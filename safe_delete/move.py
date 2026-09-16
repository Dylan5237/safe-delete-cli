"""Atomic, same-filesystem moves used by trash and restore transactions."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from pathlib import Path

from .errors import SafeDeleteError, error
from .storage import is_exdev


_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_NO_REPLACE_UNAVAILABLE = object()


def _renameat2_noreplace(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> bool | object:
    """Use Linux's atomic no-replace rename when libc exposes it.

    ``False`` means the host has no usable primitive and the caller may use the
    documented residual-check fallback. Any real filesystem error is raised.
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


def _open_directory_without_symlinks(path: Path) -> int:
    """Open every component with O_NOFOLLOW and retain the final directory fd."""

    normalized = os.path.normpath(os.fspath(path))
    if not os.path.isabs(normalized):
        raise error("storage_failure", f"move path must be absolute: {path}", path=str(path))
    fd = os.open(os.sep, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        for component in Path(normalized).parts[1:]:
            next_fd = os.open(
                component,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=fd,
            )
            os.close(fd)
            fd = next_fd
        return fd
    except OSError:
        os.close(fd)
        raise


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
) -> None:
    """Move one filesystem object with no copy/delete fallback.

    The caller owns the ledger lock and path policy. The destination is checked
    with ``lstat`` so a dangling final symlink is still occupied. On Linux the
    final rename uses ``renameat2(RENAME_NOREPLACE)``. Other hosts use the same
    residual check followed by ``rename``; they still never intentionally
    overwrite a destination.
    """

    source_path = Path(source)
    destination_path = Path(destination)
    source_parent_fd = destination_parent_fd = None
    try:
        source_parent_fd = _open_directory_without_symlinks(source_path.parent)
        destination_parent_fd = _open_directory_without_symlinks(destination_path.parent)
        source_stat = _lstat_at(source_parent_fd, source_path.name)
        if source_stat is None:
            raise error(
                "source_not_found",
                f"source does not exist: {source_path}",
                path=str(source_path),
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
            # There is no portable no-replace directory move primitive.  For
            # regular files and symlinks, link+unlink gives an atomic,
            # no-overwrite destination claim.  Refuse directories rather than
            # falling back to overwrite-capable os.rename.
            if stat.S_ISDIR(source_stat.st_mode):
                raise error(
                    "storage_failure",
                    "no safe no-replace move primitive is available for directories",
                    source=str(source_path),
                    destination=str(destination_path),
                )
            try:
                os.link(
                    source_path.name,
                    destination_path.name,
                    src_dir_fd=source_parent_fd,
                    dst_dir_fd=destination_parent_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    raise error(
                        destination_error_code,
                        f"move destination already exists: {destination_path}",
                        path=str(destination_path),
                    ) from exc
                raise
            try:
                os.unlink(source_path.name, dir_fd=source_parent_fd)
            except OSError:
                try:
                    os.unlink(destination_path.name, dir_fd=destination_parent_fd)
                except OSError:
                    pass
                raise
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
        if source_parent_fd is not None:
            os.close(source_parent_fd)
        if destination_parent_fd is not None:
            os.close(destination_parent_fd)
