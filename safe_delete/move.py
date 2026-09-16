"""Atomic, same-filesystem moves used by trash and restore transactions."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from pathlib import Path

from .errors import SafeDeleteError, error
from .storage import is_exdev, open_directory_without_symlinks


_RENAME_NOREPLACE = 1
_NO_REPLACE_UNAVAILABLE = object()

# Kept as a module-level alias for callers/tests that exercise the move
# primitive directly; the implementation lives with the other storage helpers.
_open_directory_without_symlinks = open_directory_without_symlinks


def _renameat2_noreplace(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> bool | object:
    """Use Linux's atomic no-replace rename when libc exposes it.

    The unavailable sentinel means the caller must fail closed. Any real
    filesystem error is raised.
    """

    if not sys.platform.startswith("linux"):
        return _NO_REPLACE_UNAVAILABLE
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError):
        return _NO_REPLACE_UNAVAILABLE

    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        source_parent_fd,
        os.fsencode(source_name),
        destination_parent_fd,
        os.fsencode(destination_name),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return True
    saved_errno = ctypes.get_errno()
    if saved_errno in {errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP}:
        return _NO_REPLACE_UNAVAILABLE
    raise OSError(saved_errno, os.strerror(saved_errno), source_name)


def rename_without_replace(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> None:
    """Atomically move one name with no-replace semantics or fail closed.

    ``OSError`` from the rename propagates with its original ``errno`` (for
    example ``EEXIST`` when the destination name is occupied or ``EXDEV``
    across filesystems).  When the platform lacks the no-replace primitive the
    caller must fail closed, so this raises ``storage_failure`` instead of
    falling back to a replace-prone rename.
    """

    result = _renameat2_noreplace(
        source_parent_fd,
        source_name,
        destination_parent_fd,
        destination_name,
    )
    if result is _NO_REPLACE_UNAVAILABLE:
        raise error(
            "storage_failure",
            "safe no-replace rename primitive is unavailable",
            source=source_name,
            destination=destination_name,
        )


def _lstat_at(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise exc


def atomic_move(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    *,
    destination_error_code: str = "destination_exists",
    expected_source_stat: os.stat_result | None = None,
    expected_source_kind: str | None = None,
    source_parent_fd: int | None = None,
    destination_parent_fd: int | None = None,
) -> None:
    """Move one filesystem object with no copy/delete fallback.

    The caller owns the ledger lock and path policy. The destination is checked
    with ``lstat`` so a dangling final symlink is still occupied. On Linux the
    final rename uses ``renameat2(RENAME_NOREPLACE)``. If that primitive is not
    available, the operation fails closed because a portable fallback cannot
    provide the same no-replace race guarantees for every supported kind.

    When an expected source snapshot is supplied, both the pre-move source and
    the post-move destination are checked for the same inode and kind. This
    makes a replacement between inspection and rename a failed operation, not
    a ledger record for an object that was never inspected.
    """

    source_path = Path(source)
    destination_path = Path(destination)
    owns_source_parent_fd = source_parent_fd is None
    owns_destination_parent_fd = destination_parent_fd is None
    try:
        if source_parent_fd is None:
            source_parent_fd = _open_directory_without_symlinks(source_path.parent)
        if destination_parent_fd is None:
            destination_parent_fd = _open_directory_without_symlinks(destination_path.parent)
        source_stat = _lstat_at(source_parent_fd, source_path.name)
        if source_stat is None:
            raise error(
                "source_not_found",
                f"source does not exist: {source_path}",
                path=str(source_path),
            )
        if expected_source_stat is not None and (
            source_stat.st_dev != expected_source_stat.st_dev
            or source_stat.st_ino != expected_source_stat.st_ino
        ):
            raise error(
                "storage_failure",
                "source changed between inspection and atomic move",
                source=str(source_path),
                expected_source_device=expected_source_stat.st_dev,
                expected_source_inode=expected_source_stat.st_ino,
                actual_source_device=source_stat.st_dev,
                actual_source_inode=source_stat.st_ino,
            )
        if expected_source_kind is not None:
            actual_kind = _kind_for_stat(source_stat)
            if actual_kind != expected_source_kind:
                raise error(
                    "storage_failure",
                    "source kind changed between inspection and atomic move",
                    source=str(source_path),
                    expected_kind=expected_source_kind,
                    actual_kind=actual_kind,
                )
        destination_stat = _lstat_at(destination_parent_fd, destination_path.name)
        if destination_stat is not None:
            raise error(
                destination_error_code,
                f"move destination already exists: {destination_path}",
                path=str(destination_path),
            )

        parent_stat = os.fstat(destination_parent_fd)
        if source_stat.st_dev != parent_stat.st_dev:
            raise error(
                "cross_device",
                "source and destination are on different filesystems",
                source=str(source_path),
                destination=str(destination_path),
            )

        result = _renameat2_noreplace(
            source_parent_fd,
            source_path.name,
            destination_parent_fd,
            destination_path.name,
        )
        if result is _NO_REPLACE_UNAVAILABLE:
            raise error(
                "storage_failure",
                "safe no-replace atomic move primitive is unavailable",
                source=str(source_path),
                destination=str(destination_path),
            )

        if expected_source_stat is not None or expected_source_kind is not None:
            moved_stat = _lstat_at(destination_parent_fd, destination_path.name)
            if moved_stat is None:
                raise error(
                    "storage_failure",
                    "atomic move destination disappeared during source verification",
                    source=str(source_path),
                    destination=str(destination_path),
                )
            if expected_source_stat is not None and (
                moved_stat.st_dev != expected_source_stat.st_dev
                or moved_stat.st_ino != expected_source_stat.st_ino
            ):
                raise error(
                    "storage_failure",
                    "atomic move moved a source replacement",
                    source=str(source_path),
                    destination=str(destination_path),
                    expected_source_device=expected_source_stat.st_dev,
                    expected_source_inode=expected_source_stat.st_ino,
                    actual_destination_device=moved_stat.st_dev,
                    actual_destination_inode=moved_stat.st_ino,
                )
            if expected_source_kind is not None:
                actual_kind = _kind_for_stat(moved_stat)
                if actual_kind != expected_source_kind:
                    raise error(
                        "storage_failure",
                        "atomic move moved a source replacement kind",
                        source=str(source_path),
                        destination=str(destination_path),
                        expected_kind=expected_source_kind,
                        actual_kind=actual_kind,
                    )
    except SafeDeleteError:
        raise
    except OSError as exc:
        if is_exdev(exc):
            raise error(
                "cross_device",
                "atomic move crossed filesystem devices",
                source=str(source_path),
                destination=str(destination_path),
            ) from exc
        if exc.errno == errno.EEXIST:
            raise error(
                destination_error_code,
                f"move destination already exists: {destination_path}",
                path=str(destination_path),
            ) from exc
        if exc.errno == errno.ENOENT:
            raise error(
                "source_not_found",
                f"source or move parent does not exist: {source_path}",
                path=str(source_path),
            ) from exc
        raise error(
            "storage_failure",
            f"atomic move failed: {source_path} -> {destination_path}",
            source=str(source_path),
            destination=str(destination_path),
            errno=exc.errno,
        ) from exc
    finally:
        if owns_source_parent_fd and source_parent_fd is not None:
            os.close(source_parent_fd)
        if owns_destination_parent_fd and destination_parent_fd is not None:
            os.close(destination_parent_fd)


def _kind_for_stat(source_stat: os.stat_result) -> str | None:
    if stat.S_ISREG(source_stat.st_mode):
        return "file"
    if stat.S_ISDIR(source_stat.st_mode):
        return "directory"
    if stat.S_ISLNK(source_stat.st_mode):
        return "symlink"
    return None
