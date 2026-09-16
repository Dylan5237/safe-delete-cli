"""Locked, auditable physical purge of eligible trash objects."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from .audit import AuditReport, LedgerEntry, audit_layout
from .errors import SafeDeleteError, error
from .ledger import (
    append_event,
    build_purge_complete_record,
    build_purge_failed_record,
    build_purge_intent_record,
)
from .retention import Eligibility, RetentionPolicy, evaluate_entry
from .storage import Layout, has_entry, ledger_lock, open_directory_without_symlinks


def _same_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev == second.st_dev
        and first.st_ino == second.st_ino
        and stat.S_IFMT(first.st_mode) == stat.S_IFMT(second.st_mode)
    )


def _kind_for_mode(mode: int) -> str | None:
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return None


def _remove_tree_at(
    parent_fd: int,
    name: str,
    *,
    expected_stat: os.stat_result | None = None,
    display_path: str,
) -> None:
    """Remove one name without following symlinks outside the object tree."""

    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise error(
            "payload_missing",
            f"purge payload disappeared: {display_path}",
            trashed_path=display_path,
        ) from exc
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot inspect purge payload: {display_path}",
            path=display_path,
            errno=exc.errno,
        ) from exc

    if expected_stat is not None and not _same_identity(current, expected_stat):
        raise error(
            "storage_failure",
            f"purge payload changed before removal: {display_path}",
            path=display_path,
        )

    if not stat.S_ISDIR(current.st_mode) or stat.S_ISLNK(current.st_mode):
        try:
            os.unlink(name, dir_fd=parent_fd)
        except FileNotFoundError as exc:
            raise error(
                "payload_missing",
                f"purge payload disappeared: {display_path}",
                trashed_path=display_path,
            ) from exc
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot remove purge payload: {display_path}",
                path=display_path,
                errno=exc.errno,
            ) from exc
        return

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NOFOLLOW", 0):
        raise error(
            "storage_failure",
            "safe purge directory descriptors are unavailable",
            path=display_path,
        )

    child_fd: int | None = None
    try:
        try:
            child_fd = os.open(name, flags, dir_fd=parent_fd)
            opened = os.fstat(child_fd)
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot open purge directory: {display_path}",
                path=display_path,
                errno=exc.errno,
            ) from exc
        if not _same_identity(opened, current):
            raise error(
                "storage_failure",
                f"purge directory changed before removal: {display_path}",
                path=display_path,
            )

        try:
            with os.scandir(child_fd) as entries:
                child_names = [entry.name for entry in entries]
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot enumerate purge directory: {display_path}",
                path=display_path,
                errno=exc.errno,
            ) from exc
        for child_name in child_names:
            _remove_tree_at(
                child_fd,
                child_name,
                display_path=f"{display_path}/{child_name}",
            )

        try:
            after_children = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise error(
                "payload_missing",
                f"purge directory disappeared: {display_path}",
                trashed_path=display_path,
            ) from exc
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot verify purge directory: {display_path}",
                path=display_path,
                errno=exc.errno,
            ) from exc
        if not _same_identity(after_children, current):
            raise error(
                "storage_failure",
                f"purge directory was replaced: {display_path}",
                path=display_path,
            )
        try:
            os.rmdir(name, dir_fd=parent_fd)
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot remove purge directory: {display_path}",
                path=display_path,
                errno=exc.errno,
            ) from exc
    finally:
        if child_fd is not None:
            os.close(child_fd)


def remove_payload(layout: Layout, entry: LedgerEntry) -> None:
    """Remove exactly ``objects/<entry_id>/payload`` and its empty container.

    The object directory is opened through no-follow descriptors.  Only the
    expected ``payload`` child is accepted; unexpected siblings fail closed.
    Recursive directory deletion unlinks symlinks as names and never traverses
    them, so a symlink inside a trashed directory cannot redirect deletion.
    """

    expected_payload = layout.payload(entry.entry_id)
    if entry.trashed_path != str(expected_payload):
        raise error(
            "storage_failure",
            "ledger payload path does not match the storage layout",
            entry_id=entry.entry_id,
            trashed_path=entry.trashed_path,
        )

    objects_fd: int | None = None
    object_fd: int | None = None
    object_stat: os.stat_result | None = None
    try:
        try:
            objects_fd = open_directory_without_symlinks(layout.objects)
            object_stat = os.stat(
                entry.entry_id,
                dir_fd=objects_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as exc:
            raise error(
                "payload_missing",
                "purge entry has no object directory",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
            ) from exc
        except SafeDeleteError:
            raise
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot inspect purge object: {expected_payload.parent}",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
                errno=exc.errno,
            ) from exc

        if object_stat is None or not stat.S_ISDIR(object_stat.st_mode) or stat.S_ISLNK(object_stat.st_mode):
            raise error(
                "storage_failure",
                "purge object is not a real directory",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
            )
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        if not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NOFOLLOW", 0):
            raise error(
                "storage_failure",
                "safe purge directory descriptors are unavailable",
                path=str(expected_payload.parent),
            )
        try:
            object_fd = os.open(entry.entry_id, flags, dir_fd=objects_fd)
            opened_object = os.fstat(object_fd)
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot open purge object: {expected_payload.parent}",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
                errno=exc.errno,
            ) from exc
        if not _same_identity(opened_object, object_stat):
            raise error(
                "storage_failure",
                "purge object changed while opening",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
            )

        try:
            with os.scandir(object_fd) as entries:
                object_names = [item.name for item in entries]
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot inspect purge object layout: {expected_payload.parent}",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
                errno=exc.errno,
            ) from exc
        if object_names != ["payload"]:
            if "payload" not in object_names:
                raise error(
                    "payload_missing",
                    "purge object has no payload",
                    entry_id=entry.entry_id,
                    trashed_path=str(expected_payload),
                )
            raise error(
                "storage_failure",
                "purge object contains an unexpected sibling",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload.parent),
            )

        try:
            payload_stat = os.stat("payload", dir_fd=object_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise error(
                "payload_missing",
                "purge object payload is missing",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
            ) from exc
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot inspect purge payload: {expected_payload}",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
                errno=exc.errno,
            ) from exc
        if _kind_for_mode(payload_stat.st_mode) != entry.kind:
            raise error(
                "storage_failure",
                "purge payload kind changed",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
            )

        _remove_tree_at(
            object_fd,
            "payload",
            expected_stat=payload_stat,
            display_path=str(expected_payload),
        )

        try:
            with os.scandir(object_fd) as entries:
                remaining = [item.name for item in entries]
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot verify empty purge object: {expected_payload.parent}",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
                errno=exc.errno,
            ) from exc
        if remaining:
            raise error(
                "storage_failure",
                "purge object changed after payload removal",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload.parent),
            )
        os.close(object_fd)
        object_fd = None

        try:
            current_object = os.stat(
                entry.entry_id,
                dir_fd=objects_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError as exc:
            raise error(
                "storage_failure",
                "purge object disappeared after payload removal",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
            ) from exc
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot verify purge object: {expected_payload.parent}",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
                errno=exc.errno,
            ) from exc
        if not _same_identity(current_object, object_stat):
            raise error(
                "storage_failure",
                "purge object was replaced after payload removal",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
            )
        try:
            os.rmdir(entry.entry_id, dir_fd=objects_fd)
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot reclaim purge object directory: {expected_payload.parent}",
                entry_id=entry.entry_id,
                trashed_path=str(expected_payload),
                errno=exc.errno,
            ) from exc
    finally:
        if object_fd is not None:
            os.close(object_fd)
        if objects_fd is not None:
            os.close(objects_fd)


def _entry_projection(entry: LedgerEntry, decision: Eligibility) -> dict[str, Any]:
    result: dict[str, Any] = {
        "entry_id": entry.entry_id,
        "state": entry.state,
        "original_path": entry.original_path,
        "trashed_path": entry.trashed_path,
        "kind": entry.kind,
        "timestamp": entry.creation["timestamp"],
    }
    result.update(decision.as_dict())
    if entry.events:
        result["last_event"] = {
            "event_id": entry.events[-1]["event_id"],
            "operation": entry.events[-1]["operation"],
            "timestamp": entry.events[-1]["timestamp"],
        }
    return result


def _report_projection(
    *,
    policy: RetentionPolicy,
    execute: bool,
    decisions: list[dict[str, Any]],
    candidates: list[str],
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "mode": "execute" if execute else "dry_run",
        "dry_run": not execute,
        "policy": policy.as_dict(),
        "candidates": candidates,
        "decisions": decisions,
        "outcomes": outcomes,
    }


def _audit_decisions(
    report: AuditReport,
    policy: RetentionPolicy,
    *,
    audit_error: bool,
) -> tuple[list[dict[str, Any]], list[LedgerEntry], list[dict[str, Any]]]:
    decisions: list[dict[str, Any]] = []
    candidates: list[LedgerEntry] = []
    outcomes: list[dict[str, Any]] = []
    for entry in sorted(report.entries.values(), key=lambda item: item.entry_id):
        payload_present = entry.state in {"active", "purge_pending"}
        eligibility = evaluate_entry(
            entry,
            policy,
            payload_present=payload_present,
            audit_error=audit_error,
        )
        decisions.append(_entry_projection(entry, eligibility))
        if eligibility.selected and not audit_error:
            candidates.append(entry)
        elif entry.state == "purged":
            outcomes.append(
                {
                    "entry_id": entry.entry_id,
                    "state": "purged",
                    "outcome": "already_purged",
                    "code": "already_purged",
                }
            )
    return decisions, candidates, outcomes


def _entry_failure_present(entry: LedgerEntry) -> bool:
    try:
        return has_entry(entry.trashed_path)
    except SafeDeleteError:
        return False


def _remove_for_runner(layout: Layout, entry: LedgerEntry) -> None:
    """Normalize a test/integration remover's raw OSError to a safe error."""

    try:
        remove_payload(layout, entry)
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot remove purge payload: {entry.trashed_path}",
            entry_id=entry.entry_id,
            trashed_path=entry.trashed_path,
            errno=exc.errno,
        ) from exc


def _run_locked(
    layout: Layout,
    policy: RetentionPolicy,
    *,
    execute: bool,
) -> tuple[list[dict[str, Any]], list[SafeDeleteError]]:
    report = audit_layout(layout)
    decisions, candidate_entries, outcomes = _audit_decisions(
        report,
        policy,
        audit_error=bool(report.errors),
    )
    candidate_ids = [entry.entry_id for entry in candidate_entries]
    if report.errors or not execute:
        return [
            _report_projection(
                policy=policy,
                execute=execute,
                decisions=decisions,
                candidates=[] if report.errors else candidate_ids,
                outcomes=[] if report.errors else outcomes,
            )
        ], list(report.errors)

    errors: list[SafeDeleteError] = []
    removal_failures = 0
    for entry in candidate_entries:
        recovery = entry.state == "purge_pending"
        intent_event_id: str
        if recovery:
            intent_event_id = entry.events[-1]["event_id"]
        else:
            intent_record = build_purge_intent_record(entry)
            try:
                append_event(layout, intent_record)
            except SafeDeleteError as exc:
                errors.append(exc)
                outcomes.append(
                    {
                        "entry_id": entry.entry_id,
                        "state": "active",
                        "outcome": "intent_failed",
                        "code": exc.code,
                        "error": exc.as_dict(),
                    }
                )
                break
            intent_event_id = str(intent_record["event_id"])

        try:
            _remove_for_runner(layout, entry)
        except SafeDeleteError as remove_error:
            if remove_error.code == "payload_missing" or not _entry_failure_present(entry):
                missing = (
                    remove_error
                    if remove_error.code == "payload_missing"
                    else error(
                        "payload_missing",
                        "purge payload is absent after an incomplete purge",
                        entry_id=entry.entry_id,
                        trashed_path=entry.trashed_path,
                    )
                )
                errors.append(missing)
                outcomes.append(
                    {
                        "entry_id": entry.entry_id,
                        "state": "purge_pending",
                        "outcome": "blocked",
                        "code": missing.code,
                        "intent_event_id": intent_event_id,
                    }
                )
                break

            failed_record = build_purge_failed_record(entry)
            try:
                append_event(layout, failed_record)
            except SafeDeleteError as append_error:
                errors.append(append_error)
                outcomes.append(
                    {
                        "entry_id": entry.entry_id,
                        "state": "purge_pending",
                        "outcome": "failure_unrecorded",
                        "code": append_error.code,
                        "intent_event_id": intent_event_id,
                    }
                )
                break
            failure = error(
                "purge_remove_failed",
                "purge payload could not be removed; it remains active",
                entry_id=entry.entry_id,
                state="active",
                trashed_path=entry.trashed_path,
                cause=remove_error.code,
            )
            errors.append(failure)
            outcomes.append(
                {
                    "entry_id": entry.entry_id,
                    "state": "active",
                    "outcome": "failed",
                    "code": "purge_remove_failed",
                    "error_code": "purge_remove_failed",
                    "intent_event_id": intent_event_id,
                    "failed_event_id": str(failed_record["event_id"]),
                    "error": failure.as_dict(),
                }
            )
            removal_failures += 1
            continue

        complete_record = build_purge_complete_record(entry)
        try:
            append_event(layout, complete_record)
        except SafeDeleteError as exc:
            errors.append(exc)
            outcomes.append(
                {
                    "entry_id": entry.entry_id,
                    "state": "purge_pending",
                    "outcome": "completion_unrecorded",
                    "code": exc.code,
                    "intent_event_id": intent_event_id,
                }
            )
            break
        outcomes.append(
            {
                "entry_id": entry.entry_id,
                "state": "purged",
                "outcome": "purged",
                "code": "purge_complete",
                "intent_event_id": intent_event_id,
                "complete_event_id": str(complete_record["event_id"]),
                "recovered": recovery,
            }
        )

    if removal_failures:
        errors.append(
            error(
                "partial_failure",
                "one or more purge candidates could not be removed",
                succeeded=len([item for item in outcomes if item.get("outcome") == "purged"]),
                failed=removal_failures,
            )
        )
    return [
        _report_projection(
            policy=policy,
            execute=True,
            decisions=decisions,
            candidates=candidate_ids,
            outcomes=outcomes,
        )
    ], errors


def run_purge(
    layout: Layout,
    policy: RetentionPolicy,
    *,
    execute: bool,
) -> tuple[list[dict[str, Any]], list[SafeDeleteError]]:
    """Run the complete audit and candidate loop under the exclusive lock."""

    with ledger_lock(layout, exclusive=True):
        return _run_locked(layout, policy, execute=execute)
