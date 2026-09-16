"""Safe restore transaction for one active P2 ledger entry."""

from __future__ import annotations

import errno
import os
from pathlib import Path

from .audit import LedgerEntry
from .errors import SafeDeleteError, error
from .ledger import append_event, build_restore_record
from .move import atomic_move
from .storage import Layout, ensure_safe_target, open_directory_without_symlinks


def _lstat_at(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _remove_created_parents(created: list[Path]) -> None:
    """Remove only empty directories through a verified parent descriptor."""

    for directory in reversed(created):
        parent_fd = None
        try:
            parent_fd = open_directory_without_symlinks(directory.parent)
            os.rmdir(directory.name, dir_fd=parent_fd)
        except (OSError, SafeDeleteError):
            # A user or concurrent process may have populated or replaced a
            # newly-created parent. No pathname cleanup may follow a link.
            continue
        finally:
            if parent_fd is not None:
                os.close(parent_fd)


def _open_restore_parent(parent: Path, *, create_parents: bool) -> tuple[int, list[Path]]:
    """Open/create a destination parent using mkdirat-style operations."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NOFOLLOW", 0):
        raise error(
            "storage_failure",
            "safe restore parent descriptors are unavailable on this platform",
            path=str(parent),
        )

    fd = open_directory_without_symlinks(Path("/"))
    current = Path("/")
    created: list[Path] = []
    try:
        for component in Path(os.path.normpath(os.fspath(parent))).parts[1:]:
            next_path = current / component
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create_parents:
                    raise
                try:
                    os.mkdir(component, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                else:
                    created.append(next_path)
                # Reopening with O_NOFOLLOW verifies the object that won the
                # mkdir race is a real directory before it is traversed.
                next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            current = next_path
        return fd, created
    except BaseException:
        os.close(fd)
        _remove_created_parents(created)
        raise


def _parent_error(exc: BaseException, parent: Path, entry_id: str) -> SafeDeleteError:
    if isinstance(exc, SafeDeleteError):
        return exc
    if isinstance(exc, FileNotFoundError):
        return error(
            "destination_parent_missing",
            f"restore destination parent is missing: {parent}",
            entry_id=entry_id,
            path=str(parent),
        )
    if isinstance(exc, OSError) and exc.errno in {errno.ENOTDIR, errno.ELOOP}:
        return error(
            "destination_parent_missing",
            f"restore destination parent is not a real directory: {parent}",
            entry_id=entry_id,
            path=str(parent),
        )
    if isinstance(exc, OSError):
        return error(
            "storage_failure",
            f"cannot open restore destination parent: {parent}",
            entry_id=entry_id,
            path=str(parent),
            errno=exc.errno,
        )
    return error(
        "storage_failure",
        f"cannot open restore destination parent: {parent}",
        entry_id=entry_id,
        path=str(parent),
    )


def _rollback_restore(
    *,
    destination: str,
    payload: str,
    created_parents: list[Path],
    append_error: SafeDeleteError,
    destination_parent_fd: int,
    payload_parent_fd: int,
    payload_stat: os.stat_result,
    kind: str,
) -> SafeDeleteError:
    try:
        atomic_move(
            destination,
            payload,
            source_parent_fd=destination_parent_fd,
            destination_parent_fd=payload_parent_fd,
            expected_source_stat=payload_stat,
            expected_source_kind=kind,
        )
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

    if restore_path is not None and not restore_path:
        raise error(
            "usage_error",
            "restore destination must not be empty",
            entry_id=entry.entry_id,
        )

    payload = layout.payload(entry.entry_id)
    payload_parent_fd = None
    destination_parent_fd = None
    created_parents: list[Path] = []
    try:
        try:
            payload_parent_fd = open_directory_without_symlinks(payload.parent)
            payload_stat = _lstat_at(payload_parent_fd, payload.name)
        except SafeDeleteError:
            raise
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot inspect trash payload: {payload}",
                entry_id=entry.entry_id,
                trashed_path=str(payload),
                errno=exc.errno,
            ) from exc
        if payload_stat is None:
            raise error(
                "payload_missing",
                "active ledger entry has no payload",
                entry_id=entry.entry_id,
                trashed_path=str(payload),
            )

        destination = entry.original_path if restore_path is None else restore_path
        destination_path = Path(destination)
        ensure_safe_target(layout, destination)
        parent = destination_path.parent
        try:
            destination_parent_fd, created_parents = _open_restore_parent(
                parent,
                create_parents=create_parents,
            )
        except BaseException as exc:
            raise _parent_error(exc, parent, entry.entry_id) from exc

        try:
            destination_stat = _lstat_at(destination_parent_fd, destination_path.name)
        except OSError as exc:
            _remove_created_parents(created_parents)
            raise error(
                "storage_failure",
                f"cannot inspect restore destination: {destination}",
                entry_id=entry.entry_id,
                restore_path=destination,
                trashed_path=str(payload),
                errno=exc.errno,
            ) from exc
        if destination_stat is not None:
            _remove_created_parents(created_parents)
            raise error(
                "destination_exists",
                f"restore destination already exists: {destination}",
                entry_id=entry.entry_id,
                path=destination,
            )

        try:
            payload_parent_stat = os.fstat(payload_parent_fd)
            destination_parent_stat = os.fstat(destination_parent_fd)
        except OSError as exc:
            _remove_created_parents(created_parents)
            raise error(
                "storage_failure",
                "cannot inspect restore directories",
                entry_id=entry.entry_id,
                restore_path=destination,
                trashed_path=str(payload),
                errno=exc.errno,
            ) from exc
        if payload_parent_stat.st_dev != destination_parent_stat.st_dev:
            _remove_created_parents(created_parents)
            raise error(
                "cross_device",
                "restore destination and trash are on different filesystems",
                entry_id=entry.entry_id,
                restore_path=destination,
                trashed_path=str(payload),
            )

        try:
            atomic_move(
                payload,
                destination_path,
                source_parent_fd=payload_parent_fd,
                destination_parent_fd=destination_parent_fd,
                expected_source_stat=payload_stat,
                expected_source_kind=entry.kind,
            )
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
                destination_parent_fd=destination_parent_fd,
                payload_parent_fd=payload_parent_fd,
                payload_stat=payload_stat,
                kind=entry.kind,
            )

        return {
            "entry_id": entry.entry_id,
            "state": "restored",
            "original_path": entry.original_path,
            "restore_path": destination,
            "trashed_path": str(payload),
            "kind": entry.kind,
        }
    finally:
        if destination_parent_fd is not None:
            os.close(destination_parent_fd)
        if payload_parent_fd is not None:
            os.close(payload_parent_fd)
