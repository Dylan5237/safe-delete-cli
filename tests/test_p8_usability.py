"""P8 usability contract gates P8-1 … P8-8 (Issue #24).

Every gate replays the freeze's commands against a disposable ``HOME`` and a
fresh storage root outside the checkout, with ages set by rewriting ledger
timestamps rather than by waiting on the wall clock.  Human/PTY assertions use
a real PTY; the non-TTY invariant is asserted byte-for-byte.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pty
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from safe_delete.errors import ERROR_EXIT_CATEGORIES, SafeDeleteError, exit_code_for
from safe_delete.hook import OUT_OF_COVERAGE_BYPASSES
from safe_delete.purge import empty_confirm_token

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CLI = REPOSITORY_ROOT / "safe-delete"
SKILL = REPOSITORY_ROOT / "skills" / "safe-delete" / "SKILL.md"

RESIDUAL_NOTE = (
    "Exception #12 — P2-only same-UID staging publication — excluded model / "
    "residual risk; not fixed"
)
WIPE_ALL_WARNING = (
    "cutoff is not in the past: every active entry is eligible (wipe-all "
    "semantics); read candidates before extending this invocation with "
    "--execute --yes"
)
PURGE_SENTINEL = "Never append --execute --yes as a default or habit."
AGED = "2024-01-01T00:00:00Z"
PAST_CUTOFF = "2025-01-01T00:00:00Z"


class P8Harness(unittest.TestCase):
    """Disposable HOME, workspace, project, and storage root per test."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="safe-delete-p8-")
        self.base = Path(self.temp_dir.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self.project_a = self.base / "project-a"
        self.project_b = self.base / "project-b"
        self.project_a.mkdir()
        self.project_b.mkdir()
        self.storage = self.base / "storage"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def environment(self) -> dict[str, str]:
        child = os.environ.copy()
        child["HOME"] = str(self.home)
        child["XDG_DATA_HOME"] = str(self.home / ".local" / "share")
        child["XDG_CONFIG_HOME"] = str(self.home / ".config")
        child["SAFE_DELETE_ROOT"] = str(self.storage)
        child.pop("SAFE_DELETE_RETENTION_DAYS", None)
        return child

    def run_cli(
        self,
        *arguments: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        root: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        child_env = self.environment()
        if env:
            child_env.update(env)
        return subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--root",
                str(self.storage if root is None else root),
                *arguments,
            ],
            cwd=REPOSITORY_ROOT if cwd is None else cwd,
            text=True,
            capture_output=True,
            env=child_env,
            check=False,
        )

    def run_json(self, *arguments: str, cwd: Path | None = None) -> tuple[int, dict, str]:
        completed = self.run_cli("--json", *arguments, cwd=cwd)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic guard
            raise AssertionError(
                f"CLI did not emit JSON\nstdout={completed.stdout!r}\nstderr={completed.stderr!r}"
            ) from exc
        return completed.returncode, payload, completed.stderr

    # -- fixtures ---------------------------------------------------------

    def init_storage(self) -> None:
        code, payload, _ = self.run_json("init")
        self.assertEqual(code, 0, payload)

    def add_file(self, name: str) -> tuple[str, Path]:
        source = self.workspace / name
        source.write_text(name, encoding="utf-8")
        code, payload, _ = self.run_json("add", "--", str(source))
        self.assertEqual(code, 0, payload)
        result = payload["results"][0]
        return str(result["entry_id"]), Path(str(result["trashed_path"]))

    def add_aged_file(self, name: str) -> tuple[str, Path]:
        entry_id, payload_path = self.add_file(name)
        self.set_creation_timestamp(entry_id, AGED)
        return entry_id, payload_path

    def ledger_bytes(self) -> bytes:
        return (self.storage / "ledger.jsonl").read_bytes()

    def add_records(self) -> list[dict]:
        return [
            json.loads(line)
            for line in self.ledger_bytes().decode("utf-8").splitlines()
            if line.strip()
        ]

    def set_creation_timestamp(self, entry_id: str, timestamp: str) -> None:
        records = self.add_records()
        for record in records:
            if record["entry_id"] == entry_id and record["operation"] == "trash":
                record["timestamp"] = timestamp
                break
        else:  # pragma: no cover - fixture misuse
            self.fail(f"missing creation record for {entry_id}")
        (self.storage / "ledger.jsonl").write_text(
            "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
            encoding="utf-8",
        )

    def snapshot_root(self) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for path in sorted(self.storage.rglob("*")):
            if path.is_file() and not path.is_symlink():
                info = path.lstat()
                snapshot[str(path.relative_to(self.storage))] = (info.st_size, info.st_mtime_ns)
        return snapshot

    def run_pty(self, *arguments: str, cwd: Path | None = None) -> tuple[int, str]:
        """Run the CLI with stdout attached to a real PTY."""

        child_env = self.environment()
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(CLI),
                    "--root",
                    str(self.storage),
                    *arguments,
                ],
                cwd=REPOSITORY_ROOT if cwd is None else cwd,
                stdin=subprocess.DEVNULL,
                stdout=slave,
                stderr=subprocess.DEVNULL,
                text=True,
                env=child_env,
            )
        finally:
            os.close(slave)
        chunks: list[bytes] = []
        try:
            while True:
                try:
                    chunk = os.read(master, 4096)
                except OSError:  # pragma: no cover - PTY closed by the child
                    break
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            os.close(master)
        return process.wait(), b"".join(chunks).decode("utf-8", errors="replace")


class P8_1_SetupOneShotTests(P8Harness):
    """Gate P8-1 — `setup` one-shot install plus read-only report."""

    def test_setup_claude_init_reports_the_unmodified_install_and_doctor(self) -> None:
        code, payload, stderr = self.run_json("setup", "claude", "--init")
        self.assertEqual(code, 0, (payload, stderr))
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["command"], "setup")
        report = payload["results"][0]
        self.assertEqual(report["selector"], "claude")
        self.assertEqual(report["initialized"]["root"], str(self.storage))
        self.assertTrue((self.storage / "ledger.jsonl").is_file())

        install = report["install"]
        self.assertNotIn("ok", install, "the envelope owns `ok`; install must not add one")
        # The install result is the unmodified P7 object: required keys present,
        # and no key outside the frozen set plus the two selector-dependent ones.
        required = {
            "selector",
            "mode",
            "cli_path",
            "boundary",
            "installed",
            "enforced",
            "enabled",
            "changed",
            "config_created",
            "package",
            "registry_valid",
            "out_of_coverage",
            "install_warnings",
            "storage",
        }
        self.assertLessEqual(required, set(install))
        self.assertLessEqual(set(install), required | {"path_activation", "warning"})
        self.assertTrue(install["installed"])
        self.assertTrue(install["enforced"])
        self.assertTrue(install["changed"])
        self.assertEqual(install["selector"], "claude")
        self.assertEqual(install["out_of_coverage"], list(OUT_OF_COVERAGE_BYPASSES))

        doctor = report["doctor"]
        self.assertTrue(doctor["read_only"])
        self.assertEqual(
            [item["selector"] for item in doctor["boundaries"]],
            ["claude", "cursor", "path-shim", "workbuddy"],
        )
        self.assertEqual(doctor["restore"]["residual_note"], RESIDUAL_NOTE)
        self.assertTrue(report["next_steps"])

        # No success wording may be promoted into a coverage claim.
        rendered = json.dumps(payload)
        self.assertNotIn("protected", rendered)
        self.assertNotIn("safe to delete", rendered)

    def test_setup_cursor_succeeds_from_the_intended_project(self) -> None:
        self.init_storage()
        code, payload, stderr = self.run_json("setup", "cursor", cwd=self.project_a)
        self.assertEqual(code, 0, (payload, stderr))
        self.assertTrue(payload["ok"], payload)
        report = payload["results"][0]
        self.assertEqual(report["selector"], "cursor")
        config_path = str(self.project_a / ".cursor" / "hooks.json")
        self.assertEqual(report["install"]["boundary"]["config_path"], config_path)
        self.assertTrue(report["install"]["installed"])
        self.assertTrue(report["install"]["changed"])
        # The human summary names the boundary the install wrote.
        human = self.run_cli("--human", "setup", "cursor", cwd=self.project_a)
        self.assertEqual(human.returncode, 0, human)
        self.assertIn(f"config_path: {config_path}", human.stdout)
        self.assertIn("an installed integration is not an enforced one", human.stdout)

    def test_setup_without_a_selector_is_a_read_only_report(self) -> None:
        code, payload, _ = self.run_json("setup")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"], payload)
        report = payload["results"][0]
        self.assertIsNone(report["selector"])
        self.assertIsNone(report["install"])
        self.assertFalse(self.storage.exists(), "a read-only setup must create nothing")
        self.assertTrue(report["doctor"]["read_only"])
        self.assertEqual(
            [item["selector"] for item in report["doctor"]["boundaries"]],
            ["claude", "cursor", "path-shim", "workbuddy"],
        )
        self.assertFalse(any(item["installed"] for item in report["doctor"]["boundaries"]))


class P8_2_SetupFailClosedTests(P8Harness):
    """Gate P8-2 — fail-closed install, guidance, --init opt-in, preflight."""

    def test_second_cursor_project_fails_closed_with_recorded_and_resolved_paths(self) -> None:
        self.init_storage()
        first, _, _ = self.run_json("setup", "cursor", cwd=self.project_a)
        self.assertEqual(first, 0)

        recorded = str(self.project_a / ".cursor" / "hooks.json")
        resolved = str(self.project_b / ".cursor" / "hooks.json")

        code, payload, _ = self.run_json("setup", "cursor", cwd=self.project_b)
        self.assertEqual(code, 4, payload)
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["errors"][0]["code"], "storage_failure")
        details = payload["errors"][0]
        self.assertEqual(details["recorded_config_path"], recorded)
        self.assertEqual(details["resolved_config_path"], resolved)
        self.assertEqual(
            details["next_steps"],
            [
                "safe-delete hook uninstall cursor   # from the recorded project",
                "safe-delete setup cursor   # from the project you meant to protect",
            ],
        )

        human = self.run_cli("--human", "setup", "cursor", cwd=self.project_b)
        self.assertEqual(human.returncode, 4, human)
        self.assertIn(f"recorded config: {recorded}", human.stderr)
        self.assertIn(f"resolved config: {resolved}", human.stderr)
        self.assertIn("safe-delete hook uninstall cursor", human.stderr)
        self.assertIn("safe-delete setup cursor", human.stderr)
        # Guidance is a translation, never a silent retarget: project A keeps
        # its boundary and project B gains nothing.
        self.assertFalse((self.project_b / ".cursor" / "hooks.json").exists())
        _, status, _ = self.run_json("hook", "status", "cursor", cwd=self.project_a)
        self.assertTrue(status["results"][0]["installed"])
        self.assertEqual(
            status["results"][0]["boundary"]["config_path"], recorded
        )

    def test_setup_without_init_never_creates_a_root_and_names_init(self) -> None:
        code, payload, stderr = self.run_json("setup", "claude", cwd=self.project_a)
        self.assertEqual(code, 0, (payload, stderr))
        self.assertFalse(self.storage.exists(), "--init is the only root-creating path")
        report = payload["results"][0]
        self.assertIn("safe-delete init", " ".join(report["next_steps"]))
        self.assertIsNone(report["initialized"])

    def test_install_flags_without_a_selector_are_usage_errors(self) -> None:
        code, payload, _ = self.run_json("setup", "--project", str(self.project_a))
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["errors"][0]["code"], "usage_error")

    def test_unknown_selector_is_unsupported_command(self) -> None:
        code, payload, _ = self.run_json("setup", "not-a-host")
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["errors"][0]["code"], "unsupported_command")

    def test_simulated_platform_failure_installs_nothing(self) -> None:
        import safe_delete.cli as cli
        from safe_delete import platform_check

        stderr = io.StringIO()
        stdout = io.StringIO()
        with patch.object(
            platform_check, "missing_posix_primitives", return_value=["fcntl"]
        ), redirect_stdout(stdout):
            previous = sys.stderr
            sys.stderr = stderr
            try:
                code = cli.main(["setup", "claude", "--root", str(self.storage)])
            finally:
                sys.stderr = previous
        self.assertEqual(code, 2)
        self.assertEqual(
            stderr.getvalue(),
            "unsupported platform: requires Linux/macOS/WSL (fcntl)\n",
        )
        self.assertFalse((self.home / ".local" / "share" / "safe-delete").exists())
        self.assertFalse(self.storage.exists())


class P8_3_EmptyPreviewTests(P8Harness):
    """Gate P8-3 — both preview forms are inert and report the frozen fields."""

    def setUp(self) -> None:
        super().setUp()
        self.init_storage()
        self.aged_id, self.aged_payload = self.add_aged_file("aged.txt")
        self.young_id, self.young_payload = self.add_file("young.txt")

    def ledger_and_payload_bytes(self) -> tuple[bytes, bytes, bytes]:
        return (
            self.ledger_bytes(),
            self.aged_payload.read_bytes(),
            self.young_payload.read_bytes(),
        )

    def test_wipe_all_preview_reports_both_candidates_and_the_warning(self) -> None:
        before = self.ledger_and_payload_bytes()
        code, payload, _ = self.run_json("empty")
        self.assertEqual(code, 0, payload)
        report = payload["results"][0]
        self.assertEqual(report["mode"], "preview")
        self.assertEqual(report["policy"]["source"], "before_now")
        self.assertEqual(sorted(report["candidates"]), sorted([self.aged_id, self.young_id]))
        self.assertEqual(report["warning"], WIPE_ALL_WARNING)
        self.assertEqual(len(report["confirm_token"]), 16)
        self.assertEqual(report["confirm_token"], report["confirm_token"].lower())
        self.assertRegex(report["confirm_token"], r"^[0-9a-f]{16}$")
        self.assertEqual(report["decisions"][0]["state"], "active")
        self.assertEqual(self.ledger_and_payload_bytes(), before)

    def test_selective_preview_omits_the_warning_and_the_young_entry(self) -> None:
        before = self.ledger_and_payload_bytes()
        code, payload, _ = self.run_json("empty", "--before", PAST_CUTOFF)
        self.assertEqual(code, 0, payload)
        report = payload["results"][0]
        self.assertEqual(report["mode"], "preview")
        self.assertEqual(report["policy"]["source"], "before")
        self.assertEqual(report["candidates"], [self.aged_id])
        self.assertNotIn("warning", report)
        self.assertRegex(report["confirm_token"], r"^[0-9a-f]{16}$")
        reasons = {item["entry_id"]: item["decision"] for item in report["decisions"]}
        self.assertEqual(reasons[self.aged_id], "candidate")
        self.assertEqual(reasons[self.young_id], "excluded")
        self.assertEqual(self.ledger_and_payload_bytes(), before)

    def test_empty_token_recipe_is_root_and_candidate_set_only(self) -> None:
        _, payload, _ = self.run_json("empty", "--before", PAST_CUTOFF)
        token = payload["results"][0]["confirm_token"]
        recipe = "\n".join(
            ["safe-delete/empty/v1", os.path.realpath(self.storage), self.aged_id]
        )
        self.assertEqual(
            hashlib.sha256(recipe.encode("utf-8")).hexdigest()[:16],
            token,
        )


class P8_4_EmptyConfirmTests(P8Harness):
    """Gate P8-4 — confirm executes exactly the previewed set."""

    def setUp(self) -> None:
        super().setUp()
        self.init_storage()
        self.aged_id, self.aged_payload = self.add_aged_file("aged.txt")
        self.young_id, self.young_payload = self.add_file("young.txt")

    def test_selective_confirm_removes_only_the_aged_candidate(self) -> None:
        _, preview, _ = self.run_json("empty", "--before", PAST_CUTOFF)
        token = preview["results"][0]["confirm_token"]
        code, payload, _ = self.run_json(
            "empty", "--confirm", token, "--before", PAST_CUTOFF
        )
        self.assertEqual(code, 0, payload)
        report = payload["results"][0]
        self.assertEqual(report["mode"], "execute")
        outcomes = {item["entry_id"]: item["outcome"] for item in report["outcomes"]}
        self.assertEqual(outcomes[self.aged_id], "purged")
        self.assertFalse(self.aged_payload.exists())
        self.assertTrue(self.young_payload.is_file())
        self.assertEqual(
            [record["operation"] for record in self.add_records()
             if record["entry_id"] == self.aged_id],
            ["trash", "purge_intent", "purge_complete"],
        )
        again_code, again, _ = self.run_json("empty", "--before", PAST_CUTOFF)
        self.assertEqual(again_code, 0, again)
        self.assertEqual(again["results"][0]["candidates"], [])

    def test_default_confirm_round_trips_despite_the_clock_derived_cutoff(self) -> None:
        _, preview, _ = self.run_json("empty")
        token = preview["results"][0]["confirm_token"]
        code, payload, _ = self.run_json("empty", "--confirm", token)
        self.assertEqual(code, 0, payload)
        report = payload["results"][0]
        self.assertEqual(report["mode"], "execute")
        self.assertEqual(
            sorted(item["entry_id"] for item in report["outcomes"]),
            sorted([self.aged_id, self.young_id]),
        )
        self.assertFalse(self.aged_payload.exists())
        self.assertFalse(self.young_payload.exists())

    def test_confirm_rejects_execute_yes_and_dry_run_flags(self) -> None:
        self.assertEqual(self.run_json("empty", "--execute")[0], 2)
        self.assertEqual(self.run_json("empty", "--yes")[0], 2)
        self.assertEqual(self.run_json("empty", "--dry-run")[0], 2)
        code, payload, _ = self.run_json("empty", "--confirm")
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["errors"][0]["code"], "usage_error")
        self.assertTrue(self.aged_payload.is_file())

    def test_empty_uses_the_frozen_engine_event_pair(self) -> None:
        _, preview, _ = self.run_json("empty")
        token = preview["results"][0]["confirm_token"]
        self.assertEqual(self.run_json("empty", "--confirm", token)[0], 0)
        operations = [record["operation"] for record in self.add_records()]
        self.assertEqual(operations.count("purge_intent"), 2)
        self.assertEqual(operations.count("purge_complete"), 2)
        self.assertNotIn("empty_intent", operations)


class P8_5_EmptyFailClosedTests(P8Harness):
    """Gate P8-5 — staleness, audit failure, and partial failure."""

    def setUp(self) -> None:
        super().setUp()
        self.init_storage()

    def test_stale_token_is_rejected_without_mutation(self) -> None:
        self.add_aged_file("aged.txt")
        _, preview, _ = self.run_json("empty")
        token = preview["results"][0]["confirm_token"]
        self.add_file("newcomer.txt")
        ledger_before = self.ledger_bytes()
        code, payload, _ = self.run_json("empty", "--confirm", token)
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["errors"][0]["code"], "usage_error")
        self.assertIn("nothing was removed", payload["errors"][0]["message"])
        self.assertEqual(self.ledger_bytes(), ledger_before)
        self.assertNotIn(b'"operation":"purge_intent"', ledger_before)

    def test_stale_token_under_older_than_fails_closed_on_set_drift(self) -> None:
        self.add_aged_file("aged.txt")
        _, preview, _ = self.run_json("empty", "--older-than", "30d")
        token = preview["results"][0]["confirm_token"]
        self.add_aged_file("aged-two.txt")
        ledger_before = self.ledger_bytes()
        code, payload, _ = self.run_json(
            "empty", "--confirm", token, "--older-than", "30d"
        )
        self.assertEqual(code, 2, payload)
        self.assertEqual(self.ledger_bytes(), ledger_before)

    def test_wrong_and_malformed_tokens_are_rejected_identically(self) -> None:
        self.add_aged_file("aged.txt")
        ledger_before = self.ledger_bytes()
        for token in ("deadbeefdeadbeef", "not-a-token", "0" * 16, ""):
            with self.subTest(token=token):
                if token == "":
                    code, payload, _ = self.run_json("empty", "--confirm")
                    self.assertEqual(code, 2, payload)
                else:
                    code, payload, _ = self.run_json("empty", "--confirm", token)
                    self.assertEqual(code, 2, payload)
                self.assertEqual(payload["errors"][0]["code"], "usage_error")
        self.assertEqual(self.ledger_bytes(), ledger_before)

    def test_audit_corruption_fails_the_whole_command_closed(self) -> None:
        self.add_aged_file("aged.txt")
        _, preview, _ = self.run_json("empty")
        token = preview["results"][0]["confirm_token"]
        with (self.storage / "ledger.jsonl").open("a", encoding="utf-8") as ledger:
            ledger.write("{not-json\n")
        ledger_before = self.ledger_bytes()
        code, payload, _ = self.run_json("empty", "--confirm", token)
        self.assertEqual(code, 4, payload)
        self.assertEqual(self.ledger_bytes(), ledger_before)
        self.assertNotIn(b'"operation":"purge_intent"', ledger_before)

    def test_removal_failure_is_partial_failure_and_keeps_the_payload(self) -> None:
        import safe_delete.cli as cli
        import safe_delete.purge as purge

        failed_id, failed_payload = self.add_aged_file("failed.txt")
        other_id, other_payload = self.add_aged_file("other.txt")
        _, preview, _ = self.run_json("empty")
        token = preview["results"][0]["confirm_token"]
        self.assertEqual(
            token,
            empty_confirm_token(self.storage, sorted([failed_id, other_id])),
        )

        real_remove = purge.remove_payload

        def fail_one(layout: object, entry: object) -> None:
            if getattr(entry, "entry_id") == failed_id:
                raise SafeDeleteError("storage_failure", "injected removal failure")
            real_remove(layout, entry)

        args = Namespace(
            root=str(self.storage),
            older_than=None,
            before=None,
            confirm=token,
            execute=False,
            yes=False,
            dry_run=False,
        )
        with patch.object(purge, "remove_payload", side_effect=fail_one):
            results, errors = cli._handle_empty(args)
        self.assertEqual([item.code for item in errors], ["purge_remove_failed", "partial_failure"])
        self.assertEqual(exit_code_for(errors), 5)
        outcomes = {item["entry_id"]: item for item in results[0]["outcomes"]}
        self.assertEqual(outcomes[failed_id]["state"], "active")
        self.assertEqual(outcomes[failed_id]["error_code"], "purge_remove_failed")
        self.assertEqual(outcomes[other_id]["state"], "purged")
        self.assertTrue(failed_payload.is_file())
        self.assertFalse(other_payload.exists())
        self.assertEqual(
            [record["operation"] for record in self.add_records()
             if record["entry_id"] == failed_id],
            ["trash", "purge_intent", "purge_failed"],
        )


class P8_6_OutputModeTests(P8Harness):
    """Gate P8-6 — human default on a TTY, JSON byte-identical off it."""

    def setUp(self) -> None:
        super().setUp()
        self.init_storage()
        self.entry_id, self.payload = self.add_file("subject.txt")

    def test_pty_prints_human_text_for_the_named_commands(self) -> None:
        code, text = self.run_pty("list")
        self.assertEqual(code, 0, text)
        self.assertIn(self.entry_id, text)
        self.assertIn(str(self.workspace / "subject.txt"), text)
        self.assertIn("root:", text)
        self.assertIn("active:", text)

        code, text = self.run_pty("doctor")
        self.assertEqual(code, 0, text)
        self.assertIn("platform preflight:", text)
        self.assertIn("boundaries:", text)
        self.assertIn("problems:", text)
        self.assertIn(RESIDUAL_NOTE, text)
        self.assertIn("not a coverage claim", text)

        code, text = self.run_pty("show", self.entry_id)
        self.assertEqual(code, 0, text)
        self.assertIn(f"entry_id: {self.entry_id}", text)
        self.assertIn("events:", text)

        code, text = self.run_pty("restore", self.entry_id)
        self.assertEqual(code, 0, text)
        self.assertIn("state: restored", text)
        self.assertIn(RESIDUAL_NOTE, text)

        code, text = self.run_pty("purge")
        self.assertEqual(code, 0, text)
        self.assertIn("mode:", text)
        self.assertIn("nothing was removed", text)

        code, text = self.run_pty("hook", "status")
        self.assertEqual(code, 0, text)
        self.assertIn("claude:", text)
        self.assertIn("warning:", text)

    def test_pty_human_list_shows_restore_state_disclosure(self) -> None:
        code, text = self.run_pty("list", "--all")
        self.assertEqual(code, 0, text)
        self.assertNotIn(RESIDUAL_NOTE, text)
        self.assertEqual(self.run_json("restore", self.entry_id)[0], 0)
        code, text = self.run_pty("list", "--all")
        self.assertEqual(code, 0, text)
        self.assertIn("restored", text)
        self.assertIn(RESIDUAL_NOTE, text)

    def test_json_on_a_pty_stays_json(self) -> None:
        code, text = self.run_pty("list", "--json")
        self.assertEqual(code, 0, text)
        payload = json.loads(text)
        self.assertEqual(payload["command"], "list")
        self.assertEqual(payload["results"][0]["entry_id"], self.entry_id)

    def test_pipe_default_is_byte_identical_to_json(self) -> None:
        for arguments in (
            ("list",),
            ("list", "--all"),
            ("doctor",),
            ("show", self.entry_id),
            ("hook", "status"),
            ("version",),
        ):
            with self.subTest(arguments=arguments):
                default = self.run_cli(*arguments)
                explicit = self.run_cli("--json", *arguments)
                self.assertEqual(default.stdout, explicit.stdout)
                self.assertEqual(default.returncode, explicit.returncode)

    def test_clock_derived_commands_are_byte_identical_off_a_tty(self) -> None:
        import datetime as _datetime

        import safe_delete.cli as cli

        frozen = _datetime.datetime(2026, 9, 21, 12, 0, 0, tzinfo=_datetime.timezone.utc)
        for arguments in (("purge",), ("empty",), ("purge", "--before", PAST_CUTOFF)):
            with self.subTest(arguments=arguments):
                outputs = []
                for extra in ((), ("--json",)):
                    stream = io.StringIO()
                    with patch("safe_delete.retention.utc_now", return_value=frozen), redirect_stdout(
                        stream
                    ):
                        final = cli.main(
                            ["--root", str(self.storage), *extra, *arguments]
                        )
                    outputs.append((final, stream.getvalue()))
                self.assertEqual(outputs[0], outputs[1])

    def test_json_and_human_together_are_usage_errors(self) -> None:
        completed = self.run_cli("--json", "--human", "list")
        self.assertEqual(completed.returncode, 2, completed)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["errors"][0]["code"], "usage_error")

    def test_human_audit_errors_stay_visible_and_nonzero(self) -> None:
        orphan = self.storage / "trash" / "objects" / str(uuid.uuid4()) / "payload"
        orphan.parent.mkdir()
        orphan.write_text("orphan", encoding="utf-8")
        completed = self.run_cli("--human", "list")
        self.assertEqual(completed.returncode, 4, completed)
        self.assertIn("orphan payloads: 1", completed.stdout)
        self.assertIn("orphan_payload", completed.stderr)

    def test_limit_reranks_but_absent_limit_leaves_baseline_order(self) -> None:
        second_id, _ = self.add_file("second.txt")
        baseline = self.run_json("list", "--all")[1]["results"]
        self.assertEqual(
            [item["entry_id"] for item in baseline], sorted([self.entry_id, second_id])
        )
        limited = self.run_json("list", "--all", "--limit", "1")[1]["results"]
        self.assertEqual([item["entry_id"] for item in limited], [second_id])
        for invalid in ("0", "-1", "1.5", "nope", ""):
            with self.subTest(limit=invalid):
                code, payload, _ = self.run_json("list", "--limit", invalid)
                self.assertEqual(code, 2, payload)
                self.assertEqual(payload["errors"][0]["code"], "usage_error")


class P8_7_NoContractDriftTests(P8Harness):
    """Gate P8-7 — the frozen machine contract is unchanged."""

    def setUp(self) -> None:
        super().setUp()
        self.init_storage()
        self.entry_id, self.payload = self.add_file("subject.txt")

    def test_error_code_vocabulary_and_categories_are_unchanged(self) -> None:
        self.assertEqual(
            ERROR_EXIT_CATEGORIES,
            {
                "usage_error": 2,
                "unsupported_command": 2,
                "source_not_found": 2,
                "unsupported_kind": 2,
                "unsupported_path_encoding": 2,
                "path_forbidden": 2,
                "cross_device": 2,
                "destination_exists": 3,
                "destination_parent_missing": 3,
                "entry_not_found": 3,
                "entry_not_restorable": 3,
                "already_restored": 0,
                "already_purged": 0,
                "entry_id_collision": 3,
                "unsupported_schema_version": 4,
                "malformed_ledger": 4,
                "duplicate_event_id": 4,
                "impossible_transition": 4,
                "payload_missing": 4,
                "orphan_payload": 4,
                "ledger_failure": 4,
                "storage_failure": 4,
                "rollback_failed": 4,
                "purge_remove_failed": 5,
                "partial_failure": 5,
            },
        )

    def test_purge_fail_closed_edges_are_unchanged(self) -> None:
        code, payload, _ = self.run_json("purge", "--execute")
        self.assertEqual(code, 2, payload)
        self.assertEqual(
            payload["errors"][0]["message"],
            "--execute requires --yes confirmation; no payloads were changed",
        )
        for arguments in (
            ("purge", "--older-than", "0d"),
            ("purge", "--before", "2020-01-01T00:00:00"),
            ("purge", "--older-than", "1d", "--before", "2020-01-01T00:00:00Z"),
            ("purge", "--dry-run", "--execute"),
        ):
            with self.subTest(arguments=arguments):
                code, payload, _ = self.run_json(*arguments)
                self.assertEqual(code, 2, payload)
                self.assertEqual(payload["errors"][0]["code"], "usage_error")
        self.assertTrue(self.payload.is_file())

    def test_bypass_inventory_is_verbatim_in_doctor_and_hook_status(self) -> None:
        _, doctor, _ = self.run_json("doctor")
        _, status, _ = self.run_json("hook", "status")
        self.assertEqual(doctor["results"][0]["out_of_coverage"], list(OUT_OF_COVERAGE_BYPASSES))
        for item in status["results"]:
            self.assertEqual(item["out_of_coverage"], list(OUT_OF_COVERAGE_BYPASSES))
        self.assertEqual(len(OUT_OF_COVERAGE_BYPASSES), 10)

    def test_read_only_commands_leave_every_root_byte_and_timestamp_alone(self) -> None:
        before = self.snapshot_root()
        ledger_before = self.ledger_bytes()
        for arguments in (
            ("doctor",),
            ("list",),
            ("list", "--all"),
            ("show", self.entry_id),
            ("purge",),
            ("empty",),
            ("hook", "status"),
            ("hook", "status", "claude"),
            ("version",),
        ):
            with self.subTest(arguments=arguments):
                self.run_json(*arguments)
        self.assertEqual(self.snapshot_root(), before)
        self.assertEqual(self.ledger_bytes(), ledger_before)

    def test_setup_json_keeps_the_frozen_envelope(self) -> None:
        code, payload, _ = self.run_json("setup")
        self.assertEqual(code, 0, payload)
        self.assertEqual(
            sorted(payload), ["command", "errors", "ok", "results"]
        )
        self.assertEqual(
            sorted(payload["results"][0]),
            ["doctor", "initialized", "install", "next_steps", "preflight", "selector"],
        )


class P8_8_SkillPackagingTests(unittest.TestCase):
    """Gate P8-8 — the packaged skill mirrors the shipped surface."""

    def setUp(self) -> None:
        self.text = SKILL.read_text(encoding="utf-8")

    def test_skill_lives_outside_the_methodology_snapshot_with_frontmatter(self) -> None:
        self.assertTrue(SKILL.is_file())
        self.assertNotIn(".agents/skills", str(SKILL))
        self.assertNotIn(".agent-project-ops", str(SKILL))
        self.assertTrue(self.text.startswith("---\n"))
        frontmatter = self.text.split("---\n")[1]
        self.assertIn("name: safe-delete", frontmatter)
        self.assertIn("description:", frontmatter)

    def test_bypass_inventory_is_verbatim_and_in_order(self) -> None:
        section = self.text.split("## Out of coverage — bypass inventory")[1]
        listing = section.split("## Residual risk")[0]
        entries = re.findall(r"^\d+\. (.+)$", listing, flags=re.MULTILINE)
        self.assertEqual(entries, list(OUT_OF_COVERAGE_BYPASSES))

    def test_sentinels_are_present(self) -> None:
        self.assertIn(PURGE_SENTINEL, self.text)
        self.assertIn(RESIDUAL_NOTE, self.text)
        self.assertIn("Linux, macOS, and WSL", self.text)
        self.assertIn("native Windows", self.text)
        self.assertIn("docs/project/p7-agent-usage.md", self.text)

    def test_never_teaches_execute_yes_as_a_habit(self) -> None:
        for line in self.text.splitlines():
            if "--execute --yes" in line:
                self.assertRegex(
                    line.lower(),
                    r"never|only",
                    f"every --execute --yes mention must be disciplined: {line!r}",
                )
        self.assertIn("preview", self.text)
        self.assertIn("--confirm", self.text)
        self.assertIn("needs_attention", self.text)
        self.assertIn('needs_attention: false', self.text)
        self.assertIn("never means \"protected\"", self.text)

    def test_every_flag_in_the_skill_exists_in_the_cli_help(self) -> None:
        helps = []
        for command in (
            (),
            ("init",),
            ("add",),
            ("list",),
            ("show",),
            ("restore",),
            ("purge",),
            ("empty",),
            ("setup",),
            ("doctor",),
            ("version",),
            ("hook",),
            ("hook", "install"),
            ("hook", "status"),
            ("hook", "disable"),
            ("hook", "uninstall"),
        ):
            completed = subprocess.run(
                [sys.executable, str(CLI), *command, "--help"],
                cwd=REPOSITORY_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            helps.append(completed.stdout)
        shipped = set(re.findall(r"--[a-z][a-z-]+", " ".join(helps)))
        used = set(re.findall(r"--[a-z][a-z-]+", self.text))
        self.assertEqual(used - shipped, set())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
