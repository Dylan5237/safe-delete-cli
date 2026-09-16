"""Safe restore transaction for one active P2 ledger entry."""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .audit import LedgerEntry
from .errors import SafeDeleteError, error
from .ledger import append_event, build_restore_record
from .move import atomic_move
from .storage import Layout, ensure_safe_target, open_directory_without_symlinks


@dataclass
class _CreatedParent:
    """Identity and descriptor needed to safely clean one created parent."""

    path: Path
    name: str
    parent_fd: int | None
    identity: tuple[int, int] | None


def _lstat_at(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _identity(stat_result: os.stat_result) -> tuple[int, int]:
    return stat_result.st_dev, stat_result.st_ino


def _same_identity(
    left: os.stat_result | tuple[int, int],
    right: os.stat_result | tuple[int, int],
) -> bool:
    left_identity = _identity(left) if isinstance(left, os.stat_result) else left
    right_identity = _identity(right) if isinstance(right, os.stat_result) else right
    return left_identity == right_identity


def _parent_cleanup_error(
    parent: _CreatedParent,
    reason: str,
    *,
    actual: os.stat_result | None = None,
    exc: OSError | None = None,
) -> SafeDeleteError:
    details: dict[str, object] = {
        "path": str(parent.path),
        "preserved": True,
        "reason": reason,
    }
    if parent.identity is not None:
        details["expected_device"] = parent.identity[0]
        details["expected_inode"] = parent.identity[1]
    if actual is not None:
        details["actual_device"] = actual.st_dev
        details["actual_inode"] = actual.st_ino
    if exc is not None:
        details["errno"] = exc.errno
    return error(
        "storage_failure",
        "cannot verify restore parent identity; preserving directory",
        **details,
    )


def _close_created_parent_descriptors(created: list[_CreatedParent]) -> None:
    for parent in created:
        if parent.parent_fd is None:
            continue
        try:
            os.close(parent.parent_fd)
        except OSError:
            pass
        finally:
            parent.parent_fd = None


def _remove_created_parents(created: list[_CreatedParent]) -> SafeDeleteError | None:
    """Remove only unchanged, empty directories through creation-time fds.

    A pathname is never removed until its entry is verified against the inode
    captured immediately after this invocation's mkdir.  The parent descriptor
    is the one used for creation, so a replacement of an ancestor pathname
    cannot redirect cleanup into another directory.
    """

    first_error: SafeDeleteError | None = None
    for parent in reversed(created):
        try:
            if parent.parent_fd is None:
                cleanup_error = _parent_cleanup_error(parent, "parent descriptor unavailable")
            elif parent.identity is None:
                cleanup_error = _parent_cleanup_error(parent, "created directory identity unavailable")
            else:
                try:
                    current = _lstat_at(parent.parent_fd, parent.name)
                except OSError as exc:
                    cleanup_error = _parent_cleanup_error(
                        parent,
                        "cannot inspect directory before cleanup",
                        exc=exc,
                    )
                else:
                    if current is None:
                        cleanup_error = _parent_cleanup_error(
                            parent,
                            "directory disappeared before cleanup",
                        )
                    elif not stat.S_ISDIR(current.st_mode) or not _same_identity(
                        current,
                        parent.identity,
                    ):
                        cleanup_error = _parent_cleanup_error(
                            parent,
                            "directory was replaced before cleanup",
                            actual=current,
                        )
                    else:
                        try:
                            os.rmdir(parent.name, dir_fd=parent.parent_fd)
                        except OSError as exc:
                            if exc.errno in {errno.ENOTEMPTY, errno.EEXIST}:
                                # The directory is still the right inode but
                                # contains data added after creation. Preserve
                                # it without treating that as an identity race.
                                cleanup_error = None
                            else:
                                cleanup_error = _parent_cleanup_error(
                                    parent,
                                    "directory could not be removed after identity verification",
                                    exc=exc,
                                )
                        else:
                            cleanup_error = None
            if cleanup_error is not None and first_error is None:
                first_error = cleanup_error
        finally:
            if parent.parent_fd is not None:
                try:
                    os.close(parent.parent_fd)
                except OSError:
                    pass
                parent.parent_fd = None
    return first_error


def _with_cleanup_error(
    primary: SafeDeleteError,
    cleanup_error: SafeDeleteError,
) -> SafeDeleteError:
    details = {
        **primary.details,
        "cleanup_error": cleanup_error.code,
        "cleanup_path": cleanup_error.details.get("path"),
        "cleanup_preserved": True,
    }
    return SafeDeleteError(primary.code, primary.message, details)


def _cleanup_and_attach(
    primary: SafeDeleteError,
    created: list[_CreatedParent],
) -> SafeDeleteError:
    cleanup_error = _remove_created_parents(created)
    if cleanup_error is None:
        return primary
    return _with_cleanup_error(primary, cleanup_error)


def _remember_cleanup_error(exc: BaseException, cleanup_error: SafeDeleteError) -> None:
    # OSError is converted to the stable parent error code by _parent_error;
    # retain the cleanup finding across that conversion without changing the
    # original failure classification.
    try:
        setattr(exc, "_restore_cleanup_error", cleanup_error)
    except (AttributeError, TypeError):
        pass


def _open_restore_parent(
    parent: Path,
    *,
    create_parents: bool,
) -> tuple[int, list[_CreatedParent]]:
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
    created: list[_CreatedParent] = []
    try:
        for component in Path(os.path.normpath(os.fspath(parent))).parts[1:]:
            next_path = current / component
            created_here = False
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
                    created_here = True
                    created_parent = _CreatedParent(
                        path=next_path,
                        name=component,
                        parent_fd=os.dup(fd),
                        identity=None,
                    )
                    created.append(created_parent)
                    try:
                        created_stat = _lstat_at(fd, component)
                    except OSError:
                        raise
                    if created_stat is None:
                        raise FileNotFoundError(component)
                    if not stat.S_ISDIR(created_stat.st_mode):
                        raise OSError(
                            errno.ENOTDIR,
                            "restore parent is not a directory",
                            component,
                        )
                    created_parent.identity = _identity(created_stat)

                    # Reopening with O_NOFOLLOW is not enough: compare the
                    # descriptor to the inode captured after our mkdir before
                    # allowing it to become the traversal/move anchor.
                    next_fd = os.open(component, flags, dir_fd=fd)
                    try:
                        opened_stat = os.fstat(next_fd)
                    except OSError:
                        os.close(next_fd)
                        raise
                    if not stat.S_ISDIR(opened_stat.st_mode) or not _same_identity(
                        opened_stat,
                        created_parent.identity,
                    ):
                        os.close(next_fd)
                        raise error(
                            "storage_failure",
                            "restore parent was replaced after creation",
                            path=str(next_path),
                            expected_device=created_parent.identity[0],
                            expected_inode=created_parent.identity[1],
                            actual_device=opened_stat.st_dev,
                            actual_inode=opened_stat.st_ino,
                        )
                if not created_here:
                    # A FileExistsError means another actor created the
                    # component; it is not ours, so only open and traverse it
                    # under the existing no-follow checks.
                    next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
            current = next_path
        return fd, created
    except BaseException as exc:
        try:
            os.close(fd)
        except OSError:
            pass
        cleanup_error = _remove_created_parents(created)
        if cleanup_error is not None:
            _remember_cleanup_error(exc, cleanup_error)
        raise


def _parent_error(exc: BaseException, parent: Path, entry_id: str) -> SafeDeleteError:
    cleanup_error = getattr(exc, "_restore_cleanup_error", None)

    def finish(result: SafeDeleteError) -> SafeDeleteError:
        if isinstance(cleanup_error, SafeDeleteError):
            return _with_cleanup_error(result, cleanup_error)
        return result

    if isinstance(exc, SafeDeleteError):
        return finish(exc)
    if isinstance(exc, FileNotFoundError):
        return finish(error(
            "destination_parent_missing",
            f"restore destination parent is missing: {parent}",
            entry_id=entry_id,
            path=str(parent),
        ))
    if isinstance(exc, OSError) and exc.errno in {errno.ENOTDIR, errno.ELOOP}:
        return finish(error(
            "destination_parent_missing",
            f"restore destination parent is not a real directory: {parent}",
            entry_id=entry_id,
            path=str(parent),
        ))
    if isinstance(exc, OSError):
        return finish(error(
            "storage_failure",
            f"cannot open restore destination parent: {parent}",
            entry_id=entry_id,
            path=str(parent),
            errno=exc.errno,
        ))
    return finish(error(
        "storage_failure",
        f"cannot open restore destination parent: {parent}",
        entry_id=entry_id,
        path=str(parent),
    ))


def _rollback_restore(
    *,
    destination: str,
    payload: str,
    created_parents: list[_CreatedParent],
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
    cleanup_error = _remove_created_parents(created_parents)
    if cleanup_error is not None:
        return error(
            "rollback_failed",
            "restore ledger append failed; parent cleanup identity could not be verified",
            restore_path=destination,
            trashed_path=payload,
            append_error=append_error.code,
            cleanup_error=cleanup_error.code,
            cleanup_path=cleanup_error.details.get("path"),
            cleanup_preserved=True,
        )
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
    created_parents: list[_CreatedParent] = []
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
            primary = error(
                "storage_failure",
                f"cannot inspect restore destination: {destination}",
                entry_id=entry.entry_id,
                restore_path=destination,
                trashed_path=str(payload),
                errno=exc.errno,
            )
            raise _cleanup_and_attach(primary, created_parents) from exc
        if destination_stat is not None:
            primary = error(
                "destination_exists",
                f"restore destination already exists: {destination}",
                entry_id=entry.entry_id,
                path=destination,
            )
            raise _cleanup_and_attach(primary, created_parents)

        try:
            payload_parent_stat = os.fstat(payload_parent_fd)
            destination_parent_stat = os.fstat(destination_parent_fd)
        except OSError as exc:
            primary = error(
                "storage_failure",
                "cannot inspect restore directories",
                entry_id=entry.entry_id,
                restore_path=destination,
                trashed_path=str(payload),
                errno=exc.errno,
            )
            raise _cleanup_and_attach(primary, created_parents) from exc
        if payload_parent_stat.st_dev != destination_parent_stat.st_dev:
            primary = error(
                "cross_device",
                "restore destination and trash are on different filesystems",
                entry_id=entry.entry_id,
                restore_path=destination,
                trashed_path=str(payload),
            )
            raise _cleanup_and_attach(primary, created_parents)

        try:
            atomic_move(
                payload,
                destination_path,
                source_parent_fd=payload_parent_fd,
                destination_parent_fd=destination_parent_fd,
                expected_source_stat=payload_stat,
                expected_source_kind=entry.kind,
            )
        except SafeDeleteError as exc:
            raise _cleanup_and_attach(exc, created_parents)

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
        _close_created_parent_descriptors(created_parents)
