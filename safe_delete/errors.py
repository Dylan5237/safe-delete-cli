"""Stable machine-readable errors and reserved process exit categories."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EXIT_SUCCESS = 0
EXIT_USAGE = 2
EXIT_CONFLICT = 3
EXIT_STORAGE = 4
EXIT_PARTIAL = 5


ERROR_EXIT_CATEGORIES: dict[str, int] = {
    "usage_error": EXIT_USAGE,
    "unsupported_command": EXIT_USAGE,
    "source_not_found": EXIT_USAGE,
    "unsupported_kind": EXIT_USAGE,
    "unsupported_path_encoding": EXIT_USAGE,
    "path_forbidden": EXIT_USAGE,
    "cross_device": EXIT_USAGE,
    "destination_exists": EXIT_CONFLICT,
    "destination_parent_missing": EXIT_CONFLICT,
    "entry_not_found": EXIT_CONFLICT,
    "entry_not_restorable": EXIT_CONFLICT,
    "already_restored": EXIT_SUCCESS,
    "already_purged": EXIT_SUCCESS,
    "entry_id_collision": EXIT_CONFLICT,
    "unsupported_schema_version": EXIT_STORAGE,
    "malformed_ledger": EXIT_STORAGE,
    "duplicate_event_id": EXIT_STORAGE,
    "impossible_transition": EXIT_STORAGE,
    "payload_missing": EXIT_STORAGE,
    "orphan_payload": EXIT_STORAGE,
    "ledger_failure": EXIT_STORAGE,
    "storage_failure": EXIT_STORAGE,
    "rollback_failed": EXIT_STORAGE,
    "purge_remove_failed": EXIT_PARTIAL,
    "partial_failure": EXIT_PARTIAL,
}

FROZEN_ERROR_CODES = frozenset(ERROR_EXIT_CATEGORIES)


@dataclass
class SafeDeleteError(Exception):
    """An error whose ``code`` is part of the CLI contract."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)
        if self.code not in FROZEN_ERROR_CODES:
            raise ValueError(f"unknown safe-delete error code: {self.code}")

    @property
    def exit_code(self) -> int:
        return ERROR_EXIT_CATEGORIES[self.code]

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": self.message}
        result.update(self.details)
        return result


def error(code: str, message: str, **details: Any) -> SafeDeleteError:
    return SafeDeleteError(code, message, details)


def exit_code_for(errors: list[SafeDeleteError]) -> int:
    """Return the strongest reserved category represented by ``errors``."""

    if not errors:
        return EXIT_SUCCESS
    categories = {item.exit_code for item in errors}
    if EXIT_PARTIAL in categories:
        return EXIT_PARTIAL
    if EXIT_STORAGE in categories:
        return EXIT_STORAGE
    if EXIT_CONFLICT in categories:
        return EXIT_CONFLICT
    return EXIT_USAGE

