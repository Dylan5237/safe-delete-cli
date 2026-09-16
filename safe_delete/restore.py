"""Safe restore transaction for one active P2 ledger entry."""

from __future__ import annotations

import errno
import os
from pathlib import Path

from .audit import LedgerEntry
from .errors import SafeDeleteError, error
from .ledger import append_event, build_restore_record
from .move import atomic_move
from .storage import Layout, ensure_safe_target, has_entry, same_filesystem


def _existing_parent(path: Path) -> Path:
    cursor = path
    while True:
        try:
            os.lstat(cursor)
        except FileNotFoundError:
            if cursor.parent == cursor:
                return cursor
            cursor = cursor.parent
            continue
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot inspect restore parent: {cursor}",
                path=str(cursor),
                errno=exc.errno,
            ) from exc
        return cursor


def _make_missing_parents(parent: Path) -> list[Path]:
    missing: list[Path] = []
    cursor = parent
    while True:
        try:
            st = os.lstat(cursor)
        except FileNotFoundError:
            missing.append(cursor)
            if cursor.parent == cursor:
                break
            cursor = cursor.parent
            continue
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot inspect restore parent: {cursor}",
                path=str(cursor),
                errno=exc.errno,
            ) from exc
        if not os.path.isdir(cursor) or os.path.islink(cursor):
            raise error(
                "destination_parent_missing",
                f"restore parent is not a real directory: {cursor}",
                path=str(cursor),
            )
        break

    created: list[Path] = []
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o700)
        except FileExistsError:
            try:
                st = os.lstat(directory)
            except OSError as exc:
                raise error(
                    "storage_failure",
                    f"cannot inspect restore parent after a race: {directory}",
                    path=str(directory),
                    errno=exc.errno,
                ) from exc
            if os.path.islink(directory) or not os.path.isdir(directory):
                raise error(
                    "destination_parent_missing",
                    f"restore parent is not a real directory: {directory}",
                    path=str(directory),
                )
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot create restore parent: {directory}",
                path=str(directory),
                errno=exc.errno,
            ) from exc
        else:
            created.append(directory)
    return created


def _remove_created_parents(created: list[Path]) -> None:
    for directory in reversed(created):
        try:
            os.rmdir(directory)
        except FileNotFoundError:
            continue
        except OSError:
            # A user or concurrent process may have populated a newly-created
            # parent. Never remove non-empty data while trying to clean up.
            continue


def _rollback_restore(
    *,
    destination: str,
    payload: str,
    created_parents: list[Path],
    append_error: SafeDeleteError,
) -> SafeDeleteError:
    try:
        atomic_move(destination, payload)
    except SafeDeleteError as rollback_error:
        return error(
            "rollback_failed",
            "restore ledger append failed and payload rollback failed",
            restore_path=destination,
            trashed_path=payload,
            append_error=append_error.code,
            rollback_error=rollback_error.code,
        )
    _remove_created_parents(created_parents)
    return SafeDeleteError(
        append_error.code,
        append_error.message,
        {
            **append_error.details,
            "restore_path": destination,
            "trashed_path": payload,
            "rolled_back": True,
        },
    )


def restore_entry(
    layout: Layout,
    entry: LedgerEntry,
    *,
    restore_path: str | None,
    create_parents: bool,
) -> dict[str, object]:
    """Restore an active entry; the caller must hold the exclusive ledger lock."""

    payload = layout.payload(entry.entry_id)
    if not has_entry(payload):
        raise error(
            "payload_missing",
            "active ledger entry has no payload",
            entry_id=entry.entry_id,
            trashed_path=str(payload),
        )

    destination = restore_path or entry.original_path
    destination_path = Path(destination)
    ensure_safe_target(layout, destination)
    if has_entry(destination_path):
        raise error(
            "destination_exists",
            f"restore destination already exists: {destination}",
            entry_id=entry.entry_id,
            path=destination,
        )

    parent = destination_path.parent
    try:
        parent_stat = os.stat(parent)
    except FileNotFoundError:
        if not create_parents:
            raise error(
                "destination_parent_missing",
                f"restore destination parent is missing: {parent}",
                entry_id=entry.entry_id,
                path=str(parent),
            )
        nearest = _existing_parent(parent)
        try:
            nearest_stat = os.stat(nearest)
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot inspect nearest restore parent: {nearest}",
                entry_id=entry.entry_id,
                path=str(nearest),
                errno=exc.errno,
            ) from exc
        try:
            payload_parent_stat = os.stat(payload.parent)
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot inspect trash payload parent: {payload.parent}",
                entry_id=entry.entry_id,
                path=str(payload.parent),
                errno=exc.errno,
            ) from exc
        if nearest_stat.st_dev != payload_parent_stat.st_dev:
            raise error(
                "cross_device",
                "restore destination and trash are on different filesystems",
                entry_id=entry.entry_id,
                destination=destination,
                trashed_path=str(payload),
            )
        created_parents = _make_missing_parents(parent)
        try:
            parent_stat = os.stat(parent)
        except OSError as exc:
            _remove_created_parents(created_parents)
            raise error(
                "storage_failure",
                f"cannot inspect created restore parent: {parent}",
                entry_id=entry.entry_id,
                path=str(parent),
                errno=exc.errno,
            ) from exc
    except OSError as exc:
        if exc.errno in {errno.ENOTDIR, errno.ELOOP}:
            raise error(
                "destination_parent_missing",
                f"restore destination parent is not a directory: {parent}",
                entry_id=entry.entry_id,
                path=str(parent),
            ) from exc
        raise error(
            "storage_failure",
            f"cannot inspect restore destination parent: {parent}",
            entry_id=entry.entry_id,
            path=str(parent),
            errno=exc.errno,
        ) from exc
    else:
        if not os.path.isdir(parent) or os.path.islink(parent):
            raise error(
                "destination_parent_missing",
                f"restore destination parent is not a real directory: {parent}",
                entry_id=entry.entry_id,
                path=str(parent),
            )
        created_parents = []

    try:
        if parent_stat.st_dev != os.stat(payload.parent).st_dev:
            raise error(
                "cross_device",
                "restore destination and trash are on different filesystems",
                entry_id=entry.entry_id,
                destination=destination,
                trashed_path=str(payload),
            )
        atomic_move(payload, destination_path)
    except SafeDeleteError:
        _remove_created_parents(created_parents)
        raise

    record = build_restore_record(
        entry_id=entry.entry_id,
        original_path=entry.original_path,
        trashed_path=str(payload),
        kind=entry.kind,
        restore_path=destination,
    )
    try:
        append_event(layout, record)
    except SafeDeleteError as append_error:
        raise _rollback_restore(
            destination=destination,
            payload=str(payload),
            created_parents=created_parents,
            append_error=append_error,
        )

    return {
        "entry_id": entry.entry_id,
        "state": "restored",
        "original_path": entry.original_path,
        "restore_path": destination,
        "trashed_path": str(payload),
        "kind": entry.kind,
    }

