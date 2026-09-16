from __future__ import annotations

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


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CLI = REPOSITORY_ROOT / "safe-delete"


def run_cli(root: Path, *arguments: str) -> tuple[int, dict[str, object]]:
    completed = subprocess.run(
        [sys.executable, str(CLI), "--root", str(root), "--json", *arguments],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - useful failure detail
        raise AssertionError(
            f"CLI did not emit JSON\nstdout={completed.stdout!r}\nstderr={completed.stderr!r}"
        ) from exc
    return completed.returncode, payload


class CliContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="safe-delete-test-")
        self.workspace = Path(self.temp_dir.name) / "workspace"
        self.workspace.mkdir()
        self.storage = Path(self.temp_dir.name) / "storage"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def init_storage(self) -> None:
        code, payload = run_cli(self.storage, "init")
        self.assertEqual(code, 0, payload)
        self.assertTrue((self.storage / "ledger.jsonl").is_file())
        self.assertTrue((self.storage / "locks" / "ledger.lock").is_file())
        self.assertTrue((self.storage / "trash" / "objects").is_dir())

    def test_bootstrap_version_reserved_commands_and_empty_list(self) -> None:
        code, payload = run_cli(self.storage, "version")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["results"][0]["contract_version"], 1)
        self.assertFalse(self.storage.exists(), "version must not initialize storage")

        self.init_storage()
        code, payload = run_cli(self.storage, "list")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["results"], [])

        before = sorted(path.relative_to(self.storage).as_posix() for path in self.storage.rglob("*"))
        code, payload = run_cli(self.storage, "purge")
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["errors"][0]["code"], "unsupported_command")
        code, hook_payload = run_cli(self.storage, "hook", "install", "codex")
        self.assertEqual(code, 2, hook_payload)
        self.assertEqual(hook_payload["errors"][0]["code"], "unsupported_command")
        after = sorted(path.relative_to(self.storage).as_posix() for path in self.storage.rglob("*"))
        self.assertEqual(before, after)

    def test_add_moves_file_directory_and_symlink_and_writes_minimum_records(self) -> None:
        self.init_storage()
        file_path = self.workspace / "file.txt"
        file_path.write_text("hello", encoding="utf-8")
        directory = self.workspace / "directory"
        directory.mkdir()
        (directory / "child.txt").write_text("child", encoding="utf-8")
        link = self.workspace / "link"
        link.symlink_to("missing-target")

        code, payload = run_cli(
            self.storage,
            "add",
            "--",
            str(file_path),
            str(directory),
            str(link),
        )
        self.assertEqual(code, 0, payload)
        results = payload["results"]
        self.assertEqual(len(results), 3)
        for result in results:
            entry_id = result["entry_id"]
            parsed = uuid.UUID(entry_id)
            self.assertEqual(parsed.version, 4)
            self.assertEqual(str(parsed), entry_id)
            self.assertFalse(os.path.lexists(result["original_path"]))
            self.assertTrue(os.path.lexists(result["trashed_path"]))

        lines = [json.loads(line) for line in (self.storage / "ledger.jsonl").read_text().splitlines()]
        self.assertEqual(len(lines), 3)
        for record in lines:
            self.assertEqual(
                set(record),
                {
                    "schema_version",
                    "event_id",
                    "entry_id",
                    "operation",
                    "state",
                    "original_path",
                    "trashed_path",
                    "kind",
                    "timestamp",
                },
            )
            self.assertEqual(record["schema_version"], 1)
            self.assertEqual(record["operation"], "trash")
            self.assertEqual(record["state"], "active")
            self.assertEqual(str(uuid.UUID(record["event_id"])), record["event_id"])

        code, list_payload = run_cli(self.storage, "list")
        self.assertEqual(code, 0, list_payload)
        self.assertEqual({item["entry_id"] for item in list_payload["results"]}, {
            item["entry_id"] for item in results
        })
        code, show_payload = run_cli(self.storage, "show", results[0]["entry_id"])
        self.assertEqual(code, 0, show_payload)
        self.assertEqual(len(show_payload["results"][0]["events"]), 1)
        self.assertEqual(show_payload["results"][0]["creation"]["operation"], "trash")

    def test_list_reports_injected_orphan(self) -> None:
        self.init_storage()
        orphan_id = "550e8400-e29b-41d4-a716-446655440000"
        orphan_payload = self.storage / "trash" / "objects" / orphan_id / "payload"
        orphan_payload.parent.mkdir()
        orphan_payload.write_text("quarantined", encoding="utf-8")

        code, payload = run_cli(self.storage, "list", "--orphans")
        self.assertEqual(code, 4, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["errors"][0]["code"], "orphan_payload")
        self.assertEqual(payload["errors"][0]["entry_id"], orphan_id)
        self.assertEqual(payload["errors"][0]["trashed_path"], str(orphan_payload))

        code, normal_payload = run_cli(self.storage, "list")
        self.assertEqual(code, 4, normal_payload)
        self.assertEqual(normal_payload["errors"][0]["code"], "orphan_payload")

    def test_restore_collision_is_no_overwrite_and_history_is_preserved(self) -> None:
        self.init_storage()
        source = self.workspace / "restore-me.txt"
        source.write_text("original", encoding="utf-8")
        code, add_payload = run_cli(self.storage, "add", "--", str(source))
        self.assertEqual(code, 0, add_payload)
        result = add_payload["results"][0]
        entry_id = result["entry_id"]
        payload_path = Path(result["trashed_path"])

        source.write_text("sentinel", encoding="utf-8")
        code, collision = run_cli(self.storage, "restore", entry_id)
        self.assertEqual(code, 3, collision)
        self.assertEqual(collision["errors"][0]["code"], "destination_exists")
        self.assertEqual(source.read_text(encoding="utf-8"), "sentinel")
        self.assertTrue(payload_path.is_file())
        self.assertEqual(len((self.storage / "ledger.jsonl").read_text().splitlines()), 1)

        source.unlink()
        source.symlink_to("still-missing")
        code, dangling_collision = run_cli(self.storage, "restore", entry_id)
        self.assertEqual(code, 3, dangling_collision)
        self.assertEqual(dangling_collision["errors"][0]["code"], "destination_exists")
        self.assertTrue(os.path.lexists(source))
        self.assertTrue(payload_path.is_file())
        source.unlink()

        code, restored = run_cli(self.storage, "restore", entry_id)
        self.assertEqual(code, 0, restored)
        self.assertEqual(source.read_text(encoding="utf-8"), "original")
        self.assertFalse(payload_path.exists())
        ledger_lines = (self.storage / "ledger.jsonl").read_text().splitlines()
        self.assertEqual(len(ledger_lines), 2)
        restore_record = json.loads(ledger_lines[-1])
        self.assertEqual(restore_record["operation"], "restore")
        self.assertEqual(restore_record["state"], "restored")
        self.assertEqual(restore_record["restore_path"], str(source))

        code, repeated = run_cli(self.storage, "restore", entry_id)
        self.assertEqual(code, 0, repeated)
        self.assertEqual(repeated["errors"], [])
        self.assertEqual(repeated["results"][0]["code"], "already_restored")
        self.assertEqual(len((self.storage / "ledger.jsonl").read_text().splitlines()), 2)

        code, all_entries = run_cli(self.storage, "list", "--all")
        self.assertEqual(code, 0, all_entries)
        self.assertEqual(all_entries["results"][0]["state"], "restored")

    def test_restore_to_requires_parents_unless_opted_in(self) -> None:
        self.init_storage()
        source = self.workspace / "source.txt"
        source.write_text("content", encoding="utf-8")
        code, add_payload = run_cli(self.storage, "add", "--", str(source))
        self.assertEqual(code, 0, add_payload)
        entry_id = add_payload["results"][0]["entry_id"]
        target = self.workspace / "new" / "nested" / "target.txt"

        code, missing = run_cli(self.storage, "restore", "--to", str(target), entry_id)
        self.assertEqual(code, 3, missing)
        self.assertEqual(missing["errors"][0]["code"], "destination_parent_missing")
        self.assertFalse(target.exists())
        self.assertTrue(Path(add_payload["results"][0]["trashed_path"]).is_file())

        code, restored = run_cli(
            self.storage,
            "restore",
            "--to",
            str(target),
            "--create-parents",
            entry_id,
        )
        self.assertEqual(code, 0, restored)
        self.assertEqual(target.read_text(encoding="utf-8"), "content")
        record = json.loads((self.storage / "ledger.jsonl").read_text().splitlines()[-1])
        self.assertEqual(record["restore_path"], str(target))

    def test_ledger_append_failure_rolls_back_without_raw_delete(self) -> None:
        self.init_storage()
        source = self.workspace / "append-failure.txt"
        source.write_text("must survive", encoding="utf-8")

        import safe_delete.cli as cli
        from safe_delete.errors import SafeDeleteError

        args = Namespace(
            root=str(self.storage),
            paths=[str(source)],
            dry_run=False,
            reason=None,
            project=None,
            session_id=None,
            agent=None,
            tool=None,
        )
        injected = SafeDeleteError("ledger_failure", "injected append failure")
        with patch.object(cli, "append_event", side_effect=injected):
            results, errors = cli._handle_add(args)
        self.assertEqual(results, [])
        self.assertEqual([item.code for item in errors], ["ledger_failure"])
        self.assertTrue(source.is_file())
        self.assertEqual(source.read_text(encoding="utf-8"), "must survive")
        self.assertEqual((self.storage / "ledger.jsonl").read_text(), "")
        self.assertEqual(list((self.storage / "trash" / "objects").iterdir()), [])

    def test_audit_failure_blocks_add_and_restore(self) -> None:
        self.init_storage()
        first = self.workspace / "first.txt"
        first.write_text("first", encoding="utf-8")
        code, added = run_cli(self.storage, "add", "--", str(first))
        self.assertEqual(code, 0, added)
        entry_id = added["results"][0]["entry_id"]
        payload_path = Path(added["results"][0]["trashed_path"])
        with (self.storage / "ledger.jsonl").open("a", encoding="utf-8") as ledger:
            ledger.write("{not-json\n")

        second = self.workspace / "second.txt"
        second.write_text("second", encoding="utf-8")
        code, add_failure = run_cli(self.storage, "add", "--", str(second))
        self.assertEqual(code, 4, add_failure)
        self.assertIn("malformed_ledger", [item["code"] for item in add_failure["errors"]])
        self.assertTrue(second.is_file())

        code, restore_failure = run_cli(self.storage, "restore", entry_id)
        self.assertEqual(code, 4, restore_failure)
        self.assertIn("malformed_ledger", [item["code"] for item in restore_failure["errors"]])
        self.assertTrue(payload_path.is_file())
        self.assertFalse(first.exists())

    @unittest.skipUnless(
        Path("/dev/shm").is_dir() and os.stat("/dev/shm").st_dev != os.stat("/tmp").st_dev,
        "this host does not provide a distinct /dev/shm filesystem",
    )
    def test_cross_device_add_fails_closed(self) -> None:
        self.init_storage()
        source_fd, source_name = tempfile.mkstemp(
            prefix="safe-delete-cross-device-", dir="/dev/shm"
        )
        os.close(source_fd)
        source = Path(source_name)
        try:
            source.write_text("stay", encoding="utf-8")
            code, payload = run_cli(self.storage, "add", "--", str(source))
            self.assertEqual(code, 2, payload)
            self.assertEqual(payload["errors"][0]["code"], "cross_device")
            self.assertTrue(source.is_file())
            self.assertEqual(list((self.storage / "trash" / "objects").iterdir()), [])
        finally:
            source.unlink(missing_ok=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
