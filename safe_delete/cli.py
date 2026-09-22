"""Command dispatch and the P2-S0 machine-readable CLI surface."""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import CONTRACT_VERSION, SCHEMA_VERSION, __version__
from .audit import AuditReport, LedgerEntry, audit_layout, is_uuid4
from .doctor import run_doctor
from .errors import (
    EXIT_SUCCESS,
    SafeDeleteError,
    error,
    exit_code_for,
)
from .human import PATH_ACTIVATION_IS_OPERATOR_OWNED
from .human import render as render_human
from .ledger import (
    append_event,
    build_trash_record,
    create_entry_directory,
    inspect_source,
    remove_empty_object_directory,
)
from .metadata import (
    RichMetadata,
    metadata_from_record,
    parse_extensions_json,
    project_record,
    validate_extensions_object,
    validate_scalar,
)
from .hook import hook_disable, hook_install, hook_status, hook_uninstall
from .move import atomic_move
from .platform_check import platform_report
from .platform_check import preflight as platform_preflight
from .purge import run_empty, run_purge
from .retention import RetentionPolicy, parse_rfc3339
from .restore import restore_entry
from .storage import (
    ensure_safe_target,
    initialize_layout,
    ledger_lock,
    layout_for,
    normalized_path,
    require_layout,
    same_filesystem,
)


def _common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", dest="root", default=argparse.SUPPRESS, metavar="DIR")
    parser.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--human", dest="human", action="store_true", default=argparse.SUPPRESS)


class _SingleValueAction(argparse.Action):
    """Reject repeated metadata flags instead of silently taking the last one."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        if getattr(namespace, self.dest, None) is not None:
            option = option_string or self.dest
            raise argparse.ArgumentError(parser, f"{option} may be specified only once")
        setattr(namespace, self.dest, values)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="safe-delete")
    parser.set_defaults(root=None, json=False, human=False)
    _common_options(parser)
    commands = parser.add_subparsers(dest="command")

    init_parser = commands.add_parser("init")
    _common_options(init_parser)

    add_parser = commands.add_parser("add")
    _common_options(add_parser)
    add_parser.add_argument("paths", nargs="+")
    add_parser.add_argument("--reason", action=_SingleValueAction)
    add_parser.add_argument("--project", action=_SingleValueAction)
    add_parser.add_argument("--session-id", action=_SingleValueAction)
    add_parser.add_argument("--agent", action=_SingleValueAction)
    add_parser.add_argument("--tool", action=_SingleValueAction)
    add_parser.add_argument("--extensions", action=_SingleValueAction)
    add_parser.add_argument("--dry-run", action="store_true")

    list_parser = commands.add_parser("list")
    _common_options(list_parser)
    list_parser.add_argument("--all", action="store_true")
    list_parser.add_argument("--orphans", action="store_true")
    list_parser.add_argument("--project")
    list_parser.add_argument("--original")
    list_parser.add_argument("--limit")

    show_parser = commands.add_parser("show")
    _common_options(show_parser)
    show_parser.add_argument("entry_id")

    restore_parser = commands.add_parser("restore")
    _common_options(restore_parser)
    restore_parser.add_argument("entry_id")
    restore_parser.add_argument("--to", dest="restore_to")
    restore_parser.add_argument("--create-parents", action="store_true")

    purge_parser = commands.add_parser("purge")
    _common_options(purge_parser)
    purge_parser.add_argument("--dry-run", action="store_true")
    purge_parser.add_argument("--execute", action="store_true")
    purge_parser.add_argument("--yes", action="store_true")
    purge_parser.add_argument("--older-than")
    purge_parser.add_argument("--before")

    setup_parser = commands.add_parser("setup")
    _common_options(setup_parser)
    setup_parser.add_argument("selector", nargs="?")
    setup_parser.add_argument("--init", action="store_true")
    setup_parser.add_argument("--host", dest="host_selector")
    setup_parser.add_argument("--config")
    setup_parser.add_argument("--project")
    setup_parser.add_argument("--cli", dest="cli_path")

    empty_parser = commands.add_parser("empty")
    _common_options(empty_parser)
    empty_parser.add_argument("--older-than")
    empty_parser.add_argument("--before")
    # ``empty`` deliberately has no --execute/--yes/--dry-run.  They stay
    # declared but hidden so that passing one is an explicit, stable
    # ``usage_error`` (exit 2) instead of argparse's generic text; see the P8
    # contract § 3.2.
    empty_parser.add_argument("--confirm", nargs="?", const="", default=None)
    for rejected in ("--execute", "--yes", "--dry-run"):
        empty_parser.add_argument(
            rejected,
            dest=rejected.lstrip("-").replace("-", "_"),
            action="store_true",
            help=argparse.SUPPRESS,
        )

    hook_parser = commands.add_parser("hook")
    _common_options(hook_parser)
    hook_commands = hook_parser.add_subparsers(dest="hook_command")
    for hook_command in ("install", "status", "disable", "uninstall"):
        management_parser = hook_commands.add_parser(hook_command)
        _common_options(management_parser)
        management_parser.add_argument("selector", nargs="?")
        management_parser.add_argument("--host", dest="host_selector")
        management_parser.add_argument("--config")
        management_parser.add_argument("--project")
        if hook_command == "install":
            management_parser.add_argument("--cli", dest="cli_path")

    doctor_parser = commands.add_parser("doctor")
    _common_options(doctor_parser)

    version_parser = commands.add_parser("version")
    _common_options(version_parser)
    return parser


def _envelope(command: str, results: list[Any], errors: list[SafeDeleteError]) -> dict[str, Any]:
    return {
        "command": command,
        "ok": not errors,
        "results": results,
        "errors": [item.as_dict() for item in errors],
    }


def _print_human(envelope: dict[str, Any], *, root: str | None = None) -> None:
    command = str(envelope.get("command") or "")
    text = render_human(command, envelope["results"], envelope["errors"], root=root)
    if text:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    for item in envelope["errors"]:
        print(
            f"safe-delete: {item['code']}: {item['message']}",
            file=sys.stderr,
        )
        has_transaction_paths = (
            item["code"] in {"rollback_failed", "orphan_payload"}
            or (
                "trashed_path" in item
                and ("source" in item or "restore_path" in item)
            )
        )
        if has_transaction_paths:
            trash = item.get("trashed_path") or item.get("trash_path") or "<not recorded>"
            if "restore_path" in item:
                print(f"  restore path: {item['restore_path']}", file=sys.stderr)
            else:
                source = item.get("source") or item.get("original_path") or "<not recorded>"
                print(f"  source path: {source}", file=sys.stderr)
            print(f"  trash path: {trash}", file=sys.stderr)
        for key, label in (
            ("recorded_config_path", "recorded config"),
            ("resolved_config_path", "resolved config"),
        ):
            if item.get(key) is not None:
                print(f"  {label}: {item[key]}", file=sys.stderr)
        steps = list(item.get("next_steps") or ())
        for index, step in enumerate(steps):
            # The first step is labelled; any further step is a continuation
            # line, matching the freeze's guided-multi-project layout.
            label = "  next: " if index == 0 else "        "
            print(f"{label}{step}", file=sys.stderr)


def _emit(
    command: str,
    results: list[Any],
    errors: list[SafeDeleteError],
    json_mode: bool,
    *,
    root: str | None = None,
) -> int:
    envelope = _envelope(command, results, errors)
    if json_mode:
        print(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
    else:
        _print_human(envelope, root=root)
    return exit_code_for(errors)


def _entry_result(entry: LedgerEntry) -> dict[str, Any]:
    result = {
        "entry_id": entry.entry_id,
        "state": entry.state,
        "original_path": entry.original_path,
        "trashed_path": entry.trashed_path,
        "kind": entry.kind,
        "timestamp": entry.creation["timestamp"],
    }
    result.update(metadata_from_record(entry.creation).projection_fields())
    return result


def _audit_errors_for_list(report: AuditReport) -> list[SafeDeleteError]:
    return list(report.errors)


_MISSING = object()


def _hook_context_from_args(
    args: argparse.Namespace,
    supplied: object = _MISSING,
) -> tuple[Mapping[str, Any], bool]:
    if supplied is not _MISSING:
        candidate = supplied
    else:
        candidate = _MISSING
        for attribute in ("hook_context", "adapter_context", "hook", "context"):
            if hasattr(args, attribute):
                candidate = getattr(args, attribute)
                break
        if candidate is _MISSING or candidate is None:
            return {}, False
    if candidate is None:
        return {}, False
    if not isinstance(candidate, Mapping):
        raise error("usage_error", "hook context must be a JSON object")
    return candidate, True


def _nearest_supported_project_root(start: str | os.PathLike[str] | None = None) -> str | None:
    """Detect the nearest Git project root, the only P3-supported detector."""

    candidate = Path(os.path.abspath(os.fspath(start or os.getcwd())))
    if not candidate.is_dir():
        candidate = candidate.parent
    while True:
        # A worktree's .git is a file, while a normal checkout uses a
        # directory; both are supported project roots.
        if os.path.lexists(candidate / ".git"):
            return normalized_path(str(candidate), field_name="project")
        if candidate.parent == candidate:
            return None
        candidate = candidate.parent


def _selected_value(
    args: argparse.Namespace,
    context: Mapping[str, Any],
    hook_present: bool,
    field_name: str,
    env_name: str | None = None,
) -> object:
    flag_value = getattr(args, field_name, _MISSING)
    if flag_value is not _MISSING and flag_value is not None:
        return flag_value
    if hook_present and field_name in context:
        return context[field_name]
    if env_name is not None and env_name in os.environ:
        return os.environ[env_name]
    return _MISSING


def resolve_metadata(
    args: argparse.Namespace,
    *,
    hook_context: object = _MISSING,
    invocation_dir: str | os.PathLike[str] | None = None,
) -> RichMetadata:
    """Resolve and validate the frozen P3 metadata source precedence."""

    context, hook_present = _hook_context_from_args(args, hook_context)

    project = _selected_value(
        args,
        context,
        hook_present,
        "project",
        "SAFE_DELETE_PROJECT",
    )
    if project is _MISSING:
        project = _nearest_supported_project_root(invocation_dir)

    session_id = _selected_value(
        args,
        context,
        hook_present,
        "session_id",
        "SAFE_DELETE_SESSION_ID",
    )
    reason = _selected_value(args, context, hook_present, "reason")
    agent = _selected_value(
        args,
        context,
        hook_present,
        "agent",
        "SAFE_DELETE_AGENT",
    )
    if session_id is _MISSING:
        session_id = None
    if reason is _MISSING:
        reason = None
    if agent is _MISSING:
        agent = None

    flag_tool = getattr(args, "tool", _MISSING)
    if flag_tool is not _MISSING and flag_tool is not None:
        tool: object = flag_tool
    elif hook_present:
        hook_tool = context.get("tool", _MISSING)
        # A hook/adapter is a known caller even when it does not identify its
        # own tool; use the same explicit direct-CLI identity in that case.
        tool = (
            "safe-delete-cli"
            if hook_tool is _MISSING or hook_tool is None or hook_tool == ""
            else hook_tool
        )
    else:
        tool = "safe-delete-cli"

    flag_extensions = getattr(args, "extensions", _MISSING)
    if flag_extensions is not _MISSING and flag_extensions is not None:
        extensions = parse_extensions_json(flag_extensions)
    elif hook_present and "extensions" in context:
        extensions = validate_extensions_object(context["extensions"])
    else:
        extensions = None

    return RichMetadata(
        project=validate_scalar("project", project, normalize_project=True),
        session_id=validate_scalar("session_id", session_id),
        reason=validate_scalar("reason", reason),
        agent=validate_scalar("agent", agent),
        tool=validate_scalar("tool", tool),
        extensions=extensions,
    )


def _handle_init(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    layout = initialize_layout(args.root)
    return [
        {
            "root": str(layout.root),
            "ledger_path": str(layout.ledger),
            "lock_path": str(layout.lock),
            "trash_path": str(layout.trash),
            "objects_path": str(layout.objects),
        }
    ], []


_EPOCH = _datetime.datetime(1970, 1, 1, tzinfo=_datetime.timezone.utc)


def _positive_limit(value: object, *, field_name: str) -> int:
    """Parse the additive ``--limit`` as a positive base-10 integer."""

    text = value if isinstance(value, str) else ""
    if not text or not text.isdigit() or text.strip() != text:
        raise error(
            "usage_error",
            f"{field_name} must be a positive base-10 integer",
            value=value,
        )
    parsed = int(text, 10)
    if parsed <= 0:
        raise error(
            "usage_error",
            f"{field_name} must be a positive base-10 integer",
            value=value,
        )
    return parsed


def _latest_event_instant(entry: LedgerEntry) -> _datetime.datetime | None:
    """Return the newest lifecycle-event instant recorded for one entry."""

    best: _datetime.datetime | None = None
    candidates: list[Any] = []
    if entry.events:
        candidates.append(entry.events[-1].get("timestamp"))
    candidates.append(entry.creation.get("timestamp"))
    for raw in candidates:
        if not isinstance(raw, str):
            continue
        try:
            parsed = parse_rfc3339(raw)
        except SafeDeleteError:
            continue
        if best is None or parsed > best:
            best = parsed
    return best


def _limit_sort_key(entry: LedgerEntry) -> tuple[int, _datetime.datetime]:
    instant = _latest_event_instant(entry)
    if instant is None:
        return (0, _EPOCH)
    return (1, instant)


def _handle_list(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    limit = None
    if getattr(args, "limit", None) is not None:
        limit = _positive_limit(args.limit, field_name="--limit")
    layout = require_layout(args.root)
    project_filter = (
        normalized_path(args.project, field_name="project")
        if args.project is not None
        else None
    )
    original_filter = (
        normalized_path(args.original, field_name="original")
        if args.original is not None
        else None
    )
    with ledger_lock(layout, exclusive=False):
        report = audit_layout(layout)
    selected: list[tuple[str, Any, LedgerEntry]] = []
    if not args.orphans:
        for entry in sorted(report.entries.values(), key=lambda item: item.entry_id):
            if not args.all and entry.state != "active":
                continue
            if project_filter is not None and entry.creation.get("project") != project_filter:
                continue
            if original_filter is not None and entry.original_path != original_filter:
                continue
            selected.append((entry.entry_id, _entry_result(entry), entry))
    if limit is not None:
        # ``--limit`` is opt-in: it re-sorts by newest lifecycle event with an
        # ``entry_id`` ascending tiebreak, then truncates.  The stable second
        # pass keeps the tiebreak ascending while the first pass is descending.
        selected.sort(key=lambda item: item[0])
        selected.sort(key=lambda item: _limit_sort_key(item[2]), reverse=True)
        selected = selected[:limit]
    audit_errors = _audit_errors_for_list(report)
    return [result for _, result, _ in selected], audit_errors


def _handle_show(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    if not is_uuid4(args.entry_id):
        return [], [error("usage_error", "entry_id must be a canonical UUID v4", entry_id=args.entry_id)]
    layout = require_layout(args.root)
    with ledger_lock(layout, exclusive=False):
        report = audit_layout(layout)
    entry = report.entries.get(args.entry_id)
    relevant_errors = report.errors_for(args.entry_id)
    if relevant_errors:
        return [], relevant_errors
    if entry is None:
        return [], [error("entry_not_found", "entry was not found", entry_id=args.entry_id)]
    return [
        {
            "entry_id": entry.entry_id,
            "state": entry.state,
            "creation": project_record(entry.creation),
            "events": [project_record(event) for event in entry.events],
        }
    ], []


def _handle_reserved(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    command = args.command
    return [], [
        error(
            "unsupported_command",
            f"{command} is reserved for a later phase",
            command=command,
        )
    ]


def _handle_hook(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    selector = args.selector
    host_selector = getattr(args, "host_selector", None)
    if selector is not None and host_selector is not None and selector != host_selector:
        return [], [error("usage_error", "hook selector and --host disagree")]
    selector = selector or host_selector
    kwargs = {
        "config": getattr(args, "config", None),
        "project": getattr(args, "project", None),
        "root": getattr(args, "root", None),
    }
    if args.hook_command == "install":
        result = hook_install(selector, cli_path=getattr(args, "cli_path", None), **kwargs)
    elif args.hook_command == "status":
        return hook_status(selector, **kwargs), []
    elif args.hook_command == "disable":
        result = hook_disable(selector, **kwargs)
    elif args.hook_command == "uninstall":
        result = hook_uninstall(selector, **kwargs)
    else:
        return [], [error("usage_error", "a hook management verb is required")]
    return [result], []


def _with_path(exc: SafeDeleteError, path: str) -> SafeDeleteError:
    if "path" in exc.details:
        return exc
    return SafeDeleteError(exc.code, exc.message, {**exc.details, "path": path})


def _rollback_trash_move(
    *,
    source_path: str,
    payload_path: str,
    object_directory: Any,
    append_error: SafeDeleteError,
) -> SafeDeleteError:
    try:
        atomic_move(payload_path, source_path)
    except SafeDeleteError as rollback_error:
        return error(
            "rollback_failed",
            "ledger append failed and trash payload rollback failed",
            source=source_path,
            trashed_path=payload_path,
            append_error=append_error.code,
            rollback_error=rollback_error.code,
        )
    try:
        remove_empty_object_directory(object_directory)
    except SafeDeleteError as cleanup_error:
        return error(
            "rollback_failed",
            "ledger append failed after move; object cleanup failed",
            source=source_path,
            trashed_path=payload_path,
            append_error=append_error.code,
            rollback_error=cleanup_error.code,
        )
    return SafeDeleteError(
        append_error.code,
        append_error.message,
        {
            **append_error.details,
            "source": source_path,
            "trashed_path": payload_path,
            "rolled_back": True,
        },
    )


def _failed_input_result(path: str, exc: SafeDeleteError) -> dict[str, Any]:
    return {
        "path": path,
        "ok": False,
        "error": exc.as_dict(),
    }


def _nearest_existing_path(path: Path) -> Path:
    """Find the read-only filesystem anchor for a conceptual dry-run target."""

    candidate = path
    while not os.path.lexists(candidate) and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def _handle_add_dry_run(
    args: argparse.Namespace,
    *,
    layout: Any,
    metadata: RichMetadata,
) -> tuple[list[Any], list[SafeDeleteError]]:
    """Validate an add preview without creating or opening durable storage."""

    results: list[Any] = []
    errors: list[SafeDeleteError] = []
    failed_inputs = 0
    succeeded_inputs = 0
    target_anchor = _nearest_existing_path(layout.objects)

    for raw_path in args.paths:
        try:
            original_path = normalized_path(raw_path)
            ensure_safe_target(layout, original_path)
            source = inspect_source(layout, original_path)
            if not same_filesystem(original_path, target_anchor):
                raise error(
                    "cross_device",
                    "source and trash objects are on different filesystems",
                    source=original_path,
                    destination=str(layout.objects),
                )
            result = {
                "path": original_path,
                "original_path": original_path,
                "kind": source.kind,
                "dry_run": True,
            }
            result.update(metadata.projection_fields())
            results.append(result)
            succeeded_inputs += 1
        except SafeDeleteError as exc:
            exc = _with_path(exc, raw_path)
            errors.append(exc)
            results.append(_failed_input_result(raw_path, exc))
            failed_inputs += 1

    if succeeded_inputs and failed_inputs:
        errors.append(
            error(
                "partial_failure",
                "one or more add inputs failed after independent processing",
                succeeded=succeeded_inputs,
                failed=failed_inputs,
            )
        )
    return results, errors


def _handle_add(
    args: argparse.Namespace,
    *,
    hook_context: object = _MISSING,
) -> tuple[list[Any], list[SafeDeleteError]]:
    results: list[Any] = []
    errors: list[SafeDeleteError] = []
    try:
        metadata = resolve_metadata(args, hook_context=hook_context)
    except SafeDeleteError as exc:
        return [
            _failed_input_result(raw_path, _with_path(exc, raw_path))
            for raw_path in args.paths
        ], [exc]
    if args.dry_run:
        try:
            layout = layout_for(args.root)
            if os.path.lexists(layout.ledger):
                layout = require_layout(str(layout.root))
                with ledger_lock(layout, exclusive=False):
                    audit = audit_layout(layout)
                if audit.errors:
                    errors = list(audit.errors)
                    representative = errors[0]
                    return [
                        _failed_input_result(raw_path, representative)
                        for raw_path in args.paths
                    ], errors
        except SafeDeleteError as exc:
            return [
                _failed_input_result(raw_path, _with_path(exc, raw_path))
                for raw_path in args.paths
            ], [exc]
        return _handle_add_dry_run(args, layout=layout, metadata=metadata)
    try:
        layout = initialize_layout(args.root)
    except SafeDeleteError as exc:
        return [
            _failed_input_result(raw_path, _with_path(exc, raw_path))
            for raw_path in args.paths
        ], [exc]
    except OSError as exc:
        failure = error("storage_failure", str(exc))
        return [
            _failed_input_result(raw_path, _with_path(failure, raw_path))
            for raw_path in args.paths
        ], [failure]

    failed_inputs = 0
    succeeded_inputs = 0
    try:
        with ledger_lock(layout, exclusive=True):
            audit = audit_layout(layout)
            if audit.errors:
                errors = list(audit.errors)
                representative = errors[0]
                return [
                    _failed_input_result(raw_path, representative)
                    for raw_path in args.paths
                ], errors

            for raw_path in args.paths:
                try:
                    original_path = normalized_path(raw_path)
                    ensure_safe_target(layout, original_path)
                    source = inspect_source(layout, original_path)
                    if not same_filesystem(original_path, layout.objects):
                        raise error(
                            "cross_device",
                            "source and trash objects are on different filesystems",
                            source=original_path,
                            destination=str(layout.objects),
                        )
                    if args.dry_run:
                        result = {
                            "path": original_path,
                            "original_path": original_path,
                            "kind": source.kind,
                            "dry_run": True,
                        }
                        result.update(metadata.projection_fields())
                        results.append(result)
                        succeeded_inputs += 1
                        continue

                    entry_id, object_directory = create_entry_directory(layout)
                    payload_path = layout.payload(entry_id)
                    try:
                        atomic_move(
                            original_path,
                            payload_path,
                            destination_error_code="entry_id_collision",
                            expected_source_stat=source.stat,
                            expected_source_kind=source.kind,
                        )
                    except SafeDeleteError as move_error:
                        try:
                            remove_empty_object_directory(object_directory)
                        except SafeDeleteError as cleanup_error:
                            raise cleanup_error from move_error
                        raise move_error

                    record = build_trash_record(
                        entry_id=entry_id,
                        original_path=original_path,
                        trashed_path=str(payload_path),
                        kind=source.kind,
                        metadata=metadata,
                    )
                    try:
                        append_event(layout, record)
                    except SafeDeleteError as append_error:
                        rollback_error = _rollback_trash_move(
                            source_path=original_path,
                            payload_path=str(payload_path),
                            object_directory=object_directory,
                            append_error=append_error,
                        )
                        errors.append(rollback_error)
                        results.append(_failed_input_result(raw_path, rollback_error))
                        failed_inputs += 1
                        continue
                    result = {
                        "entry_id": entry_id,
                        "path": original_path,
                        "original_path": original_path,
                        "trashed_path": str(payload_path),
                        "kind": source.kind,
                        "state": "active",
                    }
                    result.update(metadata.projection_fields())
                    results.append(result)
                    succeeded_inputs += 1
                except SafeDeleteError as exc:
                    exc = _with_path(exc, raw_path)
                    errors.append(exc)
                    results.append(_failed_input_result(raw_path, exc))
                    failed_inputs += 1
    except SafeDeleteError as exc:
        if not results:
            return [
                _failed_input_result(raw_path, _with_path(exc, raw_path))
                for raw_path in args.paths
            ], [exc]
        errors.append(exc)
        for raw_path in args.paths[len(results):]:
            results.append(_failed_input_result(raw_path, _with_path(exc, raw_path)))
            failed_inputs += 1
    except OSError as exc:
        failure = error("storage_failure", str(exc))
        if not results:
            return [
                _failed_input_result(raw_path, _with_path(failure, raw_path))
                for raw_path in args.paths
            ], [failure]
        errors.append(failure)
        for raw_path in args.paths[len(results):]:
            results.append(_failed_input_result(raw_path, _with_path(failure, raw_path)))
            failed_inputs += 1

    if succeeded_inputs and failed_inputs:
        errors.append(
            error(
                "partial_failure",
                "one or more add inputs failed after independent processing",
                succeeded=succeeded_inputs,
                failed=failed_inputs,
            )
        )
    return results, errors


def _handle_restore(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    if not is_uuid4(args.entry_id):
        return [], [error("usage_error", "entry_id must be a canonical UUID v4", entry_id=args.entry_id)]
    if args.restore_to is not None and args.restore_to == "":
        return [], [error("usage_error", "restore destination must not be empty")]
    layout = require_layout(args.root)
    destination = (
        normalized_path(args.restore_to, field_name="restore destination")
        if args.restore_to is not None
        else None
    )
    with ledger_lock(layout, exclusive=True):
        report = audit_layout(layout)
        if report.errors:
            return [], list(report.errors)
        entry = report.entries.get(args.entry_id)
        if entry is None:
            return [], [error("entry_not_found", "entry was not found", entry_id=args.entry_id)]
        if entry.state == "restored":
            result = {
                "entry_id": entry.entry_id,
                "state": "restored",
                "code": "already_restored",
                "original_path": entry.original_path,
                "restore_path": entry.events[-1].get("restore_path", entry.original_path),
                "kind": entry.kind,
            }
            result.update(metadata_from_record(entry.creation).projection_fields())
            return [result], []
        if entry.state == "purged":
            return [
                {
                    "entry_id": entry.entry_id,
                    "state": "purged",
                    "code": "already_purged",
                    "original_path": entry.original_path,
                    "kind": entry.kind,
                }
            ], []
        if entry.state != "active":
            return [], [
                error(
                    "entry_not_restorable",
                    "entry is not restorable in its current lifecycle state",
                    entry_id=entry.entry_id,
                    state=entry.state,
                )
            ]
        try:
            result = restore_entry(
                layout,
                entry,
                restore_path=destination,
                create_parents=args.create_parents,
            )
        except SafeDeleteError as exc:
            return [], [exc]
    return [result], []


def _handle_purge(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    if args.dry_run and args.execute:
        return [], [error("usage_error", "--dry-run and --execute are mutually exclusive")]
    if args.execute and not args.yes:
        return [], [
            error(
                "usage_error",
                "--execute requires --yes confirmation; no payloads were changed",
            )
        ]
    policy = RetentionPolicy.resolve(
        older_than=args.older_than,
        before=args.before,
    )
    layout = require_layout(args.root)
    return run_purge(layout, policy, execute=bool(args.execute))


_SETUP_SELECTOR_ALIASES = {"path": "path-shim"}
_SETUP_SELECTORS = frozenset({"claude", "cursor", "path", "path-shim", "workbuddy"})
_EMPTY_REJECTED_FLAGS = (
    ("--execute", "execute"),
    ("--yes", "yes"),
    ("--dry-run", "dry_run"),
)


def _setup_report(
    selector: str | None,
    preflight: Mapping[str, Any],
    install: Any,
    doctor: Any,
    steps: list[str],
    initialized: Any,
) -> dict[str, Any]:
    """The single ``setup`` results object, in the P8 freeze key order."""

    return {
        "selector": selector,
        "preflight": dict(preflight),
        "install": install,
        "doctor": doctor,
        "next_steps": list(steps),
        # Additive to the frozen key list: a run that created a storage root
        # must say so, because ``--init`` is the one mutation ``setup`` may make.
        "initialized": initialized,
    }


def _with_next_steps(exc: SafeDeleteError, steps: list[str]) -> SafeDeleteError:
    if not steps:
        return exc
    return SafeDeleteError(exc.code, exc.message, {**exc.details, "next_steps": list(steps)})


def _install_failure_steps(exc: SafeDeleteError, selector: str | None) -> list[str]:
    """Translate one install failure into the recorded/resolved next step."""

    if (
        exc.details.get("recorded_config_path") is not None
        and exc.details.get("resolved_config_path") is not None
    ):
        # The registry keys a host by selector alone, so a second project for
        # the same host is a fail-closed boundary mismatch.  ``setup`` never
        # retargets it; it names the two commands that do resolve it.
        return [
            f"safe-delete hook uninstall {selector}   # from the recorded project",
            f"safe-delete setup {selector}   # from the project you meant to protect",
        ]
    rerun = f"safe-delete setup {selector}" if selector else "safe-delete setup"
    return [f"resolve the reported condition, then rerun: {rerun}"]


def _setup_storage_next_step(root: str | None) -> str | None:
    try:
        require_layout(root)
    except (SafeDeleteError, OSError):
        # ``setup`` never initializes storage without the explicit --init
        # opt-in; it names the deliberate command instead.
        return "storage root is not initialized or is unusable; run: safe-delete init"
    return None


def _handle_setup(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    selector_arg = getattr(args, "selector", None)
    host_selector = getattr(args, "host_selector", None)
    if selector_arg is not None and host_selector is not None and selector_arg != host_selector:
        return [], [error("usage_error", "setup selector and --host disagree")]
    raw_selector = selector_arg or host_selector
    selector: str | None = None
    if raw_selector is not None:
        normalized = str(raw_selector).strip().lower()
        if normalized not in _SETUP_SELECTORS:
            return [], [
                error(
                    "unsupported_command",
                    f"unsupported setup selector: {raw_selector}",
                    selector=raw_selector,
                )
            ]
        selector = _SETUP_SELECTOR_ALIASES.get(normalized, normalized)

    config = getattr(args, "config", None)
    project = getattr(args, "project", None)
    cli_path = getattr(args, "cli_path", None)
    if selector is None:
        # The read-only report form mutates nothing and takes no install flags.
        if any(value is not None for value in (config, project, cli_path)):
            return [], [
                error(
                    "usage_error",
                    "setup --config/--project/--cli require a selector: claude, cursor, path, or workbuddy",
                )
            ]
    preflight = platform_report()
    steps: list[str] = []
    errors: list[SafeDeleteError] = []
    initialized: dict[str, Any] | None = None

    if args.init:
        try:
            layout = initialize_layout(args.root)
        except SafeDeleteError as exc:
            errors.append(exc)
        except OSError as exc:
            errors.append(error("storage_failure", str(exc)))
        else:
            initialized = {"root": str(layout.root), "ledger": str(layout.ledger)}

    install_result: dict[str, Any] | None = None
    install_error: SafeDeleteError | None = None
    if selector is not None and not errors:
        try:
            install_result = hook_install(
                selector,
                config=config,
                project=project,
                cli_path=cli_path,
                root=args.root,
            )
        except SafeDeleteError as exc:
            install_error = exc
        except OSError as exc:
            install_error = error("storage_failure", str(exc))

    if install_error is not None:
        # Failure honesty: the install's own category and code are propagated
        # unchanged and no success wording is produced anywhere below.
        steps.extend(_install_failure_steps(install_error, selector))
        errors.append(_with_next_steps(install_error, steps))
    elif install_result is not None:
        if install_result.get("path_activation"):
            steps.append(str(install_result["path_activation"]))
            steps.append(PATH_ACTIVATION_IS_OPERATOR_OWNED)

    storage_step = _setup_storage_next_step(args.root)
    if storage_step is not None:
        steps.insert(0, storage_step)

    doctor_result = run_doctor(args.root)
    if not errors:
        if doctor_result.get("problems"):
            steps.append(
                "review the doctor problems above: a boundary with a problem fails closed"
            )
        if selector is None:
            steps.append(
                "install a boundary with: safe-delete setup claude | cursor | path | workbuddy"
            )
    report = _setup_report(selector, preflight, install_result, doctor_result, steps, initialized)
    # The report travels with the envelope even on failure so a caller can see
    # the preflight/doctor facts alongside the propagated error; ``ok`` stays
    # false because ``errors`` is non-empty.
    return [report], errors


def _handle_empty(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    rejected = [name for name, dest in _EMPTY_REJECTED_FLAGS if getattr(args, dest, False)]
    if rejected:
        return [], [
            error(
                "usage_error",
                "empty does not accept "
                + " or ".join(rejected)
                + "; run `safe-delete empty` to preview and confirm with --confirm TOKEN",
            )
        ]
    if args.older_than is not None and args.before is not None:
        return [], [error("usage_error", "--older-than and --before are mutually exclusive")]
    confirm_token = getattr(args, "confirm", None)
    if confirm_token is not None and confirm_token == "":
        return [], [
            error("usage_error", "empty --confirm requires the token printed by a preview")
        ]
    # ``empty`` deliberately skips the environment/30-day default: with no
    # threshold flag the cutoff is this invocation's clock (``before_now``),
    # so env/default retention never narrows an ``empty`` run.  An explicit
    # threshold flag is passed through unchanged and alone, because ``purge``'s
    # frozen resolver rejects ``--older-than`` together with ``--before``.
    if args.older_than is not None:
        policy = RetentionPolicy.resolve(older_than=args.older_than)
    else:
        policy = RetentionPolicy.resolve(before="now" if args.before is None else args.before)
    layout = require_layout(args.root)
    return run_empty(layout, policy, confirm_token=confirm_token)


def _command_name(args: argparse.Namespace) -> str:
    if args.command == "hook" and getattr(args, "hook_command", None):
        return f"hook {args.hook_command}"
    return args.command or "safe-delete"


def _dispatch(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    if args.command == "init":
        return _handle_init(args)
    if args.command == "doctor":
        return [run_doctor(args.root)], []
    if args.command == "list":
        return _handle_list(args)
    if args.command == "show":
        return _handle_show(args)
    if args.command == "version":
        return [
            {
                "version": __version__,
                "contract_version": CONTRACT_VERSION,
                "schema_version": SCHEMA_VERSION,
            }
        ], []
    if args.command == "purge":
        return _handle_purge(args)
    if args.command == "setup":
        return _handle_setup(args)
    if args.command == "empty":
        return _handle_empty(args)
    if args.command == "hook":
        return _handle_hook(args)
    if args.command == "add":
        return _handle_add(args)
    if args.command == "restore":
        return _handle_restore(args)
    return [], [error("usage_error", "a command is required")]


def _parse_error_command(raw_args: list[str]) -> str:
    for index, value in enumerate(raw_args):
        if value == "hook" and index + 1 < len(raw_args) and raw_args[index + 1] in {"install", "status", "disable", "uninstall"}:
            return f"hook {raw_args[index + 1]}"
        if value in {"init", "add", "list", "show", "restore", "purge", "doctor", "version", "setup", "empty"}:
            return value
    return "safe-delete"


def _resolved_root_label(root: str | None) -> str | None:
    """Resolve the presentation-only root label without touching the filesystem."""

    try:
        return str(layout_for(root).root)
    except (SafeDeleteError, OSError, TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    json_requested = "--json" in raw_args
    command_hint = _parse_error_command(raw_args)
    try:
        args = parser.parse_args(raw_args)
    except SystemExit as exc:
        if exc.code and json_requested:
            return _emit(
                command_hint,
                [],
                [error("usage_error", "invalid command-line arguments")],
                True,
            )
        return int(exc.code or EXIT_SUCCESS)

    command = _command_name(args)
    human_requested = bool(getattr(args, "human", False))
    explicit_json = bool(getattr(args, "json", False))
    if human_requested and explicit_json:
        return _emit(
            command,
            [],
            [error("usage_error", "--json and --human are mutually exclusive")],
            True,
        )
    if args.command == "setup":
        # ``setup`` re-runs the platform preflight itself so a simulated
        # failure is observable and installs nothing.  The one-line message and
        # exit 2 match ``__main__``'s frozen platform behavior exactly.
        blocked = platform_preflight(raw_args)
        if blocked is not None:
            return blocked

    # Auto mode: human only when a terminal is actually attached.  A pipe, a
    # redirect, a cron job, or a captured subprocess keeps the frozen JSON
    # envelope byte-for-byte.
    human = human_requested or (not explicit_json and sys.stdout.isatty())
    root_label = _resolved_root_label(args.root)
    try:
        results, errors = _dispatch(args)
    except SafeDeleteError as exc:
        results, errors = [], [exc]
    except RecursionError:
        results, errors = [], [error("usage_error", "value is too deeply nested")]
    except (OSError, TypeError, ValueError) as exc:
        results, errors = [], [error("storage_failure", str(exc))]
    return _emit(command, results, errors, not human, root=root_label)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
