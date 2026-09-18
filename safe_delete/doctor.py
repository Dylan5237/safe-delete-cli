"""Read-only ``safe-delete doctor``.

``doctor`` only aggregates surfaces that already exist and never writes, creates,
or repairs anything:

* the platform preflight (which POSIX primitives this runtime needs);
* the resolved storage root and whether it is currently usable;
* ``hook status`` for every selector, carrying each boundary's
  ``out_of_coverage`` list verbatim;
* the captured payload source of every *installed* package artifact;
* whether an installed boundary's package file is still present and runnable;
* the resolved CLI paths and whether a registered one is world-writable.

What ``doctor`` must never claim.  Its scope is one registered
``(host, config_path)`` boundary at a time.  It must not claim interception of
PowerShell, ``os.unlink`` or any other language filesystem API, an absolute
``/bin/rm``, ``find -delete``, ``git clean``, busybox, a wrapper such as
``sudo``/``env``/``sh -c``, an unconfigured agent/tool, or a human process; it
must not claim that the current project is protected, any enforcement on native
Windows, that Exception #12 is fixed, or that a usable storage root means
deletion is safe.  ``needs_attention: false`` means only that no problem was
detected in the inspected surfaces.

The bypass inventory is reported as data (``out_of_coverage``), never as a
coverage claim: those ten entries are the statement of what is *not* covered.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .hook import (
    HOOK_COMMANDS,
    OUT_OF_COVERAGE_BYPASSES,
    git_checkout_root,
    hook_status,
    is_world_writable,
    payload_source_path,
)
from .platform_check import platform_report


RESTORE_RESIDUAL_NOTE = (
    "Exception #12 — P2-only same-UID staging publication — excluded model / "
    "residual risk; not fixed"
)
SCOPE = "enforced applies only to a registered (host, config_path) boundary"


def _artifact_paths(status: Mapping[str, Any]) -> list[Path]:
    """Return the package files a status reports without re-deriving layout."""

    if status.get("mode") == "path-shim":
        boundary = status.get("boundary")
        shim_dir = boundary.get("shim_dir") if isinstance(boundary, Mapping) else None
        if isinstance(shim_dir, str) and shim_dir:
            return [Path(shim_dir) / command for command in sorted(HOOK_COMMANDS)]
        return []
    package = status.get("package")
    adapter = package.get("adapter_path") if isinstance(package, Mapping) else None
    return [Path(adapter)] if isinstance(adapter, str) and adapter else []


def _artifact_facts(path: Path) -> dict[str, Any]:
    source = payload_source_path(path)
    checkout = git_checkout_root(source) if source is not None else None
    return {
        "path": str(path),
        "payload_source": str(source) if source is not None else None,
        "payload_source_exists": bool(source is not None and source.is_dir()),
        "git_checkout": str(checkout) if checkout is not None else None,
    }


def run_doctor(root: str | None = None) -> dict[str, Any]:
    """Aggregate the read-only checks for one invocation."""

    platform = platform_report()
    statuses = hook_status(None, root=root)
    storage: Mapping[str, Any] = statuses[0].get("storage", {}) if statuses else {}

    problems: list[str] = []
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for status in statuses:
        for path in _artifact_paths(status):
            key = str(path)
            if key in seen or not os.path.lexists(path):
                continue
            seen.add(key)
            facts = _artifact_facts(path)
            artifacts.append(facts)
            if facts["payload_source"] is None:
                problems.append(f"installed payload has no readable source dependency: {path}")
            elif not facts["payload_source_exists"]:
                problems.append(
                    f"installed payload source is missing: {facts['payload_source']}; "
                    "every hook decision at this boundary fails closed"
                )
            elif facts["git_checkout"]:
                problems.append(
                    f"payload source is a git checkout: {facts['git_checkout']}; moving or "
                    "deleting the checkout makes every installed hook fail closed"
                )

    cli_paths = sorted(
        {
            status["cli_path"]
            for status in statuses
            if isinstance(status.get("cli_path"), str) and status["cli_path"]
        }
    )
    world_writable = [item for item in cli_paths if is_world_writable(Path(item))]
    if any(status.get("installed") for status in statuses) and world_writable:
        problems.extend(f"registered CLI is world-writable: {item}" for item in world_writable)

    # A boundary can be *installed* while its package file is gone or no longer
    # importable — a stale registry entry from a moved/deleted checkout, or an
    # adapter deleted after install.  ``_artifact_paths`` skips missing files,
    # so without this the aggregate would stay quiet about a registered
    # integration whose payload cannot run.
    for status in statuses:
        if not status.get("installed"):
            continue
        package = status.get("package")
        if not isinstance(package, Mapping):
            continue
        runnable = (
            package.get("adapter_runnable")
            if status.get("mode") == "pretooluse"
            else package.get("complete")
        )
        if runnable is False:
            selector = status.get("selector", "unknown")
            problems.append(
                f"installed hook payload is missing or not runnable at boundary {selector}: "
                f"{package.get('adapter_path') or package.get('files')}; "
                "every hook decision at this boundary fails closed"
            )

    problems = list(dict.fromkeys(problems))

    return {
        "read_only": True,
        "platform_preflight": {
            "required": platform["requires"],
            "passed": platform["supported"],
            "missing_primitives": platform["missing_primitives"],
        },
        "storage": dict(storage),
        "boundaries": statuses,
        "artifacts": artifacts,
        "cli": {"paths": cli_paths, "world_writable": world_writable},
        "out_of_coverage": list(OUT_OF_COVERAGE_BYPASSES),
        "scope": SCOPE,
        "problems": problems,
        "needs_attention": bool(problems),
        "restore": {"residual_note": RESTORE_RESIDUAL_NOTE},
    }
