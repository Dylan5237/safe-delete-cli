"""P2 minimum ledger records and durable append helpers."""

from __future__ import annotations

import datetime as _datetime
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from .errors import SafeDeleteError, error
from .storage import Layout, kind_for, open_directory_without_symlinks


@dataclass(frozen=True)
class SourceInfo:
    original_path: str
    kind: str
    stat: os.stat_result


def utc_timestamp() -> str:
    return (
        _datetime.datetime.now(_datetime.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def new_entry_id() -> str:
    return str(uuid.uuid4())


def inspect_source(layout: Layout, original_path: str) -> SourceInfo:
    try:
        source_stat = os.lstat(original_path)
    except FileNotFoundError as exc:
        raise error(
            "source_not_found",
            f"source does not exist: {original_path}",
            path=original_path,
        ) from exc
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot inspect source: {original_path}",
            path=original_path,
            errno=exc.errno,
        ) from exc
    return SourceInfo(
        original_path=original_path,
        kind=kind_for(original_path, source_stat),
        stat=source_stat,
    )


def create_entry_directory(layout: Layout, *, attempts: int = 32) -> tuple[str, Path]:
    """Create an exclusive object directory and return its fresh UUID."""

    for _ in range(attempts):
        entry_id = new_entry_id()
        object_directory = layout.objects / entry_id
        try:
            os.mkdir(object_directory, 0o700)
        except FileExistsError:
            continue
        except OSError as exc:
            raise error(
                "storage_failure",
                f"cannot create trash object directory: {object_directory}",
                entry_id=entry_id,
                path=str(object_directory),
                errno=exc.errno,
            ) from exc
        return entry_id, object_directory
    raise error(
        "entry_id_collision",
        "could not allocate a unique trash entry id",
    )


def build_trash_record(
    *,
    entry_id: str,
    original_path: str,
    trashed_path: str,
    kind: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "entry_id": entry_id,
        "operation": "trash",
        "state": "active",
        "original_path": original_path,
        "trashed_path": trashed_path,
        "kind": kind,
        "timestamp": utc_timestamp(),
    }


def build_restore_record(
    *,
    entry_id: str,
    original_path: str,
    trashed_path: str,
    kind: str,
    restore_path: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "entry_id": entry_id,
        "operation": "restore",
        "state": "restored",
        "original_path": original_path,
        "trashed_path": trashed_path,
        "kind": kind,
        "timestamp": utc_timestamp(),
        "restore_path": restore_path,
    }


def _ledger_failure(message: str, path: Path, exc: OSError | None = None) -> SafeDeleteError:
    details: dict[str, object] = {"path": str(path)}
    if exc is not None:
        details["errno"] = exc.errno
    return error("ledger_failure", message, **details)


def _open_ledger_parent(layout: Layout) -> int:
    try:
        return open_directory_without_symlinks(layout.ledger.parent)
    except SafeDeleteError as exc:
        raise error(
            "ledger_failure",
            f"cannot open ledger directory: {layout.ledger.parent}",
            path=str(layout.ledger),
            cause=exc.code,
        ) from exc
    except OSError as exc:
        raise _ledger_failure(f"cannot open ledger directory: {layout.ledger.parent}", layout.ledger, exc) from exc


def _verify_ledger_descriptor(
    fd: int,
    parent_fd: int,
    path: Path,
    descriptor_stat: os.stat_result | None = None,
) -> os.stat_result:
    try:
        descriptor_stat = descriptor_stat or os.fstat(fd)
        path_stat = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        raise _ledger_failure(f"cannot verify ledger descriptor: {path}", path, exc) from exc
    if not stat.S_ISREG(descriptor_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
        raise _ledger_failure(f"ledger is not a regular file: {path}", path)
    if (
        descriptor_stat.st_dev != path_stat.st_dev
        or descriptor_stat.st_ino != path_stat.st_ino
    ):
        raise _ledger_failure(f"ledger was replaced while it was open: {path}", path)
    return descriptor_stat


def _sync_parent_directory_fd(parent_fd: int, path: Path) -> None:
    try:
        os.fsync(parent_fd)
    except OSError as exc:
        raise _ledger_failure(f"cannot flush ledger directory: {path.parent}", path, exc) from exc


def read_ledger_lines(layout: Layout) -> list[str]:
    """Read the ledger through a verified descriptor, never a replaced path."""

    parent_fd = _open_ledger_parent(layout)
    fd = None
    try:
        try:
            fd = os.open(
                layout.ledger.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise _ledger_failure(f"cannot open ledger for read: {layout.ledger}", layout.ledger, exc) from exc
        descriptor_stat = _verify_ledger_descriptor(fd, parent_fd, layout.ledger)
        chunks: list[bytes] = []
        while True:
            try:
                chunk = os.read(fd, 1024 * 1024)
            except OSError as exc:
                raise _ledger_failure(f"cannot read ledger: {layout.ledger}", layout.ledger, exc) from exc
            if not chunk:
                break
            chunks.append(chunk)
        _verify_ledger_descriptor(fd, parent_fd, layout.ledger, descriptor_stat)
        try:
            return b"".join(chunks).decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            raise
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent_fd)


def append_event(layout: Layout, record: dict[str, object]) -> None:
    """Append one compact UTF-8 event and durably flush it before returning."""

    try:
        encoded = (
            json.dumps(
                record,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise _ledger_failure("cannot encode ledger event as UTF-8 JSON", layout.ledger) from exc

    parent_fd = _open_ledger_parent(layout)
    fd = None

    try:
        try:
            fd = os.open(
                layout.ledger.name,
                os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise _ledger_failure(f"cannot open ledger for append: {layout.ledger}", layout.ledger, exc) from exc
        descriptor_stat = _verify_ledger_descriptor(fd, parent_fd, layout.ledger)
        # A hand-written or interrupted JSONL line may be valid JSON but lack
        # its final delimiter.  Add the separator as part of this append so
        # the new event can never be glued to the preceding object.
        try:
            end = os.lseek(fd, 0, os.SEEK_END)
            separator = b""
            if end:
                previous = os.pread(fd, 1, end - 1)
                if previous != b"\n":
                    separator = b"\n"
        except OSError as exc:
            raise _ledger_failure(
                f"cannot inspect ledger boundary: {layout.ledger}", layout.ledger, exc
            ) from exc
        encoded = separator + encoded
        offset = 0
        while offset < len(encoded):
            try:
                written = os.write(fd, encoded[offset:])
            except OSError as exc:
                raise _ledger_failure(f"cannot append ledger event: {layout.ledger}", layout.ledger, exc) from exc
            if written <= 0:
                raise _ledger_failure("ledger append made no progress", layout.ledger)
            offset += written
        try:
            os.fsync(fd)
        except OSError as exc:
            raise _ledger_failure(f"cannot flush ledger event: {layout.ledger}", layout.ledger, exc) from exc
        _verify_ledger_descriptor(fd, parent_fd, layout.ledger, descriptor_stat)
        _sync_parent_directory_fd(parent_fd, layout.ledger)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError as exc:
                raise _ledger_failure(f"cannot close ledger after append: {layout.ledger}", layout.ledger, exc) from exc
        os.close(parent_fd)


def remove_empty_object_directory(object_directory: Path) -> None:
    try:
        os.rmdir(object_directory)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise error(
            "storage_failure",
            f"cannot remove empty trash object directory: {object_directory}",
            path=str(object_directory),
            errno=exc.errno,
        ) from exc
