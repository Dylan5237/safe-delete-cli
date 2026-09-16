"""Command dispatch and the P2-S0 machine-readable CLI surface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import CONTRACT_VERSION, SCHEMA_VERSION, __version__
from .audit import AuditReport, LedgerEntry, audit_layout, is_uuid4
from .errors import (
    EXIT_SUCCESS,
    SafeDeleteError,
    error,
    exit_code_for,
)
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
from .move import atomic_move
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
    parser.set_defaults(root=None, json=False)
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

    hook_parser = commands.add_parser("hook")
    _common_options(hook_parser)
    hook_commands = hook_parser.add_subparsers(dest="hook_command")
    install_parser = hook_commands.add_parser("install")
    _common_options(install_parser)
    install_parser.add_argument("agent", nargs="?")

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


def _print_human(envelope: dict[str, Any]) -> None:
    for result in envelope["results"]:
        if isinstance(result, str):
            print(result)
        else:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
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


def _emit(command: str, results: list[Any], errors: list[SafeDeleteError], json_mode: bool) -> int:
    envelope = _envelope(command, results, errors)
    if json_mode:
        print(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
    else:
        _print_human(envelope)
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


def _handle_list(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
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
    results: list[Any] = []
    if not args.orphans:
        for entry in sorted(report.entries.values(), key=lambda item: item.entry_id):
            if not args.all and entry.state != "active":
                continue
            if project_filter is not None and entry.creation.get("project") != project_filter:
                continue
            if original_filter is not None and entry.original_path != original_filter:
                continue
            results.append(_entry_result(entry))
    audit_errors = _audit_errors_for_list(report)
    return results, audit_errors


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
    command = "hook install" if args.command == "hook" else args.command
    return [], [
        error(
            "unsupported_command",
            f"{command} is reserved for a later phase",
            command=command,
        )
    ]


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


def _command_name(args: argparse.Namespace) -> str:
    if args.command == "hook" and getattr(args, "hook_command", None):
        return f"hook {args.hook_command}"
    return args.command or "safe-delete"


def _dispatch(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    if args.command == "init":
        return _handle_init(args)
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
    if args.command in {"purge"} or (
        args.command == "hook" and getattr(args, "hook_command", None) == "install"
    ):
        return _handle_reserved(args)
    if args.command == "add":
        return _handle_add(args)
    if args.command == "restore":
        return _handle_restore(args)
    return [], [error("usage_error", "a command is required")]


def _parse_error_command(raw_args: list[str]) -> str:
    for index, value in enumerate(raw_args):
        if value == "hook" and index + 1 < len(raw_args) and raw_args[index + 1] == "install":
            return "hook install"
        if value in {"init", "add", "list", "show", "restore", "purge", "version"}:
            return value
    return "safe-delete"


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
    try:
        results, errors = _dispatch(args)
    except SafeDeleteError as exc:
        results, errors = [], [exc]
    except RecursionError:
        results, errors = [], [error("usage_error", "value is too deeply nested")]
    except (OSError, TypeError, ValueError) as exc:
        results, errors = [], [error("storage_failure", str(exc))]
    return _emit(command, results, errors, bool(args.json))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
