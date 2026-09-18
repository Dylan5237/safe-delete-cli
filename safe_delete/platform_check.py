"""Fail-closed platform preflight for the POSIX-only runtime.

``safe_delete.storage`` imports ``fcntl`` at module import time and then
requires ``O_NOFOLLOW``/``O_DIRECTORY``.  On a native Windows interpreter that
surfaces as ``ModuleNotFoundError: No module named 'fcntl'`` before any command
runs, which reads like a broken product rather than a wrong interpreter.

This module therefore imports **nothing** from the storage or CLI layers, so a
CLI entry point can run the check before those imports and replace the
traceback with one explicit line and a defined exit code.  It does not claim
enforcement on any platform; it only states which primitives  the runtime needs.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Sequence
from typing import Any

UNSUPPORTED_PLATFORM_MESSAGE = "unsupported platform: requires Linux/macOS/WSL (fcntl)"
UNSUPPORTED_PLATFORM_EXIT = 2
REQUIRED_PLATFORM = "Linux/macOS/WSL (fcntl)"
_DIRECTORY_FLAGS = ("O_NOFOLLOW", "O_DIRECTORY")


def missing_posix_primitives() -> list[str]:
    """Return the POSIX primitives this runtime needs but cannot provide."""

    missing: list[str] = []
    if not _module_is_importable("fcntl"):
        missing.append("fcntl")
    for name in _DIRECTORY_FLAGS:
        if not getattr(os, name, 0):
            missing.append(name)
    return missing


def _module_is_importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def platform_report() -> dict[str, Any]:
    """Return the platform facts shared by the CLI preflight and ``doctor``."""

    missing = missing_posix_primitives()
    return {
        "requires": REQUIRED_PLATFORM,
        "supported": not missing,
        "missing_primitives": missing,
    }


def preflight(argv: Sequence[str] | None = None, *, stream: Any | None = None) -> int | None:
    """Print one line and return exit 2 when the platform is unsupported.

    ``None`` means the platform is supported and the caller may continue.
    ``argv`` is accepted so an entry point can pass its raw arguments without a
    special case; the check itself is platform-only and never inspects them.
    """

    del argv  # the preflight is platform-only; no argument changes the outcome
    report = platform_report()
    if report["supported"]:
        return None
    if stream is None:
        stream = sys.stderr
    try:
        stream.write(UNSUPPORTED_PLATFORM_MESSAGE + "\n")
    except TypeError:  # a binary stream
        stream.write((UNSUPPORTED_PLATFORM_MESSAGE + "\n").encode("utf-8"))
    return UNSUPPORTED_PLATFORM_EXIT
