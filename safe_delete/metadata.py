"""P3 rich metadata schema, validation, and JSON projections."""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import SafeDeleteError, error
from .storage import normalized_path


RICH_SCALAR_FIELDS = ("project", "session_id", "reason", "agent", "tool")
RICH_FIELDS = (*RICH_SCALAR_FIELDS, "extensions")
_SCALAR_LIMITS = {
    "project": 4096,
    "reason": 4096,
    "session_id": 256,
    "agent": 256,
    "tool": 256,
}
EXTENSIONS_MAX_BYTES = 16 * 1024


def _metadata_error(field_name: str, message: str) -> SafeDeleteError:
    return error("usage_error", f"invalid {field_name}: {message}", field=field_name)


def _encoded_utf8(value: str, *, field_name: str) -> bytes:
    if "\x00" in value:
        raise _metadata_error(field_name, "NUL is not allowed")
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _metadata_error(field_name, "value is not valid UTF-8") from exc


def validate_scalar(
    field_name: str,
    value: Any,
    *,
    normalize_project: bool = False,
) -> str | None:
    """Validate one rich scalar and return its stored representation."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise _metadata_error(field_name, "value must be a string or null")
    encoded = _encoded_utf8(value, field_name=field_name)
    if not value.strip():
        return None
    if normalize_project:
        try:
            value = normalized_path(value, field_name=field_name)
        except SafeDeleteError as exc:
            raise _metadata_error(field_name, exc.message) from exc
        encoded = _encoded_utf8(value, field_name=field_name)
    if len(encoded) > _SCALAR_LIMITS[field_name]:
        raise _metadata_error(
            field_name,
            f"UTF-8 value exceeds {_SCALAR_LIMITS[field_name]} bytes",
        )
    return value


class _DuplicateKey(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(f"duplicate extension key: {key}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> Any:
    raise ValueError(f"non-finite JSON value: {value}")


def _validate_extension_value(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise _metadata_error("extensions", f"key at {path} is not a string")
            _encoded_utf8(key, field_name="extensions")
            _validate_extension_value(nested, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_extension_value(nested, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        _encoded_utf8(value, field_name="extensions")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise _metadata_error("extensions", "values must be finite JSON values")
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise _metadata_error("extensions", f"value at {path} is not a JSON value")


def validate_extensions_object(value: Any) -> dict[str, Any]:
    """Validate an already-decoded top-level JSON object."""

    if not isinstance(value, dict):
        raise _metadata_error("extensions", "value must be a JSON object")
    _validate_extension_value(value, path="$")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise _metadata_error("extensions", "value is not finite UTF-8 JSON") from exc
    if len(encoded) > EXTENSIONS_MAX_BYTES:
        raise _metadata_error(
            "extensions",
            f"compact UTF-8 value exceeds {EXTENSIONS_MAX_BYTES} bytes",
        )
    return copy.deepcopy(value)


def parse_extensions_json(value: Any) -> dict[str, Any]:
    """Decode and validate the additive ``--extensions`` JSON argument."""

    if not isinstance(value, str):
        raise _metadata_error("extensions", "value must be a JSON object")
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, _DuplicateKey, ValueError) as exc:
        raise _metadata_error("extensions", "value must be finite JSON without duplicate keys") from exc
    return validate_extensions_object(decoded)


@dataclass(frozen=True)
class RichMetadata:
    """Validated P3 metadata carried by a creation and its lifecycle events."""

    project: str | None = None
    session_id: str | None = None
    reason: str | None = None
    agent: str | None = None
    tool: str | None = None
    extensions: dict[str, Any] | None = None

    def record_fields(self) -> dict[str, Any]:
        """Return fields for a new event; omit unset extensions on disk."""

        # P3-written events always carry the five scalar keys.  ``extensions``
        # is intentionally optional on disk and is omitted when not supplied.
        fields: dict[str, Any] = {
            field_name: copy.deepcopy(getattr(self, field_name))
            for field_name in RICH_SCALAR_FIELDS
        }
        if self.extensions is not None:
            fields["extensions"] = copy.deepcopy(self.extensions)
        return fields

    def projection_fields(self) -> dict[str, Any]:
        """Return all six rich keys for normalized JSON output."""

        fields = self.record_fields()
        fields["extensions"] = copy.deepcopy(self.extensions)
        return fields


def metadata_from_record(record: Mapping[str, Any]) -> RichMetadata:
    """Validate a ledger record's optional P2/P3 rich fields."""

    values = {
        field_name: validate_scalar(
            field_name,
            record.get(field_name),
            normalize_project=field_name == "project",
        )
        for field_name in RICH_SCALAR_FIELDS
    }
    if "extensions" in record:
        extensions = validate_extensions_object(record["extensions"])
    else:
        extensions = None
    return RichMetadata(**values, extensions=extensions)


def project_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Project a validated raw record without changing the raw ledger object."""

    projected = copy.deepcopy(dict(record))
    projected.update(metadata_from_record(record).projection_fields())
    return projected
