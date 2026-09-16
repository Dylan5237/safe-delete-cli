"""Retention policy parsing and fail-closed purge eligibility decisions.

``--older-than`` deliberately has a small, unambiguous grammar: a positive
base-10 integer followed by either ``d`` (days) or ``h`` (hours), for example
``30d`` or ``720h``.  Signs, decimals, whitespace, bare numbers, and other
unit suffixes are usage errors.

The initial ``trash`` event timestamp is the only age anchor.  Restore and
purge lifecycle timestamps never reset it.  Ordinary eligibility is inclusive:
an entry whose anchor is at or before the selected UTC cutoff is eligible.
Crash recovery for a durable ``purge_intent`` is handled before ordinary age
evaluation and therefore does not reapply a later or stricter cutoff.
"""

from __future__ import annotations

import datetime as _datetime
import os
import re
from dataclasses import dataclass
from typing import Any

from .errors import SafeDeleteError, error


DEFAULT_RETENTION_DAYS = 30
_SECONDS_PER_DAY = 24 * 60 * 60
_DECIMAL_INTEGER = re.compile(r"^[0-9]+$")
_OLDER_THAN = re.compile(r"^([0-9]+)([dh])$")
_RFC3339_WITH_ZONE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def utc_now() -> _datetime.datetime:
    """Return the aware UTC clock used for one purge invocation."""

    return _datetime.datetime.now(_datetime.timezone.utc)


def _usage(message: str, **details: Any) -> SafeDeleteError:
    return error("usage_error", message, **details)


def _positive_decimal(value: str, *, field_name: str) -> int:
    if not isinstance(value, str) or not _DECIMAL_INTEGER.fullmatch(value):
        raise _usage(
            f"{field_name} must be a positive base-10 integer",
            value=value,
        )
    try:
        parsed = int(value, 10)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _usage(
            f"{field_name} must be a positive base-10 integer",
            value=value,
        ) from exc
    if parsed <= 0:
        raise _usage(
            f"{field_name} must be a positive base-10 integer",
            value=value,
        )
    return parsed


def _timedelta_from_days(days: int, *, field_name: str) -> _datetime.timedelta:
    try:
        return _datetime.timedelta(days=days)
    except (OverflowError, ValueError) as exc:
        raise _usage(
            f"{field_name} is outside the supported retention range",
            value=days,
        ) from exc


def _cutoff_from_threshold(
    as_of: _datetime.datetime,
    threshold: _datetime.timedelta,
    *,
    field_name: str,
    value: Any,
) -> _datetime.datetime:
    try:
        return as_of - threshold
    except (OverflowError, TypeError, ValueError) as exc:
        raise _usage(
            f"{field_name} is outside the supported retention range",
            value=value,
        ) from exc


def parse_older_than(value: str) -> tuple[_datetime.timedelta, str, int | float]:
    """Parse the frozen positive-integer ``d``/``h`` duration grammar."""

    match = _OLDER_THAN.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise _usage(
            "--older-than must be a positive integer followed by d or h",
            value=value,
        )
    amount_text, unit = match.groups()
    try:
        amount = int(amount_text, 10)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _usage("--older-than is outside the supported range", value=value) from exc
    if amount <= 0:
        raise _usage(
            "--older-than must be a positive integer followed by d or h",
            value=value,
        )
    try:
        duration = (
            _datetime.timedelta(days=amount)
            if unit == "d"
            else _datetime.timedelta(hours=amount)
        )
    except (OverflowError, ValueError) as exc:
        raise _usage("--older-than is outside the supported range", value=value) from exc
    days: int | float
    if unit == "d":
        days = amount
    elif amount % 24 == 0:
        days = amount // 24
    else:
        days = amount / 24
    return duration, f"{amount}{unit}", days


def parse_rfc3339(value: str, *, field_name: str = "timestamp") -> _datetime.datetime:
    """Parse a timezone-bearing RFC3339 instant and normalize it to UTC."""

    if not isinstance(value, str) or _RFC3339_WITH_ZONE.fullmatch(value) is None:
        raise _usage(
            f"{field_name} must be an RFC3339 timestamp with a timezone",
            value=value,
        )
    source = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = _datetime.datetime.fromisoformat(source)
    except (OverflowError, TypeError, ValueError) as exc:
        raise _usage(
            f"{field_name} must be a valid RFC3339 timestamp",
            value=value,
        ) from exc
    try:
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise _usage(
                f"{field_name} must include a timezone",
                value=value,
            )
        return parsed.astimezone(_datetime.timezone.utc)
    except SafeDeleteError:
        raise
    except (OverflowError, TypeError, ValueError) as exc:
        raise _usage(
            f"{field_name} must be a valid RFC3339 timestamp",
            value=value,
        ) from exc


def format_utc(value: _datetime.datetime) -> str:
    """Render an aware instant as canonical UTC RFC3339 text."""

    normalized = value.astimezone(_datetime.timezone.utc)
    timespec = "microseconds" if normalized.microsecond else "seconds"
    return normalized.isoformat(timespec=timespec).replace("+00:00", "Z")


@dataclass(frozen=True)
class RetentionPolicy:
    """The fully resolved policy for one purge invocation."""

    source: str
    as_of: _datetime.datetime
    cutoff: _datetime.datetime
    threshold: _datetime.timedelta | None
    threshold_days: int | float | None = None
    threshold_duration: str | None = None

    @classmethod
    def resolve(
        cls,
        *,
        older_than: str | None = None,
        before: str | None = None,
        now: _datetime.datetime | None = None,
        environment: str | None = None,
    ) -> "RetentionPolicy":
        """Resolve flag → environment → default precedence for one run."""

        if older_than is not None and before is not None:
            raise _usage("--older-than and --before are mutually exclusive")

        as_of = now if now is not None else utc_now()
        try:
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise _usage("purge clock must include a timezone")
            as_of = as_of.astimezone(_datetime.timezone.utc)
        except SafeDeleteError:
            raise
        except (OverflowError, TypeError, ValueError) as exc:
            raise _usage("purge clock is outside the supported range") from exc

        if older_than is not None:
            threshold, duration_text, days = parse_older_than(older_than)
            return cls(
                source="older_than",
                as_of=as_of,
                cutoff=_cutoff_from_threshold(
                    as_of,
                    threshold,
                    field_name="--older-than",
                    value=older_than,
                ),
                threshold=threshold,
                threshold_days=days,
                threshold_duration=duration_text,
            )

        if before is not None:
            cutoff = parse_rfc3339(before, field_name="--before")
            return cls(
                source="before",
                as_of=as_of,
                cutoff=cutoff,
                threshold=None,
                threshold_days=None,
                threshold_duration=None,
            )

        if environment is None:
            environment = os.environ.get("SAFE_DELETE_RETENTION_DAYS")
        if environment is not None:
            days = _positive_decimal(
                environment,
                field_name="SAFE_DELETE_RETENTION_DAYS",
            )
            threshold = _timedelta_from_days(
                days,
                field_name="SAFE_DELETE_RETENTION_DAYS",
            )
            return cls(
                source="environment",
                as_of=as_of,
                cutoff=_cutoff_from_threshold(
                    as_of,
                    threshold,
                    field_name="SAFE_DELETE_RETENTION_DAYS",
                    value=days,
                ),
                threshold=threshold,
                threshold_days=days,
                threshold_duration=f"{days}d",
            )

        threshold = _timedelta_from_days(
            DEFAULT_RETENTION_DAYS,
            field_name="default retention",
        )
        return cls(
            source="default",
            as_of=as_of,
            cutoff=_cutoff_from_threshold(
                as_of,
                threshold,
                field_name="default retention",
                value=DEFAULT_RETENTION_DAYS,
            ),
            threshold=threshold,
            threshold_days=DEFAULT_RETENTION_DAYS,
            threshold_duration=f"{DEFAULT_RETENTION_DAYS}d",
        )

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source": self.source,
            "as_of": format_utc(self.as_of),
            "cutoff": format_utc(self.cutoff),
            "cutoff_utc": format_utc(self.cutoff),
            "threshold_days": self.threshold_days,
            "threshold_duration": self.threshold_duration,
        }
        if self.threshold is not None:
            result["threshold_seconds"] = int(self.threshold.total_seconds())
        return result


def _entry_anchor(entry: Any) -> _datetime.datetime | None:
    creation = getattr(entry, "creation", None)
    timestamp = creation.get("timestamp") if isinstance(creation, dict) else None
    if not isinstance(timestamp, str):
        return None
    try:
        return parse_rfc3339(timestamp)
    except SafeDeleteError:
        return None


def _last_operation(entry: Any) -> str | None:
    events = getattr(entry, "events", None)
    if not events or not isinstance(events[-1], dict):
        return None
    operation = events[-1].get("operation")
    return operation if isinstance(operation, str) else None


@dataclass(frozen=True)
class Eligibility:
    """One auditable candidate/exclusion decision."""

    selected: bool
    reason: str
    anchor: _datetime.datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": "candidate" if self.selected else "excluded",
            "reason": self.reason,
            **({"age_anchor": format_utc(self.anchor)} if self.anchor else {}),
        }


def evaluate_entry(
    entry: Any,
    policy: RetentionPolicy,
    *,
    payload_present: bool = True,
    audit_error: bool = False,
) -> Eligibility:
    """Return a fail-closed decision for a replayed ledger entry.

    ``purge_pending`` with a final ``purge_intent`` is evaluated first.  A
    durable intent is the authorization recorded at the original decision
    point, so recovery does not use the current policy cutoff.
    """

    state = getattr(entry, "state", None)
    if audit_error:
        return Eligibility(False, "audit_error")

    if state == "purge_pending":
        if _last_operation(entry) != "purge_intent":
            return Eligibility(False, "pending_not_recoverable")
        if not payload_present:
            return Eligibility(False, "payload_missing")
        return Eligibility(True, "crash_recovery", _entry_anchor(entry))

    anchor = _entry_anchor(entry)
    if state == "active":
        if not payload_present:
            return Eligibility(False, "payload_missing", anchor)
        if anchor is None:
            return Eligibility(False, "malformed_timestamp")
        if anchor > policy.as_of:
            return Eligibility(False, "future_dated", anchor)
        if anchor <= policy.cutoff:
            return Eligibility(True, "eligible", anchor)
        return Eligibility(False, "too_young", anchor)
    if state == "restored":
        return Eligibility(False, "restored", anchor)
    if state == "purged":
        return Eligibility(False, "already_purged", anchor)
    return Eligibility(False, "unknown_state")
