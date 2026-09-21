"""Human-readable rendering for the ``safe-delete`` CLI.

Human output is presentation only and is deliberately **not** a stable parsing
interface: wording, ordering, colour, and layout may change in any later
commit.  The only stable elements are the error ``code`` values, the exit
category, and — for the commands the P8 contract names — the presence of
``entry_id`` and ``original_path``.  Agents, hooks, cron jobs, and tests must
use ``--json``; this module never changes results, ordering, filters, exit
codes, or mutations.

Two disclosure rules are load-bearing here and are asserted by the P8 gates:

* the Exception #12 residual note is printed by ``doctor`` and ``restore``
  always, and by ``list``/``show`` when a restore-related state is displayed;
* the wipe-all warning and the "nothing was removed" statement are never
  softened into a safety claim, and no renderer may present ``doctor`` as
  coverage or an install as enforcement.
"""

from __future__ import annotations

import datetime as _datetime
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .doctor import RESTORE_RESIDUAL_NOTE
from .errors import SafeDeleteError
from .retention import parse_rfc3339, utc_now


DOCTOR_READ_ONLY_STATEMENT = (
    "doctor is read-only: it inspects the surfaces above and writes, creates, "
    "repairs, and configures nothing."
)
DOCTOR_HONEST_FOOTER = (
    "needs_attention: false means only that nothing was detected in the "
    "surfaces above; it is not a coverage claim and not an enforcement "
    "guarantee for any boundary."
)
PURGE_PREVIEW_NOTHING_REMOVED = (
    "nothing was removed: this was a preview (purge removes payloads only "
    "under --execute --yes)"
)
PATH_ACTIVATION_IS_OPERATOR_OWNED = (
    "PATH activation is operator-owned: prepend the shim directory yourself; "
    "path_precedence reports only the current process environment"
)
SETUP_INSTALL_IS_NOT_ENFORCEMENT = (
    "an installed integration is not an enforced one: enforced=true means this one "
    "registered (host, config_path) boundary is proven, never that a project is "
    "covered"
)
UNRESOLVED_ROOT = "<root not resolved by this invocation>"

_RESTORE_STATES = frozenset({"restored"})


def render(
    command: str,
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    *,
    root: str | None = None,
) -> str:
    """Render one command's results as human text (errors stay on stderr)."""

    renderer = _RENDERERS.get(command)
    if renderer is None:
        return _render_generic(results, errors, root)
    return renderer(results, errors, root)


def _out(lines: Sequence[str]) -> str:
    if not lines:
        return ""
    return "\n".join(line for line in lines if line != "") + "\n"


def _encode(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _age(raw: Any) -> str:
    """Render the trash-anchor age, the only frozen age anchor."""

    if not isinstance(raw, str):
        return "unknown"
    try:
        instant = parse_rfc3339(raw)
    except SafeDeleteError:
        return "unknown"
    delta = utc_now() - instant
    if delta < _datetime.timedelta(0):
        return "future-dated"
    if delta.days:
        return f"{delta.days}d"
    hours = delta.seconds // 3600
    if hours:
        return f"{hours}h"
    minutes = delta.seconds // 60
    if minutes:
        return f"{minutes}m"
    return f"{delta.seconds}s"


def _root_line(root: str | None) -> str:
    return f"root: {root or UNRESOLVED_ROOT}"


def _render_list(
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    root: str | None,
) -> str:
    lines = [_root_line(root)]
    if not results:
        lines.append("no entries")
    else:
        lines.append(f"entries: {len(results)}")
        for item in results:
            lines.append(
                "  {entry_id}  {state}  {kind}  age={age}  {original_path}".format(
                    entry_id=item.get("entry_id"),
                    state=item.get("state"),
                    kind=item.get("kind"),
                    age=_age(item.get("timestamp")),
                    original_path=item.get("original_path"),
                )
            )
    active = sum(1 for item in results if item.get("state") == "active")
    orphans = sum(1 for item in errors if item.get("code") == "orphan_payload")
    lines.append(f"active: {active}  other: {len(results) - active}  orphan payloads: {orphans}")
    if any(item.get("state") in _RESTORE_STATES for item in results):
        lines.append(RESTORE_RESIDUAL_NOTE)
    return _out(lines)


def _render_show(
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    root: str | None,
) -> str:
    del errors, root
    lines: list[str] = []
    for item in results:
        lines.append(f"entry_id: {item.get('entry_id')}")
        lines.append(f"state: {item.get('state')}")
        creation = item.get("creation")
        if isinstance(creation, Mapping):
            lines.append(f"original_path: {creation.get('original_path')}")
            lines.append(f"trashed_path: {creation.get('trashed_path')}")
            lines.append(f"kind: {creation.get('kind')}")
            for field_name in ("project", "session_id", "reason", "agent", "tool"):
                if creation.get(field_name) is not None:
                    lines.append(f"{field_name}: {creation.get(field_name)}")
            if creation.get("extensions") is not None:
                lines.append(f"extensions: {_encode(creation['extensions'])}")
        events = item.get("events")
        if isinstance(events, Sequence) and events:
            lines.append(f"events: {len(events)}")
            for index, event in enumerate(events, start=1):
                if not isinstance(event, Mapping):
                    lines.append(f"  {index}. {_encode(event)}")
                    continue
                lines.append(
                    f"  {index}. {event.get('operation')}  {event.get('timestamp')}  "
                    f"state={event.get('state')}"
                )
        if item.get("state") in _RESTORE_STATES or _has_restore_event(events):
            lines.append(RESTORE_RESIDUAL_NOTE)
    return _out(lines)


def _has_restore_event(events: Any) -> bool:
    if not isinstance(events, Sequence):
        return False
    return any(
        isinstance(event, Mapping) and event.get("operation") == "restore"
        for event in events
    )


def _render_doctor(
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    root: str | None,
) -> str:
    del errors, root
    lines: list[str] = []
    for report in results:
        if not isinstance(report, Mapping):
            lines.append(_encode(report))
            continue
        preflight = report.get("platform_preflight")
        if isinstance(preflight, Mapping):
            missing = preflight.get("missing_primitives") or []
            state = "passed" if preflight.get("passed") else "failed"
            lines.append(f"platform preflight: {preflight.get('required')} — {state}")
            if missing:
                lines.append(f"  missing primitives: {', '.join(str(item) for item in missing)}")
        storage = report.get("storage")
        if isinstance(storage, Mapping):
            lines.append(
                f"storage: root={storage.get('root')} usable={bool(storage.get('usable'))}"
            )
            if storage.get("reason_code"):
                lines.append(f"  reason: {storage.get('reason_code')}")
        lines.append("boundaries:")
        for status in report.get("boundaries") or []:
            if not isinstance(status, Mapping):
                lines.append(f"  {_encode(status)}")
                continue
            lines.append(
                f"  {status.get('selector')}: installed={bool(status.get('installed'))} "
                f"enforced={bool(status.get('enforced'))} enabled={bool(status.get('enabled'))}"
            )
            boundary = status.get("boundary")
            if isinstance(boundary, Mapping):
                if boundary.get("config_path") is not None:
                    lines.append(f"    config_path: {boundary.get('config_path')}")
                if boundary.get("shim_dir") is not None:
                    lines.append(f"    shim_dir: {boundary.get('shim_dir')}")
                    lines.append(f"    prepend_path: {boundary.get('prepend_path')}")
            warning = status.get("warning")
            lines.append(f"    warning: {warning if warning else '(none)'}")
        artifacts = report.get("artifacts") or []
        if artifacts:
            lines.append("artifacts:")
            for artifact in artifacts:
                if not isinstance(artifact, Mapping):
                    lines.append(f"  {_encode(artifact)}")
                    continue
                lines.append(
                    f"  {artifact.get('path')}  payload_source={artifact.get('payload_source')}  "
                    f"payload_source_exists={bool(artifact.get('payload_source_exists'))}  "
                    f"git_checkout={artifact.get('git_checkout')}"
                )
        else:
            lines.append("artifacts: (none)")
        cli = report.get("cli")
        if isinstance(cli, Mapping):
            paths = ", ".join(str(item) for item in cli.get("paths") or []) or "(none)"
            lines.append(f"cli paths: {paths}")
            loose = cli.get("world_writable") or []
            if loose:
                lines.append(f"world-writable cli: {', '.join(str(item) for item in loose)}")
        problems = report.get("problems") or []
        if problems:
            lines.append("problems:")
            lines.extend(f"  - {problem}" for problem in problems)
        else:
            lines.append("problems: (none detected)")
        lines.append(DOCTOR_READ_ONLY_STATEMENT)
        lines.append(DOCTOR_HONEST_FOOTER)
    lines.append(RESTORE_RESIDUAL_NOTE)
    return _out(lines)


def _render_restore(
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    root: str | None,
) -> str:
    del errors, root
    lines: list[str] = []
    for item in results:
        lines.append(f"entry_id: {item.get('entry_id')}")
        lines.append(f"state: {item.get('state')}")
        if item.get("code"):
            lines.append(f"code: {item.get('code')}")
        lines.append(f"original_path: {item.get('original_path')}")
        if item.get("restore_path") is not None:
            lines.append(f"restore_path: {item.get('restore_path')}")
        if item.get("kind") is not None:
            lines.append(f"kind: {item.get('kind')}")
    lines.append(RESTORE_RESIDUAL_NOTE)
    return _out(lines)


def _render_purge_report(item: Mapping[str, Any], *, nothing_removed: str) -> list[str]:
    lines = [f"mode: {item.get('mode')}"]
    policy = item.get("policy")
    if isinstance(policy, Mapping):
        lines.append(
            f"policy: source={policy.get('source')} as_of={policy.get('as_of')} "
            f"cutoff={policy.get('cutoff')}"
        )
    decisions = list(item.get("decisions") or [])
    candidates = list(item.get("candidates") or [])
    lines.append(f"decisions: {len(decisions)}")
    lines.append(f"candidates: {len(candidates)}")
    lines.extend(f"  - {entry_id}" for entry_id in candidates)
    warning = item.get("warning")
    if warning:
        lines.append(f"warning: {warning}")
    if item.get("dry_run") or item.get("mode") == "preview":
        lines.append(nothing_removed)
    if item.get("confirm_token"):
        lines.append(f"confirm_token: {item.get('confirm_token')}")
    outcomes = item.get("outcomes") or []
    if outcomes:
        lines.append("outcomes:")
        for outcome in outcomes:
            if isinstance(outcome, Mapping):
                lines.append(
                    f"  {outcome.get('entry_id')}  {outcome.get('outcome')}  "
                    f"state={outcome.get('state')}"
                )
    return lines


def _render_purge(
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    root: str | None,
) -> str:
    del errors
    lines = [_root_line(root)]
    for item in results:
        if isinstance(item, Mapping):
            lines.extend(_render_purge_report(item, nothing_removed=PURGE_PREVIEW_NOTHING_REMOVED))
        else:
            lines.append(_encode(item))
    return _out(lines)


def _render_hook_status(
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    root: str | None,
) -> str:
    del errors, root
    lines: list[str] = []
    for status in results:
        if not isinstance(status, Mapping):
            lines.append(_encode(status))
            continue
        lines.append(
            f"{status.get('selector')}: installed={bool(status.get('installed'))} "
            f"enforced={bool(status.get('enforced'))}"
        )
        boundary = status.get("boundary")
        if isinstance(boundary, Mapping):
            if boundary.get("config_path") is not None:
                lines.append(f"  config_path: {boundary.get('config_path')}")
            if boundary.get("shim_dir") is not None:
                lines.append(f"  shim_dir: {boundary.get('shim_dir')}")
                lines.append(f"  prepend_path: {boundary.get('prepend_path')}")
        warning = status.get("warning")
        lines.append(f"  warning: {warning if warning else '(none)'}")
    return _out(lines)


def _render_hook_install(
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    root: str | None,
) -> str:
    del errors, root
    lines: list[str] = []
    for item in results:
        if not isinstance(item, Mapping):
            lines.append(_encode(item))
            continue
        lines.append(f"selector: {item.get('selector')}")
        boundary = item.get("boundary")
        if isinstance(boundary, Mapping) and boundary.get("config_path") is not None:
            lines.append(f"config_path: {boundary.get('config_path')}")
        if isinstance(boundary, Mapping) and boundary.get("shim_dir") is not None:
            lines.append(f"shim_dir: {boundary.get('shim_dir')}")
        lines.append(f"installed: {bool(item.get('installed'))}")
        lines.append(f"enforced: {bool(item.get('enforced'))}")
        lines.append(f"changed: {bool(item.get('changed'))}")
        warnings = list(item.get("install_warnings") or [])
        if warnings:
            lines.append("install_warnings:")
            lines.extend(f"  - {warning}" for warning in warnings)
        else:
            lines.append("install_warnings: (none)")
        if item.get("path_activation"):
            lines.append(f"path_activation: {item.get('path_activation')}")
            lines.append(PATH_ACTIVATION_IS_OPERATOR_OWNED)
    return _out(lines)


def _render_hook_management(
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    root: str | None,
) -> str:
    del errors, root
    lines: list[str] = []
    for item in results:
        if not isinstance(item, Mapping):
            lines.append(_encode(item))
            continue
        lines.append(f"{item.get('selector')}: installed={bool(item.get('installed'))} changed={bool(item.get('changed'))}")
        if item.get("raw_delete_outside_boundary"):
            lines.append("  raw deletion at this boundary is outside the configured scope")
        warning = item.get("warning")
        lines.append(f"  warning: {warning if warning else '(none)'}")
    return _out(lines)


def _render_setup(
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    root: str | None,
) -> str:
    """Render the ``setup`` summary: install, boundary, doctor problems, steps."""

    del errors, root
    lines: list[str] = []
    for item in results:
        if not isinstance(item, Mapping):
            lines.append(_encode(item))
            continue
        selector = item.get("selector")
        lines.append(
            "selector: " + (str(selector) if selector else "(none — read-only report)")
        )
        preflight = item.get("preflight")
        if isinstance(preflight, Mapping):
            state = "passed" if preflight.get("supported") else "failed"
            lines.append(f"platform preflight: {preflight.get('requires')} — {state}")
            missing = preflight.get("missing_primitives") or []
            if missing:
                lines.append(
                    "  missing primitives: " + ", ".join(str(name) for name in missing)
                )
        initialized = item.get("initialized")
        if isinstance(initialized, Mapping):
            lines.append(f"initialized: {initialized.get('root')}")
        install = item.get("install")
        if isinstance(install, Mapping):
            boundary = install.get("boundary")
            boundary = boundary if isinstance(boundary, Mapping) else {}
            lines.append(f"installed: {bool(install.get('installed'))}")
            lines.append(f"enforced: {bool(install.get('enforced'))}")
            lines.append(f"changed: {bool(install.get('changed'))}")
            if boundary.get("config_path") is not None:
                lines.append(f"config_path: {boundary.get('config_path')}")
            if boundary.get("shim_dir") is not None:
                lines.append(f"shim_dir: {boundary.get('shim_dir')}")
                lines.append(f"prepend_path: {boundary.get('prepend_path')}")
            warnings = list(install.get("install_warnings") or [])
            if warnings:
                lines.append("install_warnings:")
                lines.extend(f"  - {warning}" for warning in warnings)
            else:
                lines.append("install_warnings: (none)")
            if install.get("path_activation"):
                lines.append(f"path_activation: {install.get('path_activation')}")
                lines.append(PATH_ACTIVATION_IS_OPERATOR_OWNED)
            lines.append(SETUP_INSTALL_IS_NOT_ENFORCEMENT)
        else:
            lines.append("installed: nothing (this was a read-only report)")
        doctor = item.get("doctor")
        if isinstance(doctor, Mapping):
            for status in doctor.get("boundaries") or []:
                if not isinstance(status, Mapping):
                    continue
                lines.append(
                    f"boundary: {status.get('selector')} "
                    f"installed={bool(status.get('installed'))} "
                    f"enforced={bool(status.get('enforced'))}"
                )
            problems = list(doctor.get("problems") or [])
            if problems:
                lines.append("doctor problems:")
                lines.extend(f"  - {problem}" for problem in problems)
            else:
                lines.append("doctor problems: (none detected)")
            if doctor.get("needs_attention"):
                lines.append("needs_attention: true — see the doctor problems above")
            else:
                lines.append(DOCTOR_HONEST_FOOTER)
        steps = list(item.get("next_steps") or ())
        if steps:
            lines.append("next_steps:")
            lines.extend(f"  - {step}" for step in steps)
    return _out(lines)


def _render_init(
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    root: str | None,
) -> str:
    del errors, root
    return _out(_render_generic_lines(results))


def _render_add(
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    root: str | None,
) -> str:
    del errors, root
    lines: list[str] = []
    for item in results:
        if not isinstance(item, Mapping):
            lines.append(_encode(item))
            continue
        if item.get("ok") is False:
            detail = item.get("error")
            code = detail.get("code") if isinstance(detail, Mapping) else None
            lines.append(f"{item.get('path')}  failed  code={code}")
            continue
        lines.append(
            f"{item.get('entry_id')}  {item.get('state') or 'dry_run'}  "
            f"{item.get('original_path')}"
        )
    return _out(lines)


def _render_generic_lines(results: Sequence[Any]) -> list[str]:
    lines: list[str] = []
    for item in results:
        if isinstance(item, Mapping):
            lines.extend(f"{key}: {_encode(value)}" for key, value in item.items())
        else:
            lines.append(_encode(item))
    return lines


def _render_generic(
    results: Sequence[Any],
    errors: Sequence[Mapping[str, Any]],
    root: str | None,
) -> str:
    del errors, root
    return _out(_render_generic_lines(results))


_RENDERERS = {
    "list": _render_list,
    "show": _render_show,
    "doctor": _render_doctor,
    "restore": _render_restore,
    "purge": _render_purge,
    "hook status": _render_hook_status,
    "hook install": _render_hook_install,
    "hook disable": _render_hook_management,
    "hook uninstall": _render_hook_management,
    "init": _render_init,
    "add": _render_add,
    "setup": _render_setup,
}
