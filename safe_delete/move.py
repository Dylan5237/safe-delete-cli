"""Atomic, same-filesystem moves used by trash and restore transactions."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from pathlib import Path
from typing import Any

from .errors import SafeDeleteError, error
from .storage import is_exdev, open_directory_without_symlinks


_RENAME_NOREPLACE = 1
_NO_REPLACE_UNAVAILABLE = object()

# Linux 9p, including WSL DrvFs. TMPFS_MAGIC is 0x01021994; do not treat it as 9p.
V9FS_MAGIC = 0x01021997
_V9FS_FALLBACK_ERRNOS = frozenset(
    {errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP}
)
_UNSUPPORTED_FLAG_ERRNOS = frozenset(
    {errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP}
)

# Freeze §3.4. Doctor, the agent skill, and p7-agent-usage quote this sentence.
V9FS_NOREPLACE_RESIDUAL = (
    "DrvFs/9p root: same-filesystem rename uses renameat (flags 0) after lstat "
    "because renameat2(RENAME_NOREPLACE) is not supported. Atomic rename, not a "
    "copy. Check/rename race remains. Not an Exception #12 change."
)


class _Renameat2Missing(Exception):
    """``renameat2`` is absent. This is not an errno from a completed call."""

# Kept as a module-level alias for callers/tests that exercise the move
# primitive directly; the implementation lives with the other storage helpers.
_open_directory_without_symlinks = open_directory_without_symlinks


def _filesystem_type(directory_fd: int) -> int | None:
    """Return ``fstatfs`` ``f_type`` for an already-open directory fd.

    Linux only. The glibc ``struct statfs`` used here matches the x86_64
    layout probed for this product (``f_type`` is ``__fsword_t``). Other
    platforms return ``None`` and stay on the fail-closed no-replace path.
    """

    if not sys.platform.startswith("linux"):
        return None
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        fstatfs = libc.fstatfs
    except (AttributeError, OSError):
        return None

    class StatFS(ctypes.Structure):
        _fields_ = [
            ("f_type", ctypes.c_long),
            ("f_bsize", ctypes.c_long),
            ("f_blocks", ctypes.c_ulong),
            ("f_bfree", ctypes.c_ulong),
            ("f_bavail", ctypes.c_ulong),
            ("f_files", ctypes.c_ulong),
            ("f_ffree", ctypes.c_ulong),
            ("f_fsid", ctypes.c_ulong * 2),
            ("f_namelen", ctypes.c_long),
            ("f_frsize", ctypes.c_long),
            ("f_flags", ctypes.c_long),
            ("f_spare", ctypes.c_long * 4),
        ]

    fstatfs.argtypes = [ctypes.c_int, ctypes.POINTER(StatFS)]
    fstatfs.restype = ctypes.c_int
    buffer = StatFS()
    ctypes.set_errno(0)
    if fstatfs(directory_fd, ctypes.byref(buffer)) != 0:
        return None
    return int(buffer.f_type) & 0xFFFFFFFF


def _filesystem_type_of_path(path: Path) -> int | None:
    """Read-only ``fstatfs`` of a real directory. Missing paths are not created."""

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if not directory:
        return None
    try:
        fd = os.open(path, os.O_RDONLY | directory | nofollow)
    except OSError:
        return None
    try:
        return _filesystem_type(fd)
    finally:
        os.close(fd)


def noreplace_storage_fields(root: str | None) -> dict[str, Any]:
    """Doctor storage fields for the resolved root. Never writes."""

    magic = _filesystem_type_of_path(Path(root)) if root else None
    if magic == V9FS_MAGIC:
        return {
            "filesystem": "v9fs",
            "noreplace": "emulated",
            "noreplace_residual": V9FS_NOREPLACE_RESIDUAL,
        }
    return {"noreplace": "native", "noreplace_residual": None}


def _invoke_renameat2(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
    flags: int,
) -> None:
    """Call ``renameat2`` with ``flags``. Missing libc entry is not an errno."""

    if not sys.platform.startswith("linux"):
        raise _Renameat2Missing()
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (AttributeError, OSError) as exc:
        raise _Renameat2Missing() from exc

    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = renameat2(
        source_parent_fd,
        os.fsencode(source_name),
        destination_parent_fd,
        os.fsencode(destination_name),
        flags,
    )
    if result == 0:
        return
    saved_errno = ctypes.get_errno()
    raise OSError(saved_errno, os.strerror(saved_errno), source_name)


def _v9fs_flags0_rename(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> None:
    """Flags-0 ``renameat`` after a no-follow ``lstat``. No copy and no link."""

    if _lstat_at(destination_parent_fd, destination_name) is not None:
        raise FileExistsError(
            errno.EEXIST,
            os.strerror(errno.EEXIST),
            destination_name,
        )
    os.rename(
        source_name,
        destination_name,
        src_dir_fd=source_parent_fd,
        dst_dir_fd=destination_parent_fd,
    )


def _renameat2_noreplace(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> bool | object:
    """Use Linux's atomic no-replace rename when libc exposes it.

    The first call is always ``renameat2(..., RENAME_NOREPLACE)``. A flags-0
    ``renameat`` runs only when that call returns the unsupported-flag errno
    class and the destination parent ``f_type`` is ``V9FS_MAGIC``. Callers
    already hold the exclusive ledger lock; this helper does not take one.
    Every other filesystem keeps today's fail-closed result.
    """

    try:
        _invoke_renameat2(
            source_parent_fd,
            source_name,
            destination_parent_fd,
            destination_name,
            _RENAME_NOREPLACE,
        )
    except _Renameat2Missing:
        return _NO_REPLACE_UNAVAILABLE
    except OSError as exc:
        if (
            exc.errno in _V9FS_FALLBACK_ERRNOS
            and _filesystem_type(destination_parent_fd) == V9FS_MAGIC
        ):
            _v9fs_flags0_rename(
                source_parent_fd,
                source_name,
                destination_parent_fd,
                destination_name,
            )
            return True
        if exc.errno in _UNSUPPORTED_FLAG_ERRNOS:
            return _NO_REPLACE_UNAVAILABLE
        raise
    return True


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
    caller must fail closed.  The only replace-capable fallback is the 9p
    flags-0 ``renameat`` inside ``_renameat2_noreplace``, and only after a
    no-follow ``lstat`` shows the destination name is absent.
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
    final rename uses ``renameat2(RENAME_NOREPLACE)``. If that call is rejected
    with ``EINVAL``, ``ENOSYS``, or ``EOPNOTSUPP``/``ENOTSUP`` and the
    destination parent's ``f_type`` is ``V9FS_MAGIC``, the destination is
    ``lstat``ed again and, when absent, moved with flags-0 ``renameat``.
    Every other filesystem fails closed. There is no copy and no
    ``linkat``/``unlink`` emulation.

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
