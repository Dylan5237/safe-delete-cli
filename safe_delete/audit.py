"""Strict replay and object reconciliation for the versioned JSONL ledger."""

from __future__ import annotations

import datetime as _datetime
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from .errors import SafeDeleteError, error
from .ledger import read_ledger_lines
from .metadata import (
    _reject_duplicate_keys,
    _reject_non_finite,
    metadata_from_record,
)
from .storage import Layout, ensure_safe_target, has_entry, kind_for, normalized_path


_RFC3339_Z = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_KINDS = {"file", "directory", "symlink"}
_DECLARED_FIELDS = {
    "schema_version",
    "event_id",
    "entry_id",
    "operation",
    "state",
    "original_path",
    "trashed_path",
    "kind",
    "timestamp",
    "restore_path",
    "project",
    "session_id",
    "reason",
    "agent",
    "tool",
    "extensions",
    "error_code",
}


@dataclass
class LedgerEntry:
    entry_id: str
    creation: dict[str, Any]
    events: list[dict[str, Any]]
    state: str
    original_path: str
    trashed_path: str
    kind: str


@dataclass
class AuditReport:
    entries: dict[str, LedgerEntry] = field(default_factory=dict)
    errors: list[SafeDeleteError] = field(default_factory=list)
    tainted_entry_ids: set[str] = field(default_factory=set)

    def errors_for(self, entry_id: str) -> list[SafeDeleteError]:
        return [
            item
            for item in self.errors
            if item.details.get("entry_id") == entry_id or "entry_id" not in item.details
        ]


def is_uuid4(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return (
        parsed.version == 4
        and parsed.variant == uuid.RFC_4122
        and str(parsed) == value
        and len(value) == 36
    )


def _valid_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return os.path.isabs(value) and os.path.normpath(value) == value


def _validate_ledger_path(
    value: Any,
    *,
    layout: Layout,
    field_name: str,
    line_number: int,
    entry_id: str,
) -> None:
    if not _valid_path(value):
        raise _invalid_record(
            line_number,
            f"{field_name} is not absolute and normalized",
            entry_id=entry_id,
        )
    try:
        # The same lexical storage-target policy applies to historical paths
        # as to live CLI inputs.  Requiring the current canonical parent also
        # prevents a ledger path from becoming unsafe through a parent link.
        if normalized_path(value, field_name=field_name) != value:
            raise ValueError("parent symlink is not canonical")
        ensure_safe_target(layout, value)
    except (SafeDeleteError, ValueError) as exc:
        raise _invalid_record(
            line_number,
            f"{field_name} fails safe path validation",
            entry_id=entry_id,
        ) from exc


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not _RFC3339_Z.fullmatch(value):
        return False
    try:
        _datetime.datetime.fromisoformat(value[:-1]).replace(
            tzinfo=_datetime.timezone.utc
        )
    except ValueError:
        return False
    return True


def _hint_entry_id(record: Any) -> str | None:
    if isinstance(record, dict):
        value = record.get("entry_id")
        if isinstance(value, str):
            return value
    return None


def _invalid_record(
    line_number: int,
    message: str,
    *,
    entry_id: str | None = None,
) -> SafeDeleteError:
    details: dict[str, Any] = {"line": line_number}
    if entry_id is not None:
        details["entry_id"] = entry_id
    return error("malformed_ledger", message, **details)


def _validate_record(record: Any, layout: Layout, line_number: int) -> dict[str, Any]:
    entry_hint = _hint_entry_id(record)
    if not isinstance(record, dict):
        raise _invalid_record(line_number, "ledger line must be a JSON object")

    unknown = sorted(set(record) - _DECLARED_FIELDS)
    if unknown:
        raise _invalid_record(
            line_number,
            f"ledger record contains undeclared field(s): {', '.join(unknown)}",
            entry_id=entry_hint,
        )

    required = (
        "schema_version",
        "event_id",
        "entry_id",
        "operation",
        "state",
        "original_path",
        "trashed_path",
        "kind",
        "timestamp",
    )
    missing = [key for key in required if key not in record]
    if missing:
        raise _invalid_record(
            line_number,
            f"ledger record is missing required field(s): {', '.join(missing)}",
            entry_id=entry_hint,
        )
    if isinstance(record.get("schema_version"), bool) or not isinstance(
        record.get("schema_version"), int
    ):
        raise _invalid_record(
            line_number,
            "schema_version must be integer 1",
            entry_id=entry_hint,
        )
    if record["schema_version"] != 1:
        raise SafeDeleteError(
            "unsupported_schema_version",
            "ledger schema version is not supported",
            {"line": line_number, **({"entry_id": entry_hint} if entry_hint else {})},
        )
    if not is_uuid4(record["event_id"]):
        raise _invalid_record(line_number, "event_id is not a canonical UUID v4", entry_id=entry_hint)
    if not is_uuid4(record["entry_id"]):
        raise _invalid_record(line_number, "entry_id is not a canonical UUID v4", entry_id=entry_hint)
    if not isinstance(record["operation"], str) or record["operation"] not in {"trash", "restore"}:
        raise _invalid_record(
            line_number,
            "operation must be trash or restore in schema 1 P2",
            entry_id=record["entry_id"],
        )
    if not isinstance(record["state"], str) or record["state"] not in {"active", "restored"}:
        raise _invalid_record(
            line_number,
            "state must be active or restored in schema 1 P2",
            entry_id=record["entry_id"],
        )
    _validate_ledger_path(
        record["original_path"],
        layout=layout,
        field_name="original_path",
        line_number=line_number,
        entry_id=record["entry_id"],
    )
    if not _valid_path(record["trashed_path"]):
        raise _invalid_record(line_number, "trashed_path is not absolute and normalized", entry_id=record["entry_id"])
    expected_payload = os.fspath(layout.payload(record["entry_id"]))
    if record["trashed_path"] != expected_payload:
        raise _invalid_record(
            line_number,
            "trashed_path does not match the entry object path",
            entry_id=record["entry_id"],
        )
    if not isinstance(record["kind"], str) or record["kind"] not in _KINDS:
        raise _invalid_record(line_number, "kind is not a supported P2 kind", entry_id=record["entry_id"])
    if not _valid_timestamp(record["timestamp"]):
        raise _invalid_record(line_number, "timestamp is not UTC RFC3339 with Z", entry_id=record["entry_id"])
    if record["operation"] == "trash":
        if record["state"] != "active" or "restore_path" in record:
            raise _invalid_record(
                line_number,
                "trash records must be active and omit restore_path",
                entry_id=record["entry_id"],
            )
    else:
        _validate_ledger_path(
            record.get("restore_path"),
            layout=layout,
            field_name="restore_path",
            line_number=line_number,
            entry_id=record["entry_id"],
        )
        if record["state"] != "restored":
            raise _invalid_record(
                line_number,
                "restore records must be restored and include restore_path",
                entry_id=record["entry_id"],
            )
    if "error_code" in record:
        raise _invalid_record(
            line_number,
            "error_code is not valid on P2 trash or restore records",
            entry_id=record["entry_id"],
        )
    if "extensions" in record and not isinstance(record["extensions"], dict):
        raise _invalid_record(
            line_number,
            "extensions must be an object when present",
            entry_id=record["entry_id"],
        )
    for field_name in ("project", "session_id", "reason", "agent", "tool"):
        if field_name in record and record[field_name] is not None and not isinstance(record[field_name], str):
            raise _invalid_record(
                line_number,
                f"{field_name} must be a string or null",
                entry_id=record["entry_id"],
            )
    if "error_code" in record and not isinstance(record["error_code"], str):
        raise _invalid_record(
            line_number,
            "error_code must be a string",
            entry_id=record["entry_id"],
        )
    try:
        metadata_from_record(record)
    except SafeDeleteError as exc:
        raise _invalid_record(
            line_number,
            exc.message,
            entry_id=record.get("entry_id") if isinstance(record.get("entry_id"), str) else entry_hint,
        ) from exc
    return record


def _read_records(layout: Layout, report: AuditReport) -> list[dict[str, Any]]:
    try:
        lines = read_ledger_lines(layout)
    except UnicodeDecodeError as exc:
        report.errors.append(
            error(
                "malformed_ledger",
                "ledger is not valid UTF-8",
                line=getattr(exc, "start", None),
            )
        )
        return []
    except SafeDeleteError as exc:
        report.errors.append(exc)
        return []
    except OSError as exc:
        report.errors.append(
            error(
                "ledger_failure",
                f"cannot read ledger: {layout.ledger}",
                path=str(layout.ledger),
                errno=exc.errno,
            )
        )
        return []

    records: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            report.errors.append(_invalid_record(line_number, "blank ledger line"))
            continue
        try:
            raw = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_non_finite,
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            report.errors.append(
                _invalid_record(line_number, f"invalid JSON ledger line: {exc}")
            )
            continue
        event_hint = raw.get("event_id") if isinstance(raw, dict) else None
        entry_hint = _hint_entry_id(raw)
        if isinstance(event_hint, str) and is_uuid4(event_hint):
            if event_hint in event_ids:
                details: dict[str, Any] = {"line": line_number, "event_id": event_hint}
                if entry_hint:
                    details["entry_id"] = entry_hint
                report.errors.append(
                    error("duplicate_event_id", "event_id occurs more than once", **details)
                )
                if entry_hint:
                    report.tainted_entry_ids.add(entry_hint)
                continue
            event_ids.add(event_hint)
        try:
            record = _validate_record(raw, layout, line_number)
        except SafeDeleteError as exc:
            report.errors.append(exc)
            if entry_hint:
                report.tainted_entry_ids.add(entry_hint)
            continue
        records.append(record)

    return records


def _replay(records: list[dict[str, Any]], report: AuditReport) -> None:
    for record in records:
        entry_id = record["entry_id"]
        current = report.entries.get(entry_id)
        if record["operation"] == "trash":
            if current is not None:
                report.errors.append(
                    error(
                        "impossible_transition",
                        "an entry has more than one trash creation event",
                        entry_id=entry_id,
                    )
                )
                report.tainted_entry_ids.add(entry_id)
                continue
            report.entries[entry_id] = LedgerEntry(
                entry_id=entry_id,
                creation=record,
                events=[record],
                state="active",
                original_path=record["original_path"],
                trashed_path=record["trashed_path"],
                kind=record["kind"],
            )
            continue

        if current is None:
            report.errors.append(
                error(
                    "impossible_transition",
                    "restore event has no preceding trash event",
                    entry_id=entry_id,
                )
            )
            report.tainted_entry_ids.add(entry_id)
            continue
        if current.state != "active":
            report.errors.append(
                error(
                    "impossible_transition",
                    "restore event does not follow an active entry",
                    entry_id=entry_id,
                )
            )
            report.tainted_entry_ids.add(entry_id)
            continue
        immutable_fields = ("original_path", "trashed_path", "kind")
        if any(record[key] != getattr(current, key) for key in immutable_fields):
            report.errors.append(
                error(
                    "impossible_transition",
                    "lifecycle event changes immutable entry fields",
                    entry_id=entry_id,
                )
            )
            report.tainted_entry_ids.add(entry_id)
            continue
        if metadata_from_record(record) != metadata_from_record(current.creation):
            report.errors.append(
                error(
                    "impossible_transition",
                    "lifecycle event changes rich deletion metadata",
                    entry_id=entry_id,
                )
            )
            report.tainted_entry_ids.add(entry_id)
            continue
        current.events.append(record)
        current.state = "restored"


def _reconcile_objects(layout: Layout, report: AuditReport) -> None:
    try:
        children = list(os.scandir(layout.objects))
    except OSError as exc:
        report.errors.append(
            error(
                "storage_failure",
                f"cannot scan trash objects: {layout.objects}",
                path=str(layout.objects),
                errno=exc.errno,
            )
        )
        return

    valid_creation_ids = set(report.entries)
    for child in children:
        child_path = layout.objects / child.name
        try:
            child_stat = os.lstat(child_path)
        except OSError as exc:
            report.errors.append(
                error(
                    "storage_failure",
                    f"cannot inspect trash object: {child_path}",
                    path=str(child_path),
                    errno=exc.errno,
                )
            )
            continue
        if not os.path.isdir(child_path) or os.path.islink(child_path):
            report.errors.append(
                error(
                    "orphan_payload",
                    "trash object is not a real object directory",
                    entry_id=child.name,
                    trashed_path=str(child_path / "payload"),
                )
            )
            continue
        payload = child_path / "payload"
        try:
            payload_exists = has_entry(payload)
        except SafeDeleteError as exc:
            report.errors.append(exc)
            continue
        if not payload_exists:
            continue
        if child.name not in valid_creation_ids:
            report.errors.append(
                error(
                    "orphan_payload",
                    "trash payload has no matching valid trash event",
                    entry_id=child.name,
                    trashed_path=str(payload),
                )
            )
            continue
        entry = report.entries[child.name]
        try:
            actual_kind = kind_for(payload)
        except SafeDeleteError as exc:
            report.errors.append(exc)
            report.tainted_entry_ids.add(entry.entry_id)
            continue
        if entry.state == "active" and actual_kind != entry.kind:
            report.errors.append(
                error(
                    "storage_failure",
                    "payload kind does not match its ledger record",
                    entry_id=entry.entry_id,
                    trashed_path=str(payload),
                )
            )
            report.tainted_entry_ids.add(entry.entry_id)
        elif entry.state == "restored":
            report.errors.append(
                error(
                    "storage_failure",
                    "restored entry still has a trash payload",
                    entry_id=entry.entry_id,
                    trashed_path=str(payload),
                )
            )
            report.tainted_entry_ids.add(entry.entry_id)

    for entry_id, entry in report.entries.items():
        if entry.state == "active" and not has_entry(layout.payload(entry_id)):
            report.errors.append(
                error(
                    "payload_missing",
                    "active ledger entry has no payload",
                    entry_id=entry_id,
                    trashed_path=str(layout.payload(entry_id)),
                )
            )
            report.tainted_entry_ids.add(entry_id)


def audit_layout(layout: Layout) -> AuditReport:
    report = AuditReport()
    records = _read_records(layout, report)
    _replay(records, report)
    for entry_id in report.tainted_entry_ids:
        report.entries.pop(entry_id, None)
    _reconcile_objects(layout, report)
    for entry_id in report.tainted_entry_ids:
        report.entries.pop(entry_id, None)
    return report
