from __future__ import annotations

import datetime as _datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from safe_delete.errors import SafeDeleteError
from safe_delete.ledger import append_event, build_purge_intent_record
from safe_delete.retention import RetentionPolicy, format_utc
from safe_delete.storage import layout_for, ledger_lock


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CLI = REPOSITORY_ROOT / "safe-delete"


class PurgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="safe-delete-purge-test-")
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.workspace.mkdir()
        self.storage = Path(self.temp_dir.name) / "storage"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_cli(
        self,
        *arguments: str,
        env: dict[str, str | None] | None = None,
    ) -> tuple[int, dict[str, object]]:
        child_env = os.environ.copy()
        if env:
            for key, value in env.items():
                if value is None:
                    child_env.pop(key, None)
                else:
                    child_env[key] = value
        completed = subprocess.run(
            [sys.executable, str(CLI), "--root", str(self.storage), "--json", *arguments],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            env=child_env,
            check=False,
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover - diagnostic guard
            raise AssertionError(
                f"CLI did not emit JSON\nstdout={completed.stdout!r}\nstderr={completed.stderr!r}"
            ) from exc
        return completed.returncode, payload

    def init_storage(self) -> None:
        code, payload = self.run_cli("init")
        self.assertEqual(code, 0, payload)

    def add_file(self, name: str) -> tuple[str, Path]:
        source = self.workspace / name
        source.write_text(name, encoding="utf-8")
        code, payload = self.run_cli("add", "--", str(source))
        self.assertEqual(code, 0, payload)
        result = payload["results"][0]
        return str(result["entry_id"]), Path(str(result["trashed_path"]))

    def ledger_records(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in (self.storage / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        ]

    def set_creation_timestamp(self, entry_id: str, timestamp: str) -> None:
        records = self.ledger_records()
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

    def direct_purge(
        self,
        *,
        older_than: str | None = "1d",
        before: str | None = None,
        execute: bool = True,
        yes: bool = True,
        dry_run: bool = False,
    ) -> tuple[list[dict[str, object]], list[SafeDeleteError]]:
        import safe_delete.cli as cli

        args = Namespace(
            root=str(self.storage),
            dry_run=dry_run,
            execute=execute,
            yes=yes,
            older_than=older_than,
            before=before,
        )
        return cli._handle_purge(args)

    def test_policy_precedence_grammar_and_inclusive_cutoff(self) -> None:
        now = _datetime.datetime(2026, 9, 16, 12, 0, tzinfo=_datetime.timezone.utc)
        policy = RetentionPolicy.resolve(
            older_than="720h",
            now=now,
            environment="7",
        )
        self.assertEqual(policy.source, "older_than")
        self.assertEqual(policy.threshold_days, 30)
        self.assertEqual(policy.cutoff, now - _datetime.timedelta(days=30))

        before = RetentionPolicy.resolve(
            before="2020-01-01T00:00:00+02:00",
            now=now,
            environment="7",
        )
        self.assertEqual(before.source, "before")
        self.assertEqual(format_utc(before.cutoff), "2019-12-31T22:00:00Z")

        environment = RetentionPolicy.resolve(now=now, environment="7")
        self.assertEqual(environment.source, "environment")
        self.assertEqual(environment.threshold_days, 7)
        default = RetentionPolicy.resolve(now=now, environment=None)
        self.assertEqual(default.source, "default")
        self.assertEqual(default.threshold_days, 30)

        for value in ("0d", "-1d", "1", "1.5d", "1w", " 1d", "1 d", "1D"):
            with self.subTest(value=value):
                with self.assertRaises(SafeDeleteError) as raised:
                    RetentionPolicy.resolve(older_than=value, now=now, environment="7")
                self.assertEqual(raised.exception.code, "usage_error")
        with self.assertRaises(SafeDeleteError) as raised:
            RetentionPolicy.resolve(
                older_than="1d",
                before="2020-01-01T00:00:00Z",
                now=now,
            )
        self.assertEqual(raised.exception.code, "usage_error")
        for value in ("2020-01-01T00:00:00", "not-a-time", "2020-01-01"):
            with self.subTest(value=value):
                with self.assertRaises(SafeDeleteError) as raised:
                    RetentionPolicy.resolve(before=value, now=now)
                self.assertEqual(raised.exception.code, "usage_error")

    def test_before_now_is_wipe_all_sugar_but_never_executes_by_itself(self) -> None:
        now = _datetime.datetime(2026, 9, 16, 12, 0, tzinfo=_datetime.timezone.utc)
        policy = RetentionPolicy.resolve(before="now", now=now, environment="7")
        # ``now`` is the invocation clock, so every active entry is eligible.
        self.assertEqual(policy.source, "before_now")
        self.assertEqual(policy.as_of, now)
        self.assertEqual(policy.cutoff, now)
        self.assertIsNone(policy.threshold)
        self.assertEqual(policy.as_dict()["cutoff"], "2026-09-16T12:00:00Z")

        # A future-dated --before is the same wipe-all shape and warns too.
        future = RetentionPolicy.resolve(
            before="2030-01-01T00:00:00Z",
            now=now,
        )
        self.assertEqual(future.source, "before")

        # The literal is exact: it is not a case-insensitive keyword and it is
        # not a substitute for an RFC3339 instant.
        for value in ("NOW", "now ", "Now"):
            with self.subTest(value=value):
                with self.assertRaises(SafeDeleteError) as raised:
                    RetentionPolicy.resolve(before=value, now=now)
                self.assertEqual(raised.exception.code, "usage_error")

    def test_before_now_dry_run_reports_wipe_all_without_mutation(self) -> None:
        self.init_storage()
        entry_id, payload = self.add_file("fresh.txt")
        ledger_before = (self.storage / "ledger.jsonl").read_bytes()

        code, envelope = self.run_cli("purge", "--before", "now")
        self.assertEqual(code, 0, envelope)
        report = envelope["results"][0]
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["policy"]["source"], "before_now")
        self.assertIn("warning", report)
        self.assertIn("every active entry is eligible", report["warning"])
        self.assertEqual(report["candidates"], [entry_id])
        self.assertEqual(payload.read_text(encoding="utf-8"), "fresh.txt")
        self.assertEqual((self.storage / "ledger.jsonl").read_bytes(), ledger_before)

        # The sugar never implies --execute --yes: without both, the CLI is
        # still a dry run even though the cutoff selects everything.
        code, envelope = self.run_cli("purge", "--before", "now", "--execute")
        self.assertNotEqual(code, 0)
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["errors"][0]["code"], "usage_error")
        self.assertEqual(payload.read_text(encoding="utf-8"), "fresh.txt")
        self.assertEqual((self.storage / "ledger.jsonl").read_bytes(), ledger_before)

    def test_retention_overflow_is_usage_error_without_mutation(self) -> None:
        self.init_storage()
        entry_id, payload = self.add_file("untouched.txt")
        ledger_before = (self.storage / "ledger.jsonl").read_bytes()
        paths_before = sorted(
            path.relative_to(self.storage).as_posix() for path in self.storage.rglob("*")
        )
        payload_before = payload.read_bytes()
        cases = (
            (("--older-than", "999999999d"), {}),
            (("--older-than", "999999999h"), {}),
            ((), {"SAFE_DELETE_RETENTION_DAYS": "999999999"}),
            (
                ("--before", "0001-01-01T00:00:00+23:59"),
                {},
            ),
            (
                ("--before", "9999-12-31T23:59:59-23:59"),
                {},
            ),
        )
        for arguments, environment in cases:
            with self.subTest(arguments=arguments, environment=environment):
                code, report = self.run_cli(
                    "purge",
                    "--dry-run",
                    *arguments,
                    env={
                        "SAFE_DELETE_RETENTION_DAYS": environment.get(
                            "SAFE_DELETE_RETENTION_DAYS"
                        )
                    },
                )
                self.assertEqual(code, 2, report)
                self.assertFalse(report["ok"])
                self.assertEqual(report["results"], [])
                self.assertEqual(report["errors"][0]["code"], "usage_error")
                self.assertNotIn("OverflowError", str(report))
        self.assertEqual(
            sorted(
                path.relative_to(self.storage).as_posix() for path in self.storage.rglob("*")
            ),
            paths_before,
        )
        self.assertEqual((self.storage / "ledger.jsonl").read_bytes(), ledger_before)
        self.assertEqual(payload.read_bytes(), payload_before)
        self.assertTrue(payload.is_file(), entry_id)

    def test_retention_boundary_and_age_anchor(self) -> None:
        self.init_storage()
        young_id, young_payload = self.add_file("young.txt")
        old_id, old_payload = self.add_file("old.txt")
        self.set_creation_timestamp(young_id, "2024-01-01T00:00:01Z")
        self.set_creation_timestamp(old_id, "2024-01-01T00:00:00Z")
        cutoff = "2024-01-01T00:00:00+00:00"

        code, preview = self.run_cli("purge", "--before", cutoff)
        self.assertEqual(code, 0, preview)
        report = preview["results"][0]
        self.assertEqual(report["policy"]["source"], "before")
        self.assertEqual(report["policy"]["cutoff"], "2024-01-01T00:00:00Z")
        self.assertEqual(report["candidates"], [old_id])
        decisions = {item["entry_id"]: item for item in report["decisions"]}
        self.assertEqual(decisions[old_id]["reason"], "eligible")
        self.assertEqual(decisions[young_id]["reason"], "too_young")
        self.assertTrue(old_payload.is_file())
        self.assertTrue(young_payload.is_file())
        self.assertEqual(len(self.ledger_records()), 2)

        code, executed = self.run_cli("purge", "--execute", "--yes", "--before", cutoff)
        self.assertEqual(code, 0, executed)
        self.assertFalse(old_payload.exists())
        self.assertTrue(young_payload.is_file())
        records = self.ledger_records()
        old_events = [record for record in records if record["entry_id"] == old_id]
        self.assertEqual(
            [record["operation"] for record in old_events],
            ["trash", "purge_intent", "purge_complete"],
        )
        self.assertEqual(old_events[0]["timestamp"], "2024-01-01T00:00:00Z")
        self.assertEqual(old_events[1]["state"], "purge_pending")
        self.assertEqual(old_events[2]["state"], "purged")

    def test_directory_payload_reclaims_object_without_following_symlinks(self) -> None:
        self.init_storage()
        source = self.workspace / "tree"
        source.mkdir()
        (source / "child.txt").write_text("inside", encoding="utf-8")
        external = self.workspace / "external"
        external.mkdir()
        protected = external / "protected.txt"
        protected.write_text("must survive", encoding="utf-8")
        (source / "link").symlink_to(protected)
        code, added = self.run_cli("add", "--", str(source))
        self.assertEqual(code, 0, added)
        entry_id = str(added["results"][0]["entry_id"])
        payload = Path(str(added["results"][0]["trashed_path"]))
        self.set_creation_timestamp(entry_id, "2024-01-01T00:00:00Z")

        code, purged = self.run_cli("purge", "--execute", "--yes", "--older-than", "1d")
        self.assertEqual(code, 0, purged)
        self.assertFalse(payload.exists())
        self.assertFalse(payload.parent.exists())
        self.assertEqual(protected.read_text(encoding="utf-8"), "must survive")

    def test_dry_run_json_policy_exclusions_and_no_mutation(self) -> None:
        self.init_storage()
        young_id, young_payload = self.add_file("young.txt")
        old_id, old_payload = self.add_file("old.txt")
        self.set_creation_timestamp(young_id, "2026-09-15T00:00:00Z")
        self.set_creation_timestamp(old_id, "2024-01-01T00:00:00Z")
        ledger_before = (self.storage / "ledger.jsonl").read_bytes()
        old_before = old_payload.read_bytes()
        young_before = young_payload.read_bytes()

        code, payload = self.run_cli(
            "purge",
            "--dry-run",
            "--older-than",
            "720h",
            env={"SAFE_DELETE_RETENTION_DAYS": "bad"},
        )
        self.assertEqual(code, 0, payload)
        report = payload["results"][0]
        self.assertEqual(report["policy"]["source"], "older_than")
        self.assertEqual(report["policy"]["threshold_days"], 30)
        self.assertIn("cutoff", report["policy"])
        self.assertEqual(report["candidates"], [old_id])
        decisions = {item["entry_id"]: item for item in report["decisions"]}
        self.assertEqual(decisions[old_id]["decision"], "candidate")
        self.assertEqual(decisions[young_id]["decision"], "excluded")
        self.assertEqual(decisions[young_id]["reason"], "too_young")
        self.assertEqual(report["outcomes"], [])
        self.assertEqual((self.storage / "ledger.jsonl").read_bytes(), ledger_before)
        self.assertEqual(old_payload.read_bytes(), old_before)
        self.assertEqual(young_payload.read_bytes(), young_before)
        self.assertNotIn("purge_intent", [record["operation"] for record in self.ledger_records()])

        code, env_report = self.run_cli(
            "purge",
            env={"SAFE_DELETE_RETENTION_DAYS": "30"},
        )
        self.assertEqual(code, 0, env_report)
        self.assertEqual(env_report["results"][0]["policy"]["source"], "environment")

    def test_dry_run_has_same_fail_closed_audit_preflight(self) -> None:
        self.init_storage()
        entry_id, payload = self.add_file("aged.txt")
        self.set_creation_timestamp(entry_id, "2024-01-01T00:00:00Z")
        orphan_id = str(uuid.uuid4())
        orphan_payload = self.storage / "trash" / "objects" / orphan_id / "payload"
        orphan_payload.parent.mkdir()
        orphan_payload.write_text("orphan", encoding="utf-8")
        ledger_before = (self.storage / "ledger.jsonl").read_bytes()

        code, report = self.run_cli("purge")
        self.assertEqual(code, 4, report)
        self.assertEqual(report["errors"][0]["code"], "orphan_payload")
        result = report["results"][0]
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["decisions"][0]["reason"], "audit_error")
        self.assertTrue(payload.is_file())
        self.assertEqual((self.storage / "ledger.jsonl").read_bytes(), ledger_before)
        self.assertNotIn("purge_intent", [record["operation"] for record in self.ledger_records()])

    def test_partial_failure_retry_crash_recovery_and_terminal_idempotence(self) -> None:
        self.init_storage()
        failed_id, failed_payload = self.add_file("failed.txt")
        success_id, success_payload = self.add_file("success.txt")
        self.set_creation_timestamp(failed_id, "2024-01-01T00:00:00Z")
        self.set_creation_timestamp(success_id, "2024-01-01T00:00:00Z")

        import safe_delete.purge as purge

        real_remove = purge.remove_payload

        def fail_one(layout: object, entry: object) -> None:
            if getattr(entry, "entry_id") == failed_id:
                raise SafeDeleteError("storage_failure", "injected removal failure")
            real_remove(layout, entry)

        with patch.object(purge, "remove_payload", side_effect=fail_one):
            results, errors = self.direct_purge()
        self.assertEqual(
            [item.code for item in errors],
            ["purge_remove_failed", "partial_failure"],
        )
        report = results[0]
        outcomes = {item["entry_id"]: item for item in report["outcomes"]}
        self.assertEqual(outcomes[failed_id]["state"], "active")
        self.assertEqual(outcomes[failed_id]["error_code"], "purge_remove_failed")
        self.assertEqual(outcomes[success_id]["state"], "purged")
        self.assertTrue(failed_payload.is_file())
        self.assertFalse(success_payload.exists())
        events = self.ledger_records()
        failed_events = [record for record in events if record["entry_id"] == failed_id]
        success_events = [record for record in events if record["entry_id"] == success_id]
        self.assertEqual(
            [record["operation"] for record in failed_events],
            ["trash", "purge_intent", "purge_failed"],
        )
        self.assertEqual(failed_events[-1]["state"], "active")
        self.assertEqual(failed_events[-1]["error_code"], "purge_remove_failed")
        self.assertEqual(
            [record["operation"] for record in success_events],
            ["trash", "purge_intent", "purge_complete"],
        )

        code, retried = self.run_cli("purge", "--execute", "--yes", "--older-than", "1d")
        self.assertEqual(code, 0, retried)
        retry_outcome = next(
            item for item in retried["results"][0]["outcomes"] if item["entry_id"] == failed_id
        )
        self.assertEqual(retry_outcome["state"], "purged")
        self.assertFalse(failed_payload.exists())

        code, terminal = self.run_cli("purge", "--execute", "--yes", "--older-than", "1d")
        self.assertEqual(code, 0, terminal)
        terminal_outcome = {
            item["entry_id"]: item for item in terminal["results"][0]["outcomes"]
        }
        self.assertEqual(terminal_outcome[failed_id]["code"], "already_purged")
        self.assertEqual(terminal_outcome[success_id]["code"], "already_purged")
        self.assertEqual(
            [record["operation"] for record in self.ledger_records() if record["entry_id"] == success_id],
            ["trash", "purge_intent", "purge_complete"],
        )

        recovery_id, recovery_payload = self.add_file("recovery.txt")
        self.set_creation_timestamp(recovery_id, "2024-01-01T00:00:00Z")
        layout = layout_for(str(self.storage))
        with ledger_lock(layout, exclusive=True):
            audit = __import__("safe_delete.audit", fromlist=["audit_layout"]).audit_layout(layout)
            recovery_entry = audit.entries[recovery_id]
            append_event(layout, build_purge_intent_record(recovery_entry))

        code, recovered = self.run_cli(
            "purge",
            "--execute",
            "--yes",
            "--before",
            "2023-01-01T00:00:00Z",
        )
        self.assertEqual(code, 0, recovered)
        recovery_outcome = next(
            item
            for item in recovered["results"][0]["outcomes"]
            if item["entry_id"] == recovery_id
        )
        self.assertTrue(recovery_outcome["recovered"])
        self.assertFalse(recovery_payload.exists())
        recovery_events = [
            record for record in self.ledger_records() if record["entry_id"] == recovery_id
        ]
        self.assertEqual(
            [record["operation"] for record in recovery_events],
            ["trash", "purge_intent", "purge_complete"],
        )

    def test_restore_interaction_and_terminal_state_codes(self) -> None:
        self.init_storage()
        pending_id, pending_payload = self.add_file("pending.txt")
        self.set_creation_timestamp(pending_id, "2024-01-01T00:00:00Z")
        layout = layout_for(str(self.storage))
        with ledger_lock(layout, exclusive=True):
            audit = __import__("safe_delete.audit", fromlist=["audit_layout"]).audit_layout(layout)
            append_event(layout, build_purge_intent_record(audit.entries[pending_id]))
        ledger_before_restore = (self.storage / "ledger.jsonl").read_bytes()
        code, pending_restore = self.run_cli("restore", pending_id)
        self.assertEqual(code, 3, pending_restore)
        self.assertEqual(pending_restore["errors"][0]["code"], "entry_not_restorable")
        self.assertTrue(pending_payload.is_file())
        self.assertEqual((self.storage / "ledger.jsonl").read_bytes(), ledger_before_restore)

        code, recovered = self.run_cli("purge", "--execute", "--yes", "--older-than", "1d")
        self.assertEqual(code, 0, recovered)
        self.assertFalse(pending_payload.exists())
        code, purged_restore = self.run_cli("restore", pending_id)
        self.assertEqual(code, 0, purged_restore)
        self.assertEqual(purged_restore["results"][0]["code"], "already_purged")

        restored_id, restored_payload = self.add_file("restored.txt")
        self.set_creation_timestamp(restored_id, "2024-01-01T00:00:00Z")
        code, restored = self.run_cli("restore", restored_id)
        self.assertEqual(code, 0, restored)
        self.assertFalse(restored_payload.exists())
        code, restored_purge = self.run_cli("purge", "--execute", "--yes", "--older-than", "1d")
        self.assertEqual(code, 0, restored_purge)
        restored_decision = next(
            item
            for item in restored_purge["results"][0]["decisions"]
            if item["entry_id"] == restored_id
        )
        self.assertEqual(restored_decision["reason"], "restored")

    def test_missing_corrupt_and_orphan_fixtures_block_before_new_intent(self) -> None:
        scenarios = ("missing", "orphan", "malformed")
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                with tempfile.TemporaryDirectory(
                    prefix=f"safe-delete-purge-{scenario}-"
                ) as scenario_root:
                    previous_workspace = self.workspace
                    previous_storage = self.storage
                    self.workspace = Path(scenario_root) / "workspace"
                    self.workspace.mkdir()
                    self.storage = Path(scenario_root) / "storage"
                    try:
                        self.init_storage()
                        entry_id, payload = self.add_file(f"{scenario}.txt")
                        self.set_creation_timestamp(entry_id, "2024-01-01T00:00:00Z")
                        if scenario == "missing":
                            payload.unlink()
                        elif scenario == "orphan":
                            orphan = self.storage / "trash" / "objects" / str(uuid.uuid4()) / "payload"
                            orphan.parent.mkdir()
                            orphan.write_text("orphan", encoding="utf-8")
                        else:
                            with (self.storage / "ledger.jsonl").open("a", encoding="utf-8") as ledger:
                                ledger.write("{not-json\n")
                        ledger_before = (self.storage / "ledger.jsonl").read_bytes()
                        code, report = self.run_cli(
                            "purge", "--execute", "--yes", "--older-than", "1d"
                        )
                        self.assertEqual(code, 4, report)
                        self.assertEqual(report["results"][0]["candidates"], [])
                        self.assertEqual(
                            (self.storage / "ledger.jsonl").read_bytes(), ledger_before
                        )
                        self.assertNotIn(
                            b'"operation":"purge_intent"',
                            (self.storage / "ledger.jsonl").read_bytes(),
                        )
                        if scenario != "missing":
                            self.assertTrue(payload.is_file())
                    finally:
                        self.workspace = previous_workspace
                        self.storage = previous_storage

    def test_usage_and_confirmation_errors_do_not_mutate(self) -> None:
        self.init_storage()
        entry_id, payload = self.add_file("safe.txt")
        ledger_before = (self.storage / "ledger.jsonl").read_bytes()
        cases = (
            (("--older-than", "1d", "--before", "2020-01-01T00:00:00Z"), None),
            (("--dry-run", "--execute"), None),
            (("--execute",), None),
            (("--older-than", "not-a-duration"), None),
            (("--before", "2020-01-01T00:00:00"), None),
        )
        for arguments, _ in cases:
            with self.subTest(arguments=arguments):
                code, report = self.run_cli("purge", *arguments)
                self.assertEqual(code, 2, report)
                self.assertEqual(report["errors"][0]["code"], "usage_error")
                self.assertTrue(payload.is_file())
                self.assertEqual((self.storage / "ledger.jsonl").read_bytes(), ledger_before)

        for invalid in ("0", "-1", "1.5", "nope", "9" * 5000):
            with self.subTest(invalid_env=invalid):
                code, report = self.run_cli(
                    "purge",
                    env={"SAFE_DELETE_RETENTION_DAYS": invalid},
                )
                self.assertEqual(code, 2, report)
                self.assertEqual(report["errors"][0]["code"], "usage_error")
                self.assertEqual((self.storage / "ledger.jsonl").read_bytes(), ledger_before)
        self.assertTrue(payload.is_file())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
