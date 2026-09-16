"""P2 minimum ledger records and durable append helpers."""

from __future__ import annotations

import datetime as _datetime
import errno
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from .errors import SafeDeleteError, error
from .storage import Layout, kind_for


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


def _sync_parent_directory(path: Path) -> None:
    try:
        fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError as exc:
        raise _ledger_failure(
            f"cannot open ledger directory for durability: {path.parent}", path, exc
        ) from exc
    try:
        os.fsync(fd)
    except OSError as exc:
        raise _ledger_failure(
            f"cannot flush ledger directory: {path.parent}", path, exc
        ) from exc
    finally:
        os.close(fd)


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

    try:
        fd = os.open(layout.ledger, os.O_WRONLY | os.O_APPEND)
    except OSError as exc:
        raise _ledger_failure(f"cannot open ledger for append: {layout.ledger}", layout.ledger, exc) from exc

    try:
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
    finally:
        try:
            os.close(fd)
        except OSError as exc:
            raise _ledger_failure(f"cannot close ledger after append: {layout.ledger}", layout.ledger, exc) from exc
    _sync_parent_directory(layout.ledger)


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

