"""Frozen safe-delete storage layout, path normalization, and locking."""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .errors import SafeDeleteError, error


@dataclass(frozen=True)
class Layout:
    root: Path
    ledger: Path
    lock: Path
    trash: Path
    objects: Path

    def payload(self, entry_id: str) -> Path:
        return self.objects / entry_id / "payload"


def _text(value: os.PathLike[str] | str | bytes, *, field_name: str = "path") -> str:
    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise error("usage_error", f"{field_name} must be a path") from exc
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise error(
                "unsupported_path_encoding",
                f"{field_name} is not valid UTF-8",
            ) from exc
    if not isinstance(raw, str):
        raise error("usage_error", f"{field_name} must be a path")
    try:
        raw.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise error(
            "unsupported_path_encoding",
            f"{field_name} is not valid UTF-8",
        ) from exc
    return raw


def resolve_root(explicit: str | None = None) -> Path:
    """Resolve the explicit root or the frozen environment default."""

    if explicit is not None:
        raw = _text(explicit, field_name="root")
    else:
        raw = os.environ.get("SAFE_DELETE_ROOT")
        if raw is None:
            data_home = os.environ.get("XDG_DATA_HOME")
            if data_home is None:
                data_home = os.path.join(os.path.expanduser("~"), ".local", "share")
            raw = os.path.join(data_home, "safe-delete")
        else:
            raw = _text(raw, field_name="SAFE_DELETE_ROOT")
    if not raw:
        raise error("usage_error", "root must not be empty")
    # Resolving the root itself makes aliases to an existing storage root
    # consistent while still keeping final source symlinks unresolved.
    return Path(os.path.normpath(os.path.realpath(os.path.abspath(raw))))


def layout_for(explicit_root: str | None = None) -> Layout:
    root = resolve_root(explicit_root)
    return Layout(
        root=root,
        ledger=root / "ledger.jsonl",
        lock=root / "locks" / "ledger.lock",
        trash=root / "trash",
        objects=root / "trash" / "objects",
    )


def open_directory_without_symlinks(path: Path) -> int:
    """Open an absolute directory through stable, no-follow descriptors."""

    normalized = os.path.normpath(os.fspath(path))
    if not os.path.isabs(normalized):
        raise error(
            "storage_failure",
            f"storage directory must be absolute: {path}",
            path=str(path),
        )
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if not nofollow or not directory:
        raise error(
            "storage_failure",
            "safe directory descriptors are unavailable on this platform",
            path=str(path),
        )

    fd = os.open(os.sep, os.O_RDONLY | directory)
    try:
        for component in Path(normalized).parts[1:]:
            next_fd = os.open(
                component,
                os.O_RDONLY | directory | nofollow,
                dir_fd=fd,
            )
            os.close(fd)
            fd = next_fd
        return fd
    except OSError:
        os.close(fd)
        raise


def _lstat(path: Path) -> os.stat_result:
    try:
        return os.lstat(path)
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot inspect storage path: {path}",
            path=str(path),
            errno=exc.errno,
        ) from exc


def _ensure_directory(path: Path) -> bool:
    """Ensure a real directory exists; return whether it was created."""

    try:
        st = os.lstat(path)
    except FileNotFoundError:
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            st = _lstat(path)
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot create storage directory: {path}",
                path=str(path),
                errno=exc.errno,
            ) from exc
        else:
            return True
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot inspect storage directory: {path}",
            path=str(path),
            errno=exc.errno,
        ) from exc

    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise error(
            "storage_failure",
            f"storage path is not a directory: {path}",
            path=str(path),
        )
    return False


def _require_directory(path: Path) -> None:
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise error(
            "storage_failure",
            f"storage path is unavailable: {path}",
            path=str(path),
            errno=exc.errno,
        ) from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise error(
            "storage_failure",
            f"storage path is not a directory: {path}",
            path=str(path),
        )


def _ensure_regular_file(path: Path) -> bool:
    """Ensure a non-symlink regular file exists; return whether it was created."""

    parent_fd = None
    fd = None
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        parent_fd = open_directory_without_symlinks(path.parent)
        try:
            st = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            try:
                fd = os.open(
                    path.name,
                    flags | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                try:
                    st = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
                except OSError as exc:
                    raise error(
                        "storage_failure",
                        f"cannot inspect storage file after a race: {path}",
                        path=str(path),
                        errno=exc.errno,
                    ) from exc
            else:
                try:
                    os.fsync(fd)
                except OSError as exc:
                    raise error(
                        "storage_failure",
                        f"cannot flush storage file: {path}",
                        path=str(path),
                        errno=exc.errno,
                    ) from exc
                return True
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot inspect storage file: {path}",
                path=str(path),
                errno=exc.errno,
            ) from exc
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot inspect storage file: {path}",
            path=str(path),
            errno=exc.errno,
        ) from exc
    finally:
        if fd is not None:
            os.close(fd)
        if parent_fd is not None:
            os.close(parent_fd)

    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise error(
            "storage_failure",
            f"storage path is not a regular file: {path}",
            path=str(path),
        )
    return False


def _sync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot open storage directory for durability: {path}",
            path=str(path),
            errno=exc.errno,
        ) from exc
    try:
        os.fsync(fd)
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot flush storage directory: {path}",
            path=str(path),
            errno=exc.errno,
        ) from exc
    finally:
        os.close(fd)


def initialize_layout(explicit_root: str | None = None) -> Layout:
    """Create the frozen root and its empty ledger without deleting anything."""

    layout = layout_for(explicit_root)
    created_dirs = []
    try:
        root_exists = os.path.lexists(layout.root)
        if not root_exists:
            os.makedirs(layout.root, mode=0o700, exist_ok=True)
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot create storage root: {layout.root}",
            path=str(layout.root),
            errno=exc.errno,
        ) from exc
    if not root_exists:
        created_dirs.append(layout.root)
    else:
        _ensure_directory(layout.root)
    for path in (layout.root / "locks", layout.trash, layout.objects):
        if _ensure_directory(path):
            created_dirs.append(path)
    ledger_created = _ensure_regular_file(layout.ledger)
    lock_created = _ensure_regular_file(layout.lock)
    # Directory fsyncs make newly-created layout names durable before init says
    # it succeeded. Existing storage is never removed or rewritten.
    if ledger_created or lock_created:
        _sync_directory(layout.root / "locks")
        _sync_directory(layout.root)
    for directory in reversed(created_dirs):
        _sync_directory(directory.parent)
    return layout


def require_layout(explicit_root: str | None = None) -> Layout:
    """Load an initialized layout without creating or modifying it."""

    layout = layout_for(explicit_root)
    for path in (layout.root, layout.root / "locks", layout.trash, layout.objects):
        _require_directory(path)
    for path in (layout.ledger, layout.lock):
        try:
            st = os.lstat(path)
        except OSError as exc:
            raise error(
                "storage_failure",
                f"storage path is unavailable: {path}",
                path=str(path),
                errno=exc.errno,
            ) from exc
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise error(
                "storage_failure",
                f"storage path is not a regular file: {path}",
                path=str(path),
            )
    return layout


def normalized_path(value: str | os.PathLike[str] | bytes, *, field_name: str = "path") -> str:
    """Return an absolute path with parent symlinks resolved, not its final name."""

    raw = _text(value, field_name=field_name)
    if not raw:
        raise error("usage_error", f"{field_name} must not be empty")
    absolute = os.path.normpath(os.path.abspath(raw))
    parent, basename = os.path.split(absolute)
    resolved_parent = os.path.realpath(parent)
    return os.path.normpath(os.path.join(resolved_parent, basename))


def is_same_or_below(path: str | Path, base: str | Path) -> bool:
    try:
        return os.path.commonpath((os.fspath(path), os.fspath(base))) == os.fspath(base)
    except ValueError:
        return False


def is_ancestor_or_descendant(path: str | Path, other: str | Path) -> bool:
    first = os.fspath(path)
    second = os.fspath(other)
    return is_same_or_below(first, second) or is_same_or_below(second, first)


def ensure_safe_target(layout: Layout, path: str) -> None:
    """Reject storage paths and relationships that could capture the trash."""

    candidate = os.fspath(path)
    reserved_exact = {
        os.fspath(layout.root),
        os.fspath(layout.ledger),
        os.fspath(layout.lock),
        os.fspath(layout.trash),
    }
    if candidate in reserved_exact:
        raise error(
            "path_forbidden",
            f"reserved safe-delete path: {candidate}",
            path=candidate,
        )
    if is_same_or_below(candidate, layout.trash):
        raise error(
            "path_forbidden",
            f"path is inside the trash: {candidate}",
            path=candidate,
        )
    if is_same_or_below(candidate, layout.root / "locks"):
        raise error(
            "path_forbidden",
            f"path is inside the locks directory: {candidate}",
            path=candidate,
        )
    if is_ancestor_or_descendant(candidate, layout.trash):
        raise error(
            "path_forbidden",
            f"path has an unsafe relationship with the trash: {candidate}",
            path=candidate,
        )


def has_entry(path: str | Path) -> bool:
    """Use lstat semantics, including for dangling final symlinks."""

    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot inspect path: {path}",
            path=os.fspath(path),
            errno=exc.errno,
        ) from exc
    return True


def kind_for(path: str | Path, st: os.stat_result | None = None) -> str:
    if st is None:
        try:
            st = os.lstat(path)
        except FileNotFoundError as exc:
            raise error(
                "source_not_found",
                f"source does not exist: {path}",
                path=os.fspath(path),
            ) from exc
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot inspect source: {path}",
                path=os.fspath(path),
                errno=exc.errno,
            ) from exc
    if stat.S_ISREG(st.st_mode):
        return "file"
    if stat.S_ISDIR(st.st_mode):
        return "directory"
    if stat.S_ISLNK(st.st_mode):
        return "symlink"
    raise error(
        "unsupported_kind",
        f"unsupported source kind: {path}",
        path=os.fspath(path),
    )


@contextlib.contextmanager
def ledger_lock(layout: Layout, *, exclusive: bool) -> Iterator[int]:
    """Hold the OS flock for the whole audit/move/append transaction."""

    parent_fd = None
    fd = None
    locked = False
    try:
        try:
            parent_fd = open_directory_without_symlinks(layout.lock.parent)
            fd = os.open(
                layout.lock.name,
                os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
            descriptor_stat = os.fstat(fd)
            if not stat.S_ISREG(descriptor_stat.st_mode):
                raise error(
                    "ledger_failure",
                    f"ledger lock is not a regular file: {layout.lock}",
                    path=str(layout.lock),
                )
            path_stat = os.stat(layout.lock.name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(path_stat.st_mode)
                or path_stat.st_dev != descriptor_stat.st_dev
                or path_stat.st_ino != descriptor_stat.st_ino
            ):
                raise error(
                    "ledger_failure",
                    f"ledger lock changed while opening: {layout.lock}",
                    path=str(layout.lock),
                )
        except SafeDeleteError:
            raise
        except OSError as exc:
            raise error(
                "ledger_failure",
                f"cannot open ledger lock: {layout.lock}",
                path=str(layout.lock),
                errno=exc.errno,
            ) from exc
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(fd, operation)
            locked = True
        except OSError as exc:
            raise error(
                "ledger_failure",
                f"cannot lock ledger: {layout.lock}",
                path=str(layout.lock),
                errno=exc.errno,
            ) from exc
        try:
            path_stat = os.stat(layout.lock.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise error(
                "ledger_failure",
                f"cannot verify ledger lock after locking: {layout.lock}",
                path=str(layout.lock),
                errno=exc.errno,
            ) from exc
        if (
            not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_dev != descriptor_stat.st_dev
            or path_stat.st_ino != descriptor_stat.st_ino
        ):
            raise error(
                "ledger_failure",
                f"ledger lock was replaced while locking: {layout.lock}",
                path=str(layout.lock),
            )
        yield fd
    finally:
        try:
            if locked and fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
            elif fd is not None:
                os.close(fd)
        finally:
            if parent_fd is not None:
                os.close(parent_fd)


def same_filesystem(first: str | Path, second: str | Path) -> bool:
    try:
        return os.lstat(first).st_dev == os.lstat(second).st_dev
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot compare filesystems: {first} and {second}",
            first=os.fspath(first),
            second=os.fspath(second),
            errno=exc.errno,
        ) from exc


def is_exdev(exc: OSError) -> bool:
    return exc.errno == errno.EXDEV
