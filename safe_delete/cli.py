"""Command dispatch and the P2-S0 machine-readable CLI surface."""

from __future__ import annotations

import argparse
import json
import os
import sys
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
from .move import atomic_move
from .restore import restore_entry
from .storage import (
    ensure_safe_target,
    initialize_layout,
    ledger_lock,
    normalized_path,
    require_layout,
    same_filesystem,
)


def _common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", dest="root", default=argparse.SUPPRESS, metavar="DIR")
    parser.add_argument("--json", dest="json", action="store_true", default=argparse.SUPPRESS)


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
    add_parser.add_argument("--reason")
    add_parser.add_argument("--project")
    add_parser.add_argument("--session-id")
    add_parser.add_argument("--agent")
    add_parser.add_argument("--tool")
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
        if item["code"] in {"rollback_failed", "orphan_payload"}:
            source = (
                item.get("source")
                or item.get("restore_path")
                or item.get("original_path")
                or "<not recorded>"
            )
            trash = item.get("trashed_path") or item.get("trash_path") or "<not recorded>"
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
    return {
        "entry_id": entry.entry_id,
        "state": entry.state,
        "original_path": entry.original_path,
        "trashed_path": entry.trashed_path,
        "kind": entry.kind,
        "timestamp": entry.creation["timestamp"],
    }


def _audit_errors_for_list(report: AuditReport) -> list[SafeDeleteError]:
    return list(report.errors)


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
    project_filter = normalized_path(args.project, field_name="project") if args.project else None
    original_filter = normalized_path(args.original, field_name="original") if args.original else None
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
    if args.orphans:
        audit_errors = [item for item in audit_errors if item.code == "orphan_payload"]
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
            "creation": entry.creation,
            "events": entry.events,
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


def _handle_add(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    layout = initialize_layout(args.root)
    results: list[Any] = []
    errors: list[SafeDeleteError] = []
    with ledger_lock(layout, exclusive=True):
        audit = audit_layout(layout)
        if audit.errors:
            errors = list(audit.errors)
            if args.paths:
                representative = errors[0]
                return [
                    _failed_input_result(raw_path, representative)
                    for raw_path in args.paths
                ], errors

        failed_inputs = 0
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
                    results.append(
                        {
                            "path": original_path,
                            "original_path": original_path,
                            "kind": source.kind,
                            "dry_run": True,
                        }
                    )
                    continue

                entry_id, object_directory = create_entry_directory(layout)
                payload_path = layout.payload(entry_id)
                try:
                    atomic_move(
                        original_path,
                        payload_path,
                        destination_error_code="entry_id_collision",
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
                results.append(
                    {
                        "entry_id": entry_id,
                        "path": original_path,
                        "original_path": original_path,
                        "trashed_path": str(payload_path),
                        "kind": source.kind,
                        "state": "active",
                    }
                )
            except SafeDeleteError as exc:
                exc = _with_path(exc, raw_path)
                errors.append(exc)
                results.append(_failed_input_result(raw_path, exc))
                failed_inputs += 1

    if results and failed_inputs and failed_inputs < len(args.paths):
        errors.append(
            error(
                "partial_failure",
                "one or more add inputs failed after independent processing",
                succeeded=len(results),
                failed=failed_inputs,
            )
        )
    return results, errors


def _handle_restore(args: argparse.Namespace) -> tuple[list[Any], list[SafeDeleteError]]:
    if not is_uuid4(args.entry_id):
        return [], [error("usage_error", "entry_id must be a canonical UUID v4", entry_id=args.entry_id)]
    layout = require_layout(args.root)
    destination = normalized_path(args.restore_to, field_name="restore destination") if args.restore_to else None
    with ledger_lock(layout, exclusive=True):
        report = audit_layout(layout)
        if report.errors:
            return [], list(report.errors)
        entry = report.entries.get(args.entry_id)
        if entry is None:
            return [], [error("entry_not_found", "entry was not found", entry_id=args.entry_id)]
        if entry.state == "restored":
            return [
                {
                    "entry_id": entry.entry_id,
                    "state": "restored",
                    "code": "already_restored",
                    "original_path": entry.original_path,
                    "restore_path": entry.events[-1].get("restore_path", entry.original_path),
                    "kind": entry.kind,
                }
            ], []
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
    except (OSError, TypeError, ValueError) as exc:
        results, errors = [], [error("storage_failure", str(exc))]
    return _emit(command, results, errors, bool(args.json))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
