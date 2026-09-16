"""Atomic, same-filesystem moves used by trash and restore transactions."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from pathlib import Path

from .errors import SafeDeleteError, error
from .storage import is_exdev


_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_NO_REPLACE_UNAVAILABLE = object()


def _renameat2_noreplace(source: Path, destination: Path) -> bool | object:
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
        _AT_FDCWD,
        os.fsencode(source),
        _AT_FDCWD,
        os.fsencode(destination),
        _RENAME_NOREPLACE,
    )
    if result == 0:
        return True
    saved_errno = ctypes.get_errno()
    if saved_errno in {errno.ENOSYS, errno.EOPNOTSUPP, errno.ENOTSUP}:
        return _NO_REPLACE_UNAVAILABLE
    raise OSError(saved_errno, os.strerror(saved_errno), os.fspath(source))


def _lstat_destination(destination: Path) -> bool:
    try:
        os.lstat(destination)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot inspect move destination: {destination}",
            path=str(destination),
            errno=exc.errno,
        ) from exc
    return True


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
    try:
        source_stat = os.lstat(source_path)
    except FileNotFoundError as exc:
        raise error(
            "source_not_found",
            f"source does not exist: {source_path}",
            path=str(source_path),
        ) from exc
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot inspect move source: {source_path}",
            path=str(source_path),
            errno=exc.errno,
        ) from exc

    if _lstat_destination(destination_path):
        raise error(
            destination_error_code,
            f"move destination already exists: {destination_path}",
            path=str(destination_path),
        )

    parent = destination_path.parent
    try:
        parent_stat = os.stat(parent)
    except FileNotFoundError as exc:
        raise error(
            "storage_failure",
            f"move destination parent is missing: {parent}",
            path=str(parent),
        ) from exc
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot inspect move destination parent: {parent}",
            path=str(parent),
            errno=exc.errno,
        ) from exc

    if source_stat.st_dev != parent_stat.st_dev:
        raise error(
            "cross_device",
            "source and destination are on different filesystems",
            source=str(source_path),
            destination=str(destination_path),
        )

    try:
        result = _renameat2_noreplace(source_path, destination_path)
        if result is _NO_REPLACE_UNAVAILABLE:
            # The destination check is deliberately immediately adjacent to
            # rename. On hosts without renameat2 this is the documented small
            # residual race; no overwrite flag or copy fallback is used.
            if _lstat_destination(destination_path):
                raise error(
                    destination_error_code,
                    f"move destination already exists: {destination_path}",
                    path=str(destination_path),
                )
            os.rename(source_path, destination_path)
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
            try:
                os.lstat(source_path)
            except FileNotFoundError:
                raise error(
                    "source_not_found",
                    f"source does not exist: {source_path}",
                    path=str(source_path),
                ) from exc
        raise error(
            "storage_failure",
            f"atomic move failed: {source_path} -> {destination_path}",
            source=str(source_path),
            destination=str(destination_path),
            errno=exc.errno,
        ) from exc
