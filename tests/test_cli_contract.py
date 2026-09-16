from __future__ import annotations

import json
import contextlib
import errno
import io
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

    def test_empty_add_path_is_rejected_without_touching_cwd(self) -> None:
        self.init_storage()
        cwd = REPOSITORY_ROOT / "safe-delete"
        code, payload = run_cli(self.storage, "add", "--", "")
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["errors"][0]["code"], "usage_error")
        self.assertEqual(len(payload["results"]), 1)
        self.assertFalse(payload["results"][0]["ok"])
        self.assertTrue(cwd.is_file())
        self.assertEqual(list((self.storage / "trash" / "objects").iterdir()), [])

    def test_append_repairs_missing_jsonl_delimiter(self) -> None:
        self.init_storage()
        first = self.workspace / "first.txt"
        second = self.workspace / "second.txt"
        first.write_text("first", encoding="utf-8")
        second.write_text("second", encoding="utf-8")
        code, first_payload = run_cli(self.storage, "add", "--", str(first))
        self.assertEqual(code, 0, first_payload)
        ledger = self.storage / "ledger.jsonl"
        ledger.write_bytes(ledger.read_bytes().rstrip(b"\n"))

        code, second_payload = run_cli(self.storage, "add", "--", str(second))
        self.assertEqual(code, 0, second_payload)
        code, listed = run_cli(self.storage, "list")
        self.assertEqual(code, 0, listed)
        self.assertEqual(listed["errors"], [])
        self.assertEqual(len(listed["results"]), 2)
        self.assertEqual(len(ledger.read_text(encoding="utf-8").splitlines()), 2)

    def test_malformed_field_types_emit_json_malformed_ledger_without_traceback(self) -> None:
        self.init_storage()
        record = {
            "schema_version": 1,
            "event_id": str(uuid.uuid4()),
            "entry_id": str(uuid.uuid4()),
            "operation": [],
            "state": "active",
            "original_path": str(self.workspace / "item"),
            "trashed_path": str(self.storage / "trash" / "objects" / "x" / "payload"),
            "kind": "file",
            "timestamp": "2026-09-16T07:00:00Z",
        }
        (self.storage / "ledger.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(CLI), "--root", str(self.storage), "--json", "list"],
            cwd=REPOSITORY_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 4, payload)
        self.assertEqual(payload["errors"][0]["code"], "malformed_ledger")
        self.assertNotIn("Traceback", completed.stderr)

    def test_audit_rejects_unknown_fields_and_unsafe_ledger_paths(self) -> None:
        self.init_storage()
        source = self.workspace / "source.txt"
        source.write_text("content", encoding="utf-8")
        code, added = run_cli(self.storage, "add", "--", str(source))
        self.assertEqual(code, 0, added)
        ledger = self.storage / "ledger.jsonl"
        record = json.loads(ledger.read_text(encoding="utf-8"))

        record["unexpected"] = True
        ledger.write_text(json.dumps(record) + "\n", encoding="utf-8")
        code, unknown = run_cli(self.storage, "list")
        self.assertEqual(code, 4, unknown)
        self.assertEqual(unknown["errors"][0]["code"], "malformed_ledger")

        record.pop("unexpected")
        record["original_path"] = str(self.storage / "trash" / "escaped")
        ledger.write_text(json.dumps(record) + "\n", encoding="utf-8")
        code, unsafe = run_cli(self.storage, "list")
        self.assertEqual(code, 4, unsafe)
        self.assertEqual(unsafe["errors"][0]["code"], "malformed_ledger")

    def test_orphan_listing_filters_malformed_ledger_errors(self) -> None:
        self.init_storage()
        orphan_id = "550e8400-e29b-41d4-a716-446655440000"
        orphan_payload = self.storage / "trash" / "objects" / orphan_id / "payload"
        orphan_payload.parent.mkdir()
        orphan_payload.write_text("orphan", encoding="utf-8")
        with (self.storage / "ledger.jsonl").open("a", encoding="utf-8") as ledger:
            ledger.write("{malformed\n")

        code, payload = run_cli(self.storage, "list", "--orphans")
        self.assertEqual(code, 4, payload)
        self.assertEqual([item["code"] for item in payload["errors"]], ["orphan_payload"])

    def test_partial_batch_has_one_result_per_input(self) -> None:
        self.init_storage()
        existing = self.workspace / "existing.txt"
        missing = self.workspace / "missing.txt"
        existing.write_text("exists", encoding="utf-8")
        code, payload = run_cli(self.storage, "add", "--", str(existing), str(missing))
        self.assertEqual(code, 5, payload)
        self.assertEqual(len(payload["results"]), 2)
        self.assertEqual(payload["results"][0]["state"], "active")
        self.assertFalse(payload["results"][1]["ok"])
        self.assertEqual(payload["results"][1]["error"]["code"], "source_not_found")
        self.assertIn("partial_failure", [item["code"] for item in payload["errors"]])

    def test_fallback_collision_does_not_overwrite_racing_destination(self) -> None:
        import safe_delete.move as move
        from safe_delete.errors import SafeDeleteError

        source = self.workspace / "source.txt"
        destination = self.workspace / "destination.txt"
        source.write_text("source", encoding="utf-8")

        def race(*args: object, **kwargs: object) -> None:
            destination.write_text("sentinel", encoding="utf-8")
            raise OSError(errno.EEXIST, "destination appeared")

        with patch.object(move, "_renameat2_noreplace", return_value=move._NO_REPLACE_UNAVAILABLE):
            with patch.object(move.os, "link", side_effect=race):
                with self.assertRaises(SafeDeleteError) as raised:
                    move.atomic_move(source, destination)
        self.assertEqual(raised.exception.code, "destination_exists")
        self.assertEqual(source.read_text(encoding="utf-8"), "source")
        self.assertEqual(destination.read_text(encoding="utf-8"), "sentinel")

    def test_parent_symlink_replacement_keeps_move_on_original_directory_fd(self) -> None:
        import safe_delete.move as move

        parent = self.workspace / "parent"
        parked = self.workspace / "parked"
        external = self.workspace / "external"
        destination = self.workspace / "trash-payload"
        parent.mkdir()
        parked.mkdir()
        external.mkdir()
        source = parent / "item.txt"
        source.write_text("safe", encoding="utf-8")
        (external / "item.txt").write_text("must stay", encoding="utf-8")

        original_lstat_at = move._lstat_at
        injected = False

        def replace_parent(fd: int, name: str) -> os.stat_result | None:
            nonlocal injected
            result = original_lstat_at(fd, name)
            if not injected:
                injected = True
                os.rename(parent, parked / "parent")
                parent.symlink_to(external, target_is_directory=True)
            return result

        with patch.object(move, "_lstat_at", side_effect=replace_parent):
            move.atomic_move(source, destination)
        self.assertEqual((external / "item.txt").read_text(encoding="utf-8"), "must stay")
        self.assertFalse((parked / "parent" / "item.txt").exists())
        self.assertEqual(destination.read_text(encoding="utf-8"), "safe")

    def test_human_recovery_diagnostics_print_both_paths(self) -> None:
        import safe_delete.cli as cli
        from safe_delete.errors import error

        source = str(self.workspace / "source.txt")
        trash = str(self.storage / "trash" / "objects" / "id" / "payload")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli._emit(
                "add",
                [],
                [error("rollback_failed", "recovery required", source=source, trashed_path=trash)],
                False,
            )
            cli._emit(
                "list",
                [],
                [error("orphan_payload", "orphan", trashed_path=trash)],
                False,
            )
        output = stderr.getvalue()
        self.assertIn(f"source path: {source}", output)
        self.assertIn(f"trash path: {trash}", output)
        self.assertIn("source path: <not recorded>", output)

    def test_fsync_failure_rolls_back_move(self) -> None:
        self.init_storage()
        source = self.workspace / "fsync-failure.txt"
        source.write_text("must survive", encoding="utf-8")
        import safe_delete.cli as cli
        import safe_delete.ledger as ledger

        args = Namespace(
            root=str(self.storage), paths=[str(source)], dry_run=False,
            reason=None, project=None, session_id=None, agent=None, tool=None,
        )
        with patch.object(ledger.os, "fsync", side_effect=OSError(errno.EIO, "injected fsync")):
            results, errors = cli._handle_add(args)
        self.assertEqual(results[0]["ok"], False)
        self.assertEqual(errors[0].code, "ledger_failure")
        self.assertTrue(source.is_file())

    def test_add_rollback_failure_reports_both_paths(self) -> None:
        self.init_storage()
        source = self.workspace / "rollback-failure.txt"
        source.write_text("quarantine", encoding="utf-8")
        import safe_delete.cli as cli
        from safe_delete.errors import SafeDeleteError

        args = Namespace(
            root=str(self.storage), paths=[str(source)], dry_run=False,
            reason=None, project=None, session_id=None, agent=None, tool=None,
        )
        real_move = cli.atomic_move
        calls = 0

        def fail_rollback(src: str, dst: str, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise SafeDeleteError("storage_failure", "rollback blocked")
            real_move(src, dst, **kwargs)

        injected = SafeDeleteError("ledger_failure", "append blocked")
        with patch.object(cli, "append_event", side_effect=injected):
            with patch.object(cli, "atomic_move", side_effect=fail_rollback):
                results, errors = cli._handle_add(args)
        self.assertEqual(results[0]["ok"], False)
        self.assertEqual(errors[0].code, "rollback_failed")
        self.assertIn("source", errors[0].details)
        self.assertIn("trashed_path", errors[0].details)

    def test_restore_exdev_leaves_payload_and_ledger_unchanged(self) -> None:
        self.init_storage()
        source = self.workspace / "restore-exdev.txt"
        source.write_text("content", encoding="utf-8")
        code, added = run_cli(self.storage, "add", "--", str(source))
        self.assertEqual(code, 0, added)
        entry_id = added["results"][0]["entry_id"]
        payload = Path(added["results"][0]["trashed_path"])
        import safe_delete.cli as cli
        import safe_delete.restore as restore
        from safe_delete.errors import SafeDeleteError

        with patch.object(
            restore,
            "atomic_move",
            side_effect=SafeDeleteError("cross_device", "injected EXDEV"),
        ):
            args = Namespace(
                root=str(self.storage), entry_id=entry_id, restore_to=None,
                create_parents=False,
            )
            results, errors = cli._handle_restore(args)
            code = errors[0].exit_code if errors else 0
            failed = {"errors": [item.as_dict() for item in errors], "results": results}
        self.assertEqual(code, 2, failed)
        self.assertEqual(failed["errors"][0]["code"], "cross_device")
        self.assertTrue(payload.is_file())
        self.assertFalse(source.exists())
        self.assertEqual(len((self.storage / "ledger.jsonl").read_text().splitlines()), 1)

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
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
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
