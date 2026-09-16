"""Adapter-neutral hook enforcement and user-scoped hook installation.

The hook boundary is deliberately smaller than a shell parser.  Adapters hand
this module one already-tokenized ``argv`` vector, and this module either
rewrites a supported deletion into one ``safe-delete add`` invocation or
refuses to authorize it.  Host registration and package files are kept outside
the trash and ledger layout.

Protocol version 1 has one complete reason-code vocabulary.  Keep additions to
that vocabulary coordinated with the frozen architecture contract.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .errors import FROZEN_ERROR_CODES, SafeDeleteError, error
from .storage import layout_for, normalized_path, require_layout


HOOK_PROTOCOL_VERSION = 1
HOOK_ADAPTER_VERSION = "v1"
HOOK_COMMANDS = frozenset({"rm", "unlink", "rmdir"})
HOOK_REASON_CODES = frozenset(
    {
        "raw_delete",
        "non_delete_probe",
        "safe_delete_add",
        "unsupported_delete_invocation",
        "cli_unavailable",
        "storage_unavailable",
        "safe_delete_error",
        *FROZEN_ERROR_CODES,
    }
)
OUT_OF_COVERAGE_BYPASSES = (
    "Python/Go/Node filesystem APIs",
    "find -delete",
    "git clean",
    "busybox rm",
    "absolute /bin/rm, /bin/unlink, or /bin/rmdir",
    "another unconfigured agent/tool",
    "a container or namespace without the hook",
    "a privileged or human process",
    "PATH reordering",
    "disabled or uninstalled integration",
)
_RM_OPTION_LETTERS = frozenset({"r", "R", "f"})
_REQUEST_FIELDS = frozenset(
    {
        "protocol_version",
        "request_id",
        "tool",
        "argv",
        "cwd",
        "project",
        "session_id",
        "agent",
        "reason",
        "extensions",
    }
)
_P3_LIMITS = {
    "project": 4096,
    "session_id": 256,
    "agent": 256,
    "reason": 4096,
    "tool": 256,
}
_OWNER_MARKER = "# safe-delete-hook-owner: safe-delete/protocol-v1"


@dataclass(frozen=True)
class HookRequest:
    """The validated, adapter-neutral request received by the hook."""

    protocol_version: int
    request_id: str
    tool: str
    argv: tuple[str, ...]
    cwd: str
    project: str | None = None
    session_id: str | None = None
    agent: str | None = None
    reason: str | None = None
    extensions: dict[str, Any] | None = None


@dataclass(frozen=True)
class IntegrationSpec:
    """A supported installation selector and its host boundary."""

    selector: str
    mode: str
    adapter_path: Path
    config_path: Path | None
    event_key: str | None
    bin_dir: Path


def _response_base(payload: Any) -> tuple[int, str]:
    """Return safe echo values even when a request cannot be validated."""

    if isinstance(payload, Mapping):
        version = payload.get("protocol_version", HOOK_PROTOCOL_VERSION)
        request_id = payload.get("request_id", "")
    else:
        version = HOOK_PROTOCOL_VERSION
        request_id = ""
    if isinstance(version, bool) or not isinstance(version, int):
        version = HOOK_PROTOCOL_VERSION
    if not isinstance(request_id, str):
        request_id = ""
    return version, request_id


def _deny(
    payload: Any,
    reason_code: str = "unsupported_delete_invocation",
    message: str = "Use safe-delete add with explicit paths.",
    **details: Any,
) -> dict[str, Any]:
    version, request_id = _response_base(payload)
    result: dict[str, Any] = {
        "protocol_version": version,
        "request_id": request_id,
        "decision": "deny",
        "reason_code": reason_code,
        "message": message,
    }
    result.update(details)
    return result


def _passthrough(request: HookRequest, reason_code: str) -> dict[str, Any]:
    return {
        "protocol_version": request.protocol_version,
        "request_id": request.request_id,
        "decision": "passthrough",
        "reason_code": reason_code,
    }


def _text(value: Any, field_name: str, *, limit: int | None = None) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty UTF-8 string")
    if "\x00" in value:
        raise ValueError(f"{field_name} must not contain NUL")
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be valid UTF-8") from exc
    if limit is not None and encoded_length > limit:
        raise ValueError(f"{field_name} exceeds its maximum encoded size")
    return value


def _optional_scalar(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a UTF-8 string or null")
    if value == "" or value.strip() == "":
        return None
    value = _text(value, field_name, limit=_P3_LIMITS[field_name])
    return value


def _validate_json_value(value: Any, field_name: str) -> None:
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must contain only finite JSON values")
        return
    if isinstance(value, str):
        _json_string(value, field_name)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{field_name}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field_name} keys must be strings")
            _json_string(key, f"{field_name} key")
            _validate_json_value(item, f"{field_name}.{key}")
        return
    raise ValueError(f"{field_name} contains a value that is not JSON")


def _json_string(value: str, field_name: str) -> str:
    """Validate a JSON string without imposing P3 scalar non-empty rules."""

    if "\x00" in value:
        raise ValueError(f"{field_name} must not contain NUL")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field_name} must be valid UTF-8") from exc
    return value


def _compact_extensions(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, dict):
        raise ValueError("extensions must be a JSON object")
    _validate_json_value(value, "extensions")
    compact = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    if len(compact.encode("utf-8")) > 16 * 1024:
        raise ValueError("extensions exceeds its maximum encoded size")
    return value, compact


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_json_payload(payload: str | bytes) -> Any:
    try:
        return json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("request is not valid UTF-8 JSON") from exc


def parse_request(payload: Mapping[str, Any] | str | bytes) -> HookRequest:
    """Validate and normalize a protocol-v1 request.

    ``ValueError`` is intentionally used for this pure boundary function;
    callers that speak the wire protocol should use :func:`decide_request`,
    which converts every failure into the frozen deny response.
    """

    if isinstance(payload, (str, bytes)):
        payload = _decode_json_payload(payload)
    if not isinstance(payload, Mapping):
        raise ValueError("request must be a JSON object")
    unknown = sorted(set(payload) - _REQUEST_FIELDS)
    if unknown:
        raise ValueError(f"request contains unsupported field(s): {', '.join(unknown)}")

    version = payload.get("protocol_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != HOOK_PROTOCOL_VERSION:
        raise ValueError("protocol_version must be exactly 1")
    request_id = _text(payload.get("request_id"), "request_id")
    tool = _text(payload.get("tool"), "tool", limit=_P3_LIMITS["tool"])

    argv_value = payload.get("argv")
    if not isinstance(argv_value, (list, tuple)) or not argv_value:
        raise ValueError("argv must be a non-empty array")
    argv: list[str] = []
    for index, token in enumerate(argv_value):
        argv.append(_text(token, f"argv[{index}]"))

    cwd = _text(payload.get("cwd"), "cwd")
    if not os.path.isabs(cwd) or os.path.normpath(cwd) != cwd:
        raise ValueError("cwd must be an absolute normalized path")

    project = payload.get("project")
    if project is not None:
        project = _optional_scalar(project, "project")
        if project is not None:
            if not os.path.isabs(project):
                raise ValueError("project must be an absolute path")
            try:
                project = normalized_path(project, field_name="project")
            except SafeDeleteError as exc:
                raise ValueError(exc.message) from exc

    session_id = _optional_scalar(payload.get("session_id"), "session_id")
    agent = _optional_scalar(payload.get("agent"), "agent")
    reason = _optional_scalar(payload.get("reason"), "reason")
    extensions, _ = _compact_extensions(payload.get("extensions"))

    return HookRequest(
        protocol_version=version,
        request_id=request_id,
        tool=tool,
        argv=tuple(argv),
        cwd=cwd,
        project=project,
        session_id=session_id,
        agent=agent,
        reason=reason,
        extensions=extensions,
    )


def _classify_argv(argv: Sequence[str]) -> tuple[str, list[str] | None]:
    """Return ``(classification, operands)`` for the frozen argv policy."""

    if not argv:
        return "unsupported_delete_invocation", None
    executable = argv[0]
    if executable == "safe-delete" and len(argv) >= 2 and argv[1] == "add":
        return "safe_delete_add", None
    if executable not in HOOK_COMMANDS:
        return "unsupported_delete_invocation", None
    if len(argv) == 2 and argv[1] in {"--help", "--version"}:
        return "non_delete_probe", None

    command = executable
    options = True
    delimiter_seen = False
    operands: list[str] = []
    for token in argv[1:]:
        if options:
            if token == "--":
                options = False
                delimiter_seen = True
                continue
            if token.startswith("-"):
                if command == "rm" and len(token) >= 2 and set(token[1:]) <= _RM_OPTION_LETTERS:
                    continue
                return "unsupported_delete_invocation", None
            options = False
            operands.append(token)
            continue
        if not delimiter_seen and token == "--":
            delimiter_seen = True
            continue
        if not delimiter_seen and token.startswith("-"):
            return "unsupported_delete_invocation", None
        # Once the first delimiter has been seen, every following token,
        # including another literal "--", is an operand.
        operands.append(token)

    if not operands:
        return "non_delete_probe", None
    return "raw_delete", operands


def _absolute_operand(cwd: str, operand: str) -> str:
    candidate = operand if os.path.isabs(operand) else os.path.join(cwd, operand)
    try:
        return normalized_path(candidate, field_name="operand")
    except SafeDeleteError as exc:
        raise ValueError(exc.message) from exc


def _route_response(request: HookRequest, operands: Sequence[str], *, adapter: str) -> dict[str, Any]:
    if adapter == "pretooluse":
        tool_identity = f"pretooluse:{request.tool}"
    elif adapter == "path-shim":
        command = request.argv[0]
        if command not in HOOK_COMMANDS:
            raise ValueError("path-shim command is unsupported")
        tool_identity = f"path-shim:{command}"
    else:
        raise ValueError("unsupported hook adapter")

    safe_argv = ["safe-delete", "add"]
    if request.project is not None:
        safe_argv.extend(["--project", request.project])
    if request.session_id is not None:
        safe_argv.extend(["--session-id", request.session_id])
    if request.agent is not None:
        safe_argv.extend(["--agent", request.agent])
    if request.reason is not None:
        safe_argv.extend(["--reason", request.reason])
    if request.extensions is not None:
        _, compact = _compact_extensions(request.extensions)
        assert compact is not None
        safe_argv.extend(["--extensions", compact])
    safe_argv.extend(["--tool", tool_identity, "--"])
    safe_argv.extend(_absolute_operand(request.cwd, operand) for operand in operands)
    return {
        "protocol_version": request.protocol_version,
        "request_id": request.request_id,
        "decision": "route",
        "reason_code": "raw_delete",
        "safe_delete_argv": safe_argv,
    }


def decide_request(
    payload: Mapping[str, Any] | str | bytes,
    *,
    adapter: str = "pretooluse",
    command: str | None = None,
) -> dict[str, Any]:
    """Return the protocol-v1 decision without executing any child process."""

    try:
        request = parse_request(payload)
        if adapter == "path-shim" and command is not None and request.argv[0] != command:
            raise ValueError("path-shim argv[0] does not match its selected command")
        classification, operands = _classify_argv(request.argv)
        if classification == "safe_delete_add":
            return _passthrough(request, "safe_delete_add")
        if classification == "non_delete_probe":
            return _passthrough(request, "non_delete_probe")
        if classification != "raw_delete" or operands is None:
            return _deny(payload)
        return _route_response(request, operands, adapter=adapter)
    except (ValueError, TypeError, OSError):
        return _deny(payload)


def _home_dir() -> Path:
    raw = os.environ.get("HOME")
    if raw:
        return Path(os.path.abspath(raw))
    return Path(os.path.abspath(os.path.expanduser("~")))


def xdg_data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME") or str(_home_dir() / ".local" / "share")
    return Path(os.path.abspath(raw))


def xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME") or str(_home_dir() / ".config")
    return Path(os.path.abspath(raw))


def package_root() -> Path:
    return xdg_data_home() / "safe-delete"


def hook_registry_path() -> Path:
    return xdg_config_home() / "safe-delete" / "hooks.json"


def package_paths() -> dict[str, Path]:
    root = package_root()
    return {
        "root": root,
        "hooks": root / "hooks" / HOOK_ADAPTER_VERSION,
        "pretooluse": root / "hooks" / HOOK_ADAPTER_VERSION / "pretooluse",
        "bin": root / "bin",
        "registry": hook_registry_path(),
    }


def _safe_lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise error("storage_failure", f"cannot inspect hook path: {path}", path=str(path), errno=exc.errno) from exc


def _verify_parent_chain(path: Path) -> None:
    current = path
    missing: list[Path] = []
    while True:
        item = _safe_lstat(current)
        if item is None:
            missing.append(current)
        else:
            if stat.S_ISLNK(item.st_mode) or not stat.S_ISDIR(item.st_mode):
                raise error("storage_failure", f"hook path parent is not a directory: {current}", path=str(current))
            break
        if current.parent == current:
            break
        current = current.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            item = _safe_lstat(directory)
            if item is None or stat.S_ISLNK(item.st_mode) or not stat.S_ISDIR(item.st_mode):
                raise error("storage_failure", f"hook path parent is not a directory: {directory}", path=str(directory))
        except OSError as exc:
            raise error("storage_failure", f"cannot create hook directory: {directory}", path=str(directory), errno=exc.errno) from exc


def _mode_writable(path: Path) -> bool:
    item = _safe_lstat(path)
    if item is None:
        return False
    return bool(item.st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)) and os.access(path, os.W_OK)


def _load_json_object(path: Path, *, missing_ok: bool) -> tuple[dict[str, Any], bool]:
    item = _safe_lstat(path)
    if item is None:
        if missing_ok:
            return {}, False
        raise error("storage_failure", f"hook configuration is unavailable: {path}", path=str(path))
    if stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
        raise error("storage_failure", f"hook configuration is not a regular file: {path}", path=str(path))
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise error("storage_failure", f"hook configuration is not valid JSON: {path}", path=str(path)) from exc
    if not isinstance(value, dict):
        raise error("storage_failure", f"hook configuration must be a JSON object: {path}", path=str(path))
    return value, True


def _write_bytes_atomic(path: Path, content: bytes, *, mode: int = 0o700) -> None:
    _verify_parent_chain(path.parent)
    existing = _safe_lstat(path)
    if existing is not None:
        if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
            raise error("storage_failure", f"hook path is not a regular file: {path}", path=str(path))
        if not _mode_writable(path):
            raise error("storage_failure", f"hook path is not writable: {path}", path=str(path))
    elif not _mode_writable(path.parent):
        raise error("storage_failure", f"hook directory is not writable: {path.parent}", path=str(path.parent))
    fd: int | None = None
    temporary: Path | None = None
    try:
        fd, raw_temporary = tempfile.mkstemp(prefix=".safe-delete-", dir=path.parent)
        temporary = Path(raw_temporary)
        os.fchmod(fd, mode)
        offset = 0
        while offset < len(content):
            written = os.write(fd, content[offset:])
            if written <= 0:
                raise OSError("atomic hook write made no progress")
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = None
        os.replace(temporary, path)
        temporary = None
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except SafeDeleteError:
        raise
    except OSError as exc:
        raise error("storage_failure", f"cannot write hook file: {path}", path=str(path), errno=exc.errno) from exc
    finally:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    try:
        encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise error("storage_failure", f"cannot encode hook configuration: {path}", path=str(path)) from exc
    _write_bytes_atomic(path, encoded, mode=0o600)


def _read_registry() -> tuple[dict[str, Any], bool]:
    path = hook_registry_path()
    registry, exists = _load_json_object(path, missing_ok=True)
    if not exists:
        return {"version": 1, "integrations": {}}, False
    if registry.get("version", 1) != 1 or not isinstance(registry.get("integrations", {}), dict):
        raise error("storage_failure", f"hook registry is not a protocol-v1 object: {path}", path=str(path))
    registry.setdefault("version", 1)
    registry.setdefault("integrations", {})
    return registry, True


def _write_registry(registry: Mapping[str, Any]) -> None:
    _write_json_atomic(hook_registry_path(), registry)


def _runnable(path: Path | None) -> bool:
    if path is None:
        return False
    item = _safe_lstat(path)
    if item is None:
        return False
    if stat.S_ISLNK(item.st_mode):
        try:
            target = os.stat(path)
        except OSError:
            return False
        return stat.S_ISREG(target.st_mode) and os.access(path, os.X_OK)
    return stat.S_ISREG(item.st_mode) and os.access(path, os.X_OK)


def resolve_cli(cli_path: str | os.PathLike[str] | None = None) -> Path | None:
    """Resolve the configured CLI without resolving a deletion shim."""

    candidates: list[str] = []
    if cli_path is not None:
        candidates.append(os.fspath(cli_path))
    else:
        configured = os.environ.get("SAFE_DELETE_CLI")
        if configured:
            candidates.append(configured)
        else:
            found = shutil.which("safe-delete")
            if found:
                candidates.append(found)
            invoked = Path(sys.argv[0]) if sys.argv else None
            if invoked is not None and invoked.name == "safe-delete":
                candidates.append(str(invoked))
            source_cli = Path(__file__).resolve().parent.parent / "safe-delete"
            candidates.append(str(source_cli))
    seen: set[str] = set()
    for raw in candidates:
        if raw in seen:
            continue
        seen.add(raw)
        candidate = Path(raw)
        if "/" not in raw:
            located = shutil.which(raw)
            if located is None:
                continue
            candidate = Path(located)
        try:
            candidate = candidate.absolute()
        except OSError:
            continue
        if _runnable(candidate):
            return candidate
    return None


def _payload_text(kind: str, command: str | None = None) -> bytes:
    source_root = Path(__file__).resolve().parent.parent
    source_literal = json.dumps(str(source_root), ensure_ascii=False)
    lines = [
        "#!/usr/bin/env python3",
        _OWNER_MARKER,
        "import sys",
        f"sys.path.insert(0, {source_literal})",
        "from safe_delete.hook import main as _safe_delete_hook_main",
    ]
    if kind == "pretooluse":
        lines.append("raise SystemExit(_safe_delete_hook_main(['--adapter', 'pretooluse']))")
    elif kind == "path-shim" and command in HOOK_COMMANDS:
        command_literal = json.dumps(command)
        lines.append(
            f"raise SystemExit(_safe_delete_hook_main(['--adapter', 'path-shim', '--command', {command_literal}, *sys.argv[1:]]))"
        )
    else:
        raise ValueError("unsupported hook payload")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _owned_file(path: Path) -> bool:
    item = _safe_lstat(path)
    if item is None or stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
        return False
    try:
        with path.open("rb") as stream:
            first_lines = [
                stream.readline().decode("utf-8", errors="strict").rstrip("\r\n")
                for _ in range(4)
            ]
    except (OSError, UnicodeError):
        return False
    return _OWNER_MARKER in first_lines


def _install_owned_file(path: Path, content: bytes) -> bool:
    existing = _safe_lstat(path)
    if existing is not None:
        if not _owned_file(path):
            raise error("storage_failure", f"refusing to overwrite unowned hook file: {path}", path=str(path))
        try:
            if path.read_bytes() == content:
                return False
        except OSError as exc:
            raise error("storage_failure", f"cannot read hook file: {path}", path=str(path), errno=exc.errno) from exc
    _write_bytes_atomic(path, content, mode=0o700)
    return True


def _path_value(raw: str | os.PathLike[str], field_name: str) -> Path:
    value = os.fspath(raw)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise error("usage_error", f"{field_name} must be a non-empty path")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise error("usage_error", f"{field_name} must be valid UTF-8") from exc
    absolute = os.path.abspath(value)
    parent, basename = os.path.split(absolute)
    return Path(os.path.normpath(os.path.join(os.path.realpath(parent), basename)))


def select_integration(
    selector: str | None,
    *,
    config: str | os.PathLike[str] | None = None,
    project: str | os.PathLike[str] | None = None,
) -> IntegrationSpec:
    """Resolve the supported management selector to an exact boundary."""

    if selector is None:
        raise error("usage_error", "a hook selector is required: claude, cursor, or path-shim")
    selector = selector.strip().lower()
    if selector in {"path-shim", "rm-shim"}:
        if config is not None or project is not None:
            raise error("usage_error", "path-shim does not use a host configuration path")
        paths = package_paths()
        return IntegrationSpec("path-shim", "path-shim", paths["bin"] / "rm", None, None, paths["bin"])
    if selector not in {"claude", "cursor"}:
        raise error("unsupported_command", f"unsupported hook host: {selector}", selector=selector)

    if config is not None:
        config_path = _path_value(config, "config")
    else:
        if project is not None:
            project_path = _path_value(project, "project")
        elif selector == "cursor":
            project_path = _path_value(os.getcwd(), "project")
        else:
            project_path = None
        if selector == "claude":
            config_path = (
                project_path / ".claude" / "settings.json"
                if project_path is not None
                else _home_dir() / ".claude" / "settings.json"
            )
        else:
            assert project_path is not None
            config_path = project_path / ".cursor" / "hooks.json"
    paths = package_paths()
    return IntegrationSpec(
        selector=selector,
        mode="pretooluse",
        adapter_path=paths["pretooluse"],
        config_path=config_path,
        event_key="PreToolUse" if selector == "claude" else "preToolUse",
        bin_dir=paths["bin"],
    )


def _host_hooks(config: dict[str, Any], spec: IntegrationSpec) -> list[Any]:
    if spec.event_key is None:
        raise ValueError("path-shim has no host hooks")
    hooks = config.get("hooks")
    if hooks is None:
        hooks = {}
        config["hooks"] = hooks
    if not isinstance(hooks, dict):
        raise ValueError("host hooks field must be an object")
    value = hooks.get(spec.event_key)
    if value is None:
        value = []
        hooks[spec.event_key] = value
    if not isinstance(value, list):
        raise ValueError(f"host {spec.event_key} registration must be an array")
    return value


def _command_in_hook(value: Any, command_path: str) -> bool:
    if isinstance(value, dict):
        if value.get("command") == command_path:
            return True
        return any(_command_in_hook(item, command_path) for item in value.values())
    if isinstance(value, list):
        return any(_command_in_hook(item, command_path) for item in value)
    return False


def _has_host_registration(config: dict[str, Any], spec: IntegrationSpec) -> bool:
    if spec.config_path is None:
        return False
    try:
        hooks = _host_hooks(config, spec)
    except ValueError:
        return False
    return any(_command_in_hook(item, str(spec.adapter_path)) for item in hooks)


def _add_host_registration(config: dict[str, Any], spec: IntegrationSpec) -> bool:
    if spec.config_path is None or spec.event_key is None:
        return False
    hooks = _host_hooks(config, spec)
    command_path = str(spec.adapter_path)
    if any(_command_in_hook(item, command_path) for item in hooks):
        return False
    if spec.selector == "claude":
        hooks.append(
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": command_path}],
            }
        )
    else:
        hooks.append({"command": command_path})
    return True


def _remove_command(value: Any, command_path: str) -> tuple[Any, bool]:
    if isinstance(value, list):
        changed = False
        result: list[Any] = []
        for item in value:
            new_item, item_changed = _remove_command(item, command_path)
            changed = changed or item_changed
            if new_item is None:
                continue
            result.append(new_item)
        return result, changed
    if isinstance(value, dict):
        if value.get("command") == command_path:
            return None, True
        result = dict(value)
        changed = False
        for key, item in list(value.items()):
            new_item, item_changed = _remove_command(item, command_path)
            changed = changed or item_changed
            if new_item is None and isinstance(item, (dict, list)):
                if isinstance(item, list):
                    result[key] = []
                else:
                    result.pop(key, None)
            else:
                result[key] = new_item
        if isinstance(result.get("hooks"), list) and not result["hooks"] and set(result) <= {"matcher", "hooks"}:
            return None, True
        return result, changed
    return value, False


def _remove_host_registration(config: dict[str, Any], spec: IntegrationSpec) -> bool:
    if spec.config_path is None or spec.event_key is None:
        return False
    hooks = _host_hooks(config, spec)
    command_path = str(spec.adapter_path)
    new_hooks, changed = _remove_command(hooks, command_path)
    if changed:
        config["hooks"][spec.event_key] = new_hooks
    return changed


def _storage_status(explicit_root: str | None = None) -> dict[str, Any]:
    try:
        layout = require_layout(explicit_root)
        writable = all(_mode_writable(path) for path in (layout.root, layout.objects, layout.ledger, layout.lock))
        if not writable:
            return {
                "root": str(layout.root),
                "ledger": str(layout.ledger),
                "usable": False,
                "reason_code": "storage_unavailable",
            }
        return {"root": str(layout.root), "ledger": str(layout.ledger), "usable": True}
    except (SafeDeleteError, OSError) as exc:
        if isinstance(exc, SafeDeleteError):
            reason = exc.code
        else:
            reason = "storage_unavailable"
        try:
            fallback_layout = layout_for(explicit_root)
            root = str(fallback_layout.root)
            ledger = str(fallback_layout.ledger)
        except (SafeDeleteError, OSError):
            root = str(explicit_root) if explicit_root is not None else ""
            ledger = ""
        return {
            "root": root,
            "ledger": ledger,
            "usable": False,
            "reason_code": "storage_unavailable",
            "detail_code": reason,
        }


def _path_precedence(bin_dir: Path) -> bool:
    raw_path = os.environ.get("PATH", "")
    entries = raw_path.split(os.pathsep) if raw_path else []
    try:
        index = next(
            index
            for index, entry in enumerate(entries)
            if Path(os.path.abspath(entry or os.curdir)) == bin_dir.absolute()
        )
    except StopIteration:
        return False
    for command in HOOK_COMMANDS:
        resolved = shutil.which(command)
        if resolved is None or Path(resolved).absolute() != (bin_dir / command).absolute():
            return False
    return index == min(
        (index for index, entry in enumerate(entries) if Path(os.path.abspath(entry or os.curdir)) == bin_dir.absolute()),
        default=index,
    )


def _package_file_status(spec: IntegrationSpec) -> dict[str, Any]:
    if spec.mode == "path-shim":
        files = {
            command: _runnable(spec.bin_dir / command) and _owned_file(spec.bin_dir / command)
            for command in sorted(HOOK_COMMANDS)
        }
        return {"files": files, "complete": all(files.values()), "path_precedence": _path_precedence(spec.bin_dir)}
    owned = _runnable(spec.adapter_path) and _owned_file(spec.adapter_path)
    return {"adapter_path": str(spec.adapter_path), "adapter_runnable": owned}


def _registered_spec(spec: IntegrationSpec, entry: Mapping[str, Any] | None) -> IntegrationSpec:
    """Use the recorded host boundary for read/manage operations by default."""

    if not isinstance(entry, Mapping):
        return spec
    if spec.mode == "pretooluse":
        recorded_config = entry.get("config_path")
        if isinstance(recorded_config, str) and recorded_config:
            return replace(spec, config_path=Path(recorded_config))
    return spec


def _status_one(spec: IntegrationSpec, registry: Mapping[str, Any], *, root: str | None = None) -> dict[str, Any]:
    integrations = registry.get("integrations", {})
    entry = integrations.get(spec.selector) if isinstance(integrations, dict) else None
    enabled = bool(isinstance(entry, dict) and entry.get("enabled") is True)
    registry_valid = bool(
        isinstance(entry, dict)
        and entry.get("selector") == spec.selector
        and entry.get("mode") == spec.mode
        and entry.get("protocol_version") == HOOK_PROTOCOL_VERSION
        and entry.get("adapter_path") == str(spec.adapter_path)
        and entry.get("event_key") == spec.event_key
        and entry.get("bin_dir") == str(spec.bin_dir)
        and isinstance(entry.get("cli_path"), str)
        and bool(entry.get("cli_path"))
    )
    if spec.mode == "pretooluse":
        registry_valid = registry_valid and isinstance(entry, dict) and entry.get("config_path") == str(spec.config_path)
    else:
        registry_valid = registry_valid and isinstance(entry, dict) and entry.get("config_path") is None
    cli = resolve_cli(entry.get("cli_path") if isinstance(entry, dict) else None)
    package_status = _package_file_status(spec)
    config_exists = False
    config_valid = False
    registered = False
    config_warning: str | None = None
    if spec.config_path is not None:
        try:
            config, config_exists = _load_json_object(spec.config_path, missing_ok=True)
            config_valid = True
            if config_exists:
                registered = _has_host_registration(config, spec)
        except SafeDeleteError as exc:
            config_warning = exc.code
    storage = _storage_status(root)
    if spec.mode == "path-shim":
        package_ready = bool(package_status["complete"])
        enforced = registry_valid and enabled and package_ready and bool(package_status["path_precedence"]) and cli is not None and storage["usable"]
        boundary = {
            "shim_dir": str(spec.bin_dir),
            "prepend_path": str(spec.bin_dir),
            "path_precedence": package_status["path_precedence"],
        }
    else:
        package_ready = bool(package_status["adapter_runnable"])
        enforced = registry_valid and enabled and package_ready and registered and config_valid and cli is not None and storage["usable"]
        boundary = {
            "config_path": str(spec.config_path),
            "registered": registered,
        }
    result: dict[str, Any] = {
        "selector": spec.selector,
        "mode": spec.mode,
        "enabled": enabled,
        "installed": isinstance(entry, dict),
        "registry_valid": registry_valid,
        "enforced": enforced,
        "cli_path": str(cli) if cli is not None else (entry.get("cli_path") if isinstance(entry, dict) else None),
        "package": {"version": HOOK_ADAPTER_VERSION, **package_status},
        "boundary": boundary,
        "storage": storage,
        "out_of_coverage": list(OUT_OF_COVERAGE_BYPASSES),
    }
    if not enabled:
        result["warning"] = "raw deletion is outside the configured boundary while this integration is disabled"
    elif config_warning is not None:
        result["warning"] = f"configuration is ambiguous or unavailable: {config_warning}"
    elif not enforced:
        result["warning"] = "integration is installed but enforcement is not proven at this boundary"
    return result


def hook_status(
    selector: str | None = None,
    *,
    config: str | os.PathLike[str] | None = None,
    project: str | os.PathLike[str] | None = None,
    root: str | None = None,
) -> list[dict[str, Any]]:
    registry, _ = _read_registry()
    if selector is not None:
        spec = select_integration(selector, config=config, project=project)
        if config is None and project is None:
            spec = _registered_spec(spec, _registry_entry_for(spec, registry))
        return [_status_one(spec, registry, root=root)]
    result: list[dict[str, Any]] = []
    for name in ("claude", "cursor", "path-shim"):
        spec = select_integration(name)
        spec = _registered_spec(spec, _registry_entry_for(spec, registry))
        result.append(_status_one(spec, registry, root=root))
    return result


def _ensure_host_config(spec: IntegrationSpec) -> tuple[dict[str, Any], bool]:
    assert spec.config_path is not None
    config, exists = _load_json_object(spec.config_path, missing_ok=True)
    try:
        _host_hooks(config, spec)
    except ValueError as exc:
        raise error("storage_failure", f"host configuration is ambiguous: {spec.config_path}", path=str(spec.config_path)) from exc
    if exists and not _mode_writable(spec.config_path):
        raise error("storage_failure", f"host configuration is not writable: {spec.config_path}", path=str(spec.config_path))
    if not exists:
        _verify_parent_chain(spec.config_path.parent)
    return config, exists


def hook_install(
    selector: str | None,
    *,
    config: str | os.PathLike[str] | None = None,
    project: str | os.PathLike[str] | None = None,
    cli_path: str | os.PathLike[str] | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    spec = select_integration(selector, config=config, project=project)
    resolved_cli = resolve_cli(cli_path)
    if resolved_cli is None:
        raise error("storage_failure", "safe-delete CLI is unavailable; installation is not enabled")
    host_config: dict[str, Any] | None = None
    host_exists = False
    if spec.mode == "pretooluse":
        host_config, host_exists = _ensure_host_config(spec)
    registry, _ = _read_registry()
    integrations = registry.setdefault("integrations", {})
    if not isinstance(integrations, dict):  # defensive after registry validation
        raise error("storage_failure", "hook registry integrations must be an object")

    created_files: list[Path] = []
    changed = False
    changed_host = False
    try:
        if spec.mode == "pretooluse":
            assert host_config is not None
            adapter_was_present = _safe_lstat(spec.adapter_path) is not None
            if _install_owned_file(spec.adapter_path, _payload_text("pretooluse")):
                changed = True
                if not adapter_was_present:
                    created_files.append(spec.adapter_path)
            changed_host = _add_host_registration(host_config, spec)
            changed = changed or changed_host
            if changed_host or not host_exists:
                assert spec.config_path is not None
                _write_json_atomic(spec.config_path, host_config)
        else:
            for command in sorted(HOOK_COMMANDS):
                path = spec.bin_dir / command
                was_present = _safe_lstat(path) is not None
                if _install_owned_file(path, _payload_text("path-shim", command)):
                    changed = True
                    if not was_present:
                        created_files.append(path)
        desired_entry = {
            "selector": spec.selector,
            "mode": spec.mode,
            "enabled": True,
            "protocol_version": HOOK_PROTOCOL_VERSION,
            "adapter_path": str(spec.adapter_path),
            "config_path": str(spec.config_path) if spec.config_path is not None else None,
            "event_key": spec.event_key,
            "bin_dir": str(spec.bin_dir),
            "cli_path": str(resolved_cli),
        }
        if integrations.get(spec.selector) != desired_entry:
            integrations[spec.selector] = desired_entry
            changed = True
            _write_registry(registry)
    except Exception:
        # A package payload is harmless but should not be left as an apparently
        # installed integration when registration itself failed.  Never remove
        # a file that existed before this transaction.
        for path in created_files:
            try:
                path.unlink()
            except OSError:
                pass
        raise
    result = _status_one(spec, registry, root=root)
    result["changed"] = changed
    result["config_created"] = not host_exists if spec.mode == "pretooluse" else False
    result["path_activation"] = f"prepend {spec.bin_dir} to PATH" if spec.mode == "path-shim" else None
    return result


def _registry_entry_for(spec: IntegrationSpec, registry: Mapping[str, Any]) -> dict[str, Any] | None:
    integrations = registry.get("integrations", {})
    if not isinstance(integrations, dict):
        return None
    value = integrations.get(spec.selector)
    return value if isinstance(value, dict) else None


def hook_disable(
    selector: str | None,
    *,
    config: str | os.PathLike[str] | None = None,
    project: str | os.PathLike[str] | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    spec = select_integration(selector, config=config, project=project)
    registry, _ = _read_registry()
    entry = _registry_entry_for(spec, registry)
    spec = _registered_spec(spec, entry) if config is None and project is None else spec
    was_enabled = bool(entry and entry.get("enabled"))
    changed_host = False
    if spec.mode == "pretooluse" and spec.config_path is not None:
        host_config, exists = _load_json_object(spec.config_path, missing_ok=True)
        if exists:
            try:
                changed_host = _remove_host_registration(host_config, spec)
            except ValueError as exc:
                raise error("storage_failure", f"host configuration is ambiguous: {spec.config_path}", path=str(spec.config_path)) from exc
            if changed_host:
                if not _mode_writable(spec.config_path):
                    raise error("storage_failure", f"host configuration is not writable: {spec.config_path}", path=str(spec.config_path))
                _write_json_atomic(spec.config_path, host_config)
    if entry is not None:
        updated_entry = dict(entry)
        updated_entry["enabled"] = False
        registry["integrations"][spec.selector] = updated_entry
        if was_enabled:
            _write_registry(registry)
        entry = updated_entry
    result = _status_one(spec, registry, root=root)
    result["changed"] = was_enabled or changed_host
    result["raw_delete_outside_boundary"] = True
    return result


def _remove_owned_file(path: Path) -> bool:
    item = _safe_lstat(path)
    if item is None:
        return False
    if not _owned_file(path):
        raise error("storage_failure", f"refusing to remove unowned hook file: {path}", path=str(path))
    try:
        path.unlink()
    except OSError as exc:
        raise error("storage_failure", f"cannot remove hook file: {path}", path=str(path), errno=exc.errno) from exc
    return True


def hook_uninstall(
    selector: str | None,
    *,
    config: str | os.PathLike[str] | None = None,
    project: str | os.PathLike[str] | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    spec = select_integration(selector, config=config, project=project)
    registry, _ = _read_registry()
    entry = _registry_entry_for(spec, registry)
    spec = _registered_spec(spec, entry) if config is None and project is None else spec

    # Prove package ownership before changing the registry.  Host config is
    # also validated before any package file is removed.
    host_config: dict[str, Any] | None = None
    host_exists = False
    host_changed = False
    if spec.mode == "pretooluse" and spec.config_path is not None:
        host_config, host_exists = _load_json_object(spec.config_path, missing_ok=True)
        if host_exists:
            try:
                host_changed = _remove_host_registration(host_config, spec)
            except ValueError as exc:
                raise error("storage_failure", f"host configuration is ambiguous: {spec.config_path}", path=str(spec.config_path)) from exc
            if host_changed and not _mode_writable(spec.config_path):
                raise error("storage_failure", f"host configuration is not writable: {spec.config_path}", path=str(spec.config_path))
    package_files = (
        [spec.adapter_path]
        if spec.mode == "pretooluse"
        else [spec.bin_dir / command for command in HOOK_COMMANDS]
    )
    package_present = any(_safe_lstat(path) is not None for path in package_files)
    for path in package_files:
        item = _safe_lstat(path)
        if item is not None and not _owned_file(path):
            raise error("storage_failure", f"refusing to remove unowned hook file: {path}", path=str(path))

    if host_changed and host_config is not None and spec.config_path is not None:
        _write_json_atomic(spec.config_path, host_config)
    for path in package_files:
        _remove_owned_file(path)
    if entry is not None:
        registry["integrations"].pop(spec.selector, None)
        _write_registry(registry)
    result = _status_one(spec, registry, root=root)
    result["changed"] = bool(entry or host_changed or package_present)
    result["raw_delete_outside_boundary"] = True
    return result


def management_selectors() -> tuple[str, ...]:
    """Selectors intentionally advertised by ``safe-delete hook``."""

    return ("claude", "cursor", "path-shim", "rm-shim")


def _integration_is_registered(adapter: str) -> bool:
    """Check the package registry before an adapter authorizes a deletion."""

    try:
        registry, _ = _read_registry()
    except SafeDeleteError:
        return False
    integrations = registry.get("integrations", {})
    if not isinstance(integrations, dict):
        return False
    if adapter == "path-shim":
        entry = integrations.get("path-shim")
        spec = select_integration("path-shim")
        return bool(
            isinstance(entry, dict)
            and entry.get("enabled") is True
            and entry.get("selector") == spec.selector
            and entry.get("mode") == "path-shim"
            and entry.get("protocol_version") == HOOK_PROTOCOL_VERSION
            and entry.get("adapter_path") == str(spec.adapter_path)
            and entry.get("config_path") is None
            and entry.get("event_key") is None
            and entry.get("bin_dir") == str(spec.bin_dir)
            and isinstance(entry.get("cli_path"), str)
            and bool(entry.get("cli_path"))
            and all(
                _runnable(spec.bin_dir / command)
                and _owned_file(spec.bin_dir / command)
                for command in HOOK_COMMANDS
            )
        )
    if adapter != "pretooluse":
        return False
    adapter_path = str(package_paths()["pretooluse"])
    for entry in integrations.values():
        if not isinstance(entry, dict) or entry.get("enabled") is not True:
            continue
        selector = entry.get("selector")
        if selector not in {"claude", "cursor"}:
            continue
        config_path = entry.get("config_path")
        if not isinstance(config_path, str) or not config_path:
            continue
        try:
            expected = select_integration(selector, config=config_path)
            if (
                entry.get("mode") != "pretooluse"
                or entry.get("protocol_version") != HOOK_PROTOCOL_VERSION
                or entry.get("adapter_path") != adapter_path
                or entry.get("event_key") != expected.event_key
                or entry.get("bin_dir") != str(expected.bin_dir)
                or entry.get("config_path") != str(expected.config_path)
                or not isinstance(entry.get("cli_path"), str)
                or not entry.get("cli_path")
            ):
                continue
            spec = expected
            config, exists = _load_json_object(spec.config_path, missing_ok=True)
            if (
                exists
                and _runnable(spec.adapter_path)
                and _owned_file(spec.adapter_path)
                and _has_host_registration(config, spec)
            ):
                return True
        except (SafeDeleteError, ValueError):
            continue
    return False


def _registered_cli_path(adapter: str) -> Path | None:
    """Find the CLI captured at install time for a relocated payload."""

    try:
        registry, _ = _read_registry()
    except SafeDeleteError:
        return None
    integrations = registry.get("integrations", {})
    if not isinstance(integrations, dict):
        return None
    if adapter == "path-shim":
        candidates = [integrations.get("path-shim")]
    elif adapter == "pretooluse":
        candidates = [
            value
            for value in integrations.values()
            if isinstance(value, dict) and value.get("mode") == "pretooluse"
        ]
    else:
        candidates = []
    for entry in candidates:
        if isinstance(entry, dict) and isinstance(entry.get("cli_path"), str):
            candidate = resolve_cli(entry["cli_path"])
            if candidate is not None:
                return candidate
    return None


@dataclass(frozen=True)
class HookExecution:
    """The normalized response plus the process result at an adapter edge."""

    response: dict[str, Any]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    executed: bool = False


def _request_mapping(request: HookRequest) -> dict[str, Any]:
    value: dict[str, Any] = {
        "protocol_version": request.protocol_version,
        "request_id": request.request_id,
        "tool": request.tool,
        "argv": list(request.argv),
        "cwd": request.cwd,
    }
    for name in ("project", "session_id", "agent", "reason", "extensions"):
        item = getattr(request, name)
        if item is not None:
            value[name] = item
    return value


def _storage_ready(environment: Mapping[str, str] | None = None) -> bool:
    """Check the selected runtime root without creating or changing it."""

    try:
        explicit_root = None
        if environment is not None and "SAFE_DELETE_ROOT" in environment:
            explicit_root = environment["SAFE_DELETE_ROOT"]
        layout = require_layout(explicit_root)
        return all(
            _mode_writable(path)
            for path in (layout.root, layout.trash, layout.objects, layout.ledger, layout.lock)
        )
    except (SafeDeleteError, OSError):
        return False


def _child_environment(
    base: Mapping[str, str] | None = None,
    *,
    cli_path: Path | None = None,
    remove_shim_dir: bool = False,
) -> dict[str, str]:
    environment = dict(os.environ if base is None else base)
    entries = environment.get("PATH", "").split(os.pathsep) if environment.get("PATH") else []
    if remove_shim_dir:
        shim_dir = package_paths()["bin"].absolute()
        entries = [
            entry
            for entry in entries
            if Path(os.path.abspath(entry or os.curdir)) != shim_dir
        ]
    if cli_path is not None:
        cli_parent = str(cli_path.parent)
        if cli_parent not in entries:
            entries.insert(0, cli_parent)
    environment["PATH"] = os.pathsep.join(entries)
    return environment


def _decode_child_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _cli_error_code(stdout: str, stderr: str) -> str | None:
    """Extract a frozen CLI code from JSON or human child output."""

    for stream in (stdout, stderr):
        for line in stream.splitlines():
            try:
                value = json.loads(line)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if isinstance(value, dict):
                errors = value.get("errors")
                if isinstance(errors, list):
                    for item in errors:
                        if isinstance(item, dict) and item.get("code") in FROZEN_ERROR_CODES:
                            return str(item["code"])
    known = sorted(FROZEN_ERROR_CODES, key=len, reverse=True)
    if known:
        pattern = re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(code) for code in known) + r")(?![A-Za-z0-9_])")
        for stream in (stderr, stdout):
            match = pattern.search(stream)
            if match:
                return match.group(0)
    return None


def _child_result(
    completed: Any,
    *,
    request: HookRequest,
    original_response: dict[str, Any],
    routed: bool,
    safe_delete_child: bool,
) -> HookExecution:
    returncode = getattr(completed, "returncode", None)
    if isinstance(returncode, bool) or not isinstance(returncode, int):
        returncode = 1
    stdout = _decode_child_output(getattr(completed, "stdout", ""))
    stderr = _decode_child_output(getattr(completed, "stderr", ""))
    if returncode == 0:
        return HookExecution(original_response, 0, stdout, stderr, True)
    if not routed or not safe_delete_child:
        return HookExecution(original_response, returncode, stdout, stderr, True)
    code = _cli_error_code(stdout, stderr)
    reason_code = code or "safe_delete_error"
    message = (
        f"safe-delete add failed: {code}."
        if code is not None
        else "safe-delete add failed."
    )
    response = _deny(
        _request_mapping(request),
        reason_code,
        message,
    )
    if code is not None:
        exit_code = SafeDeleteError(code, message).exit_code
    else:
        exit_code = returncode
    if exit_code == 0:
        exit_code = returncode or 1
    return HookExecution(response, exit_code, stdout, stderr, True)


def _run_child(
    argv: Sequence[str],
    *,
    cwd: str,
    environment: Mapping[str, str],
    runner: Any | None,
) -> Any:
    if runner is not None:
        return runner(list(argv), cwd=cwd, env=dict(environment))
    return subprocess.run(
        list(argv),
        cwd=cwd,
        env=dict(environment),
        capture_output=True,
        text=True,
        check=False,
    )


def _unavailable_execution(
    request: HookRequest,
    *,
    reason_code: str,
    message: str,
    exit_code: int = 1,
) -> HookExecution:
    return HookExecution(
        _deny(_request_mapping(request), reason_code, message),
        exit_code,
        executed=False,
    )


def execute_request(
    payload: Mapping[str, Any] | str | bytes,
    *,
    adapter: str = "pretooluse",
    command: str | None = None,
    cli_path: str | os.PathLike[str] | None = None,
    runner: Any | None = None,
    environment: Mapping[str, str] | None = None,
    require_registration: bool = True,
) -> HookExecution:
    """Decide and execute exactly one authorized child vector.

    ``runner`` is a test seam with the same keyword arguments as the internal
    subprocess call.  It is never used to execute the original raw vector for
    a routed request.
    """

    try:
        request = parse_request(payload)
    except (ValueError, TypeError):
        return HookExecution(_deny(payload), 1, executed=False)

    response = decide_request(_request_mapping(request), adapter=adapter, command=command)
    decision = response.get("decision")
    if decision == "deny":
        return HookExecution(response, 1, executed=False)
    if decision == "route" and require_registration:
        try:
            registered = _integration_is_registered(adapter)
        except (SafeDeleteError, OSError, TypeError, ValueError):
            registered = False
        if not registered:
            return _unavailable_execution(
                request,
                reason_code="unsupported_delete_invocation",
                message="hook integration is not registered or enabled; raw deletion was not executed.",
            )
    if not os.path.isdir(request.cwd):
        return _unavailable_execution(
            request,
            reason_code="unsupported_delete_invocation",
            message="invocation cwd is unavailable; deletion was not executed.",
        )

    safe_delete_child = decision == "route" or response.get("reason_code") == "safe_delete_add"
    resolved_cli: Path | None = None
    if safe_delete_child:
        resolved_cli = resolve_cli(cli_path)
        if (
            resolved_cli is None
            and cli_path is None
            and "SAFE_DELETE_CLI" not in os.environ
        ):
            resolved_cli = _registered_cli_path(adapter)
        if resolved_cli is None:
            return _unavailable_execution(
                request,
                reason_code="cli_unavailable",
                message="safe-delete CLI is unavailable; raw deletion was not executed.",
            )
    if decision == "route" and not _storage_ready(environment):
        return _unavailable_execution(
            request,
            reason_code="storage_unavailable",
            message="safe-delete storage is unavailable; raw deletion was not executed.",
        )

    base_environment = environment
    child_environment = _child_environment(
        base_environment,
        cli_path=resolved_cli if safe_delete_child else None,
        remove_shim_dir=adapter == "path-shim" and not safe_delete_child,
    )
    if decision == "route":
        child_argv = response["safe_delete_argv"]
    else:
        child_argv = list(request.argv)
    try:
        completed = _run_child(
            child_argv,
            cwd=request.cwd,
            environment=child_environment,
            runner=runner,
        )
    except (FileNotFoundError, PermissionError, OSError):
        if safe_delete_child:
            return _unavailable_execution(
                request,
                reason_code="cli_unavailable",
                message="safe-delete CLI could not be started; raw deletion was not executed.",
            )
        return _unavailable_execution(
            request,
            reason_code="safe_delete_error",
            message="passthrough command could not be started.",
        )
    except Exception:
        return _unavailable_execution(
            request,
            reason_code="safe_delete_error",
            message="hook child execution failed; raw deletion was not executed.",
        )
    return _child_result(
        completed,
        request=request,
        original_response=response,
        routed=decision == "route",
        safe_delete_child=safe_delete_child,
    )


def path_shim_request(
    command: str,
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a protocol request for an installed package-owned shim."""

    if command not in HOOK_COMMANDS:
        raise ValueError("unsupported path-shim command")
    raw_argv = list(argv)
    if not raw_argv:
        raw_argv = [command]
    normalized_argv = [command, *raw_argv[1:]]
    env = os.environ if environ is None else environ
    request: dict[str, Any] = {
        "protocol_version": HOOK_PROTOCOL_VERSION,
        # This is a correlation value, not an identity value.  No session or
        # agent identity is synthesized for a PATH invocation.
        "request_id": str(uuid.uuid4()),
        "tool": "path-shim",
        "argv": normalized_argv,
        "cwd": os.getcwd() if cwd is None else cwd,
    }
    for field_name, environment_name in (
        ("project", "SAFE_DELETE_PROJECT"),
        ("session_id", "SAFE_DELETE_SESSION_ID"),
        ("agent", "SAFE_DELETE_AGENT"),
    ):
        if environment_name in env:
            request[field_name] = env[environment_name]
    return request


def _write_text(stream: Any, value: str) -> None:
    if not value:
        return
    try:
        stream.write(value)
    except TypeError:
        stream.write(value.encode("utf-8", errors="replace"))


def main(argv: Sequence[str] | None = None) -> int:
    """Run an installed PreToolUse adapter or PATH shim payload."""

    raw_args = list(sys.argv[1:] if argv is None else argv)
    if len(raw_args) < 2 or raw_args[0] != "--adapter":
        print("safe-delete hook adapter: --adapter pretooluse|path-shim is required", file=sys.stderr)
        return 2
    adapter = raw_args[1]
    if adapter == "pretooluse":
        if len(raw_args) != 2:
            print("safe-delete hook adapter: pretooluse does not accept argv", file=sys.stderr)
            return 2
        payload = sys.stdin.buffer.read()
        execution = execute_request(payload, adapter="pretooluse")
        print(json.dumps(execution.response, ensure_ascii=False, separators=(",", ":")))
        _write_text(sys.stderr, execution.stdout)
        _write_text(sys.stderr, execution.stderr)
        return execution.exit_code
    if adapter != "path-shim" or len(raw_args) < 4 or raw_args[2] != "--command":
        print("safe-delete hook adapter: invalid adapter arguments", file=sys.stderr)
        return 2
    command = raw_args[3]
    if command not in HOOK_COMMANDS:
        print("safe-delete hook adapter: unsupported path-shim command", file=sys.stderr)
        return 2
    request = path_shim_request(command, [command, *raw_args[4:]])
    execution = execute_request(request, adapter="path-shim", command=command)
    if execution.response.get("decision") == "deny":
        print(
            f"safe-delete hook: {execution.response.get('reason_code', 'safe_delete_error')}: "
            f"{execution.response.get('message', 'deletion denied.')}",
            file=sys.stderr,
        )
    else:
        _write_text(sys.stdout, execution.stdout)
        _write_text(sys.stderr, execution.stderr)
    return execution.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
