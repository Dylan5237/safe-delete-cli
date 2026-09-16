from __future__ import annotations

import json
import contextlib
import errno
import io
import os
import stat
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

    def test_orphan_listing_preserves_ledger_failure_during_reconciliation(self) -> None:
        self.init_storage()
        orphan_id = "550e8400-e29b-41d4-a716-446655440000"
        orphan_payload = self.storage / "trash" / "objects" / orphan_id / "payload"
        orphan_payload.parent.mkdir()
        orphan_payload.write_text("orphan", encoding="utf-8")

        import safe_delete.audit as audit
        import safe_delete.cli as cli
        from safe_delete.errors import SafeDeleteError

        injected = SafeDeleteError("ledger_failure", "ledger became unreadable")
        args = Namespace(
            root=str(self.storage), all=False, orphans=True,
            project=None, original=None,
        )
        with patch.object(audit, "read_ledger_lines", side_effect=injected):
            results, errors = cli._handle_list(args)
        self.assertEqual(results, [])
        self.assertEqual([item.code for item in errors], ["ledger_failure", "orphan_payload"])

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

    def test_p2_trash_and_restore_records_reject_error_code(self) -> None:
        self.init_storage()
        source = self.workspace / "error-code.txt"
        source.write_text("content", encoding="utf-8")
        code, added = run_cli(self.storage, "add", "--", str(source))
        self.assertEqual(code, 0, added)
        ledger = self.storage / "ledger.jsonl"
        trash_record = json.loads(ledger.read_text(encoding="utf-8"))

        trash_record["error_code"] = "purge_remove_failed"
        ledger.write_text(json.dumps(trash_record) + "\n", encoding="utf-8")
        code, invalid_trash = run_cli(self.storage, "list")
        self.assertEqual(code, 4, invalid_trash)
        self.assertEqual(invalid_trash["errors"][0]["code"], "malformed_ledger")

        trash_record.pop("error_code")
        restore_record = {
            **trash_record,
            "event_id": str(uuid.uuid4()),
            "operation": "restore",
            "state": "restored",
            "restore_path": str(source),
            "error_code": "purge_remove_failed",
        }
        ledger.write_text(
            json.dumps(trash_record) + "\n" + json.dumps(restore_record) + "\n",
            encoding="utf-8",
        )
        code, invalid_restore = run_cli(self.storage, "list")
        self.assertEqual(code, 4, invalid_restore)
        self.assertEqual(invalid_restore["errors"][0]["code"], "malformed_ledger")

    def test_orphan_listing_preserves_malformed_ledger_errors(self) -> None:
        self.init_storage()
        orphan_id = "550e8400-e29b-41d4-a716-446655440000"
        orphan_payload = self.storage / "trash" / "objects" / orphan_id / "payload"
        orphan_payload.parent.mkdir()
        orphan_payload.write_text("orphan", encoding="utf-8")
        with (self.storage / "ledger.jsonl").open("a", encoding="utf-8") as ledger:
            ledger.write("{malformed\n")

        code, payload = run_cli(self.storage, "list", "--orphans")
        self.assertEqual(code, 4, payload)
        self.assertEqual(
            [item["code"] for item in payload["errors"]],
            ["malformed_ledger", "orphan_payload"],
        )

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
        partial = next(item for item in payload["errors"] if item["code"] == "partial_failure")
        self.assertEqual(partial["succeeded"], 1)
        self.assertEqual(partial["failed"], 1)

    def test_fallback_collision_does_not_overwrite_racing_destination(self) -> None:
        import safe_delete.move as move
        from safe_delete.errors import SafeDeleteError

        source = self.workspace / "source.txt"
        destination = self.workspace / "destination.txt"
        source.write_text("source", encoding="utf-8")

        with patch.object(move, "_renameat2_noreplace", return_value=move._NO_REPLACE_UNAVAILABLE):
            with patch.object(move.os, "link") as link:
                with self.assertRaises(SafeDeleteError) as raised:
                    move.atomic_move(source, destination)
        self.assertEqual(raised.exception.code, "storage_failure")
        link.assert_not_called()
        self.assertEqual(source.read_text(encoding="utf-8"), "source")
        self.assertFalse(destination.exists())

    def test_add_storage_failure_still_emits_one_result_per_input(self) -> None:
        self.storage.write_text("not a directory", encoding="utf-8")
        first = self.workspace / "first.txt"
        second = self.workspace / "second.txt"
        first.write_text("first", encoding="utf-8")
        second.write_text("second", encoding="utf-8")

        code, payload = run_cli(self.storage, "add", "--", str(first), str(second))
        self.assertEqual(code, 4, payload)
        self.assertEqual(len(payload["results"]), 2)
        self.assertTrue(all(not result["ok"] for result in payload["results"]))
        self.assertEqual([item["code"] for item in payload["errors"]], ["storage_failure"])
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())

    def test_add_rejects_source_replaced_by_fifo_after_inspection(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("mkfifo is unavailable")
        self.init_storage()
        source = self.workspace / "replaced.txt"
        source.write_text("original", encoding="utf-8")
        import safe_delete.cli as cli

        real_inspect = cli.inspect_source

        def inspect_then_replace(layout: object, path: str) -> object:
            info = real_inspect(layout, path)
            os.unlink(path)
            os.mkfifo(path)
            return info

        args = Namespace(
            root=str(self.storage), paths=[str(source)], dry_run=False,
            reason=None, project=None, session_id=None, agent=None, tool=None,
        )
        with patch.object(cli, "inspect_source", side_effect=inspect_then_replace):
            results, errors = cli._handle_add(args)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertEqual(errors[0].code, "storage_failure")
        self.assertTrue(stat.S_ISFIFO(os.lstat(source).st_mode))
        self.assertEqual((self.storage / "ledger.jsonl").read_text(), "")
        self.assertEqual(list((self.storage / "trash" / "objects").iterdir()), [])

    def test_move_rejects_replacement_between_source_check_and_rename(self) -> None:
        if not hasattr(os, "mkfifo"):
            self.skipTest("mkfifo is unavailable")
        import safe_delete.move as move
        from safe_delete.errors import SafeDeleteError

        source = self.workspace / "rename-race.txt"
        destination = self.workspace / "rename-race-destination"
        source.write_text("original", encoding="utf-8")
        real_rename = move._renameat2_noreplace

        def replace_before_rename(
            source_parent_fd: int,
            source_name: str,
            destination_parent_fd: int,
            destination_name: str,
        ) -> bool | object:
            os.unlink(source_name, dir_fd=source_parent_fd)
            os.mkfifo(source_name, dir_fd=source_parent_fd)
            return real_rename(
                source_parent_fd,
                source_name,
                destination_parent_fd,
                destination_name,
            )

        with patch.object(move, "_renameat2_noreplace", side_effect=replace_before_rename):
            with self.assertRaises(SafeDeleteError) as raised:
                move.atomic_move(
                    source,
                    destination,
                    expected_source_stat=os.lstat(source),
                    expected_source_kind="file",
                )
        self.assertEqual(raised.exception.code, "storage_failure")
        self.assertFalse(source.exists())
        self.assertTrue(stat.S_ISFIFO(os.lstat(destination).st_mode))

    def test_add_ledger_symlink_replacement_fails_closed_without_external_append(self) -> None:
        self.init_storage()
        source = self.workspace / "ledger-race.txt"
        source.write_text("content", encoding="utf-8")
        external = self.workspace / "external-ledger.jsonl"
        external.write_text("sentinel\n", encoding="utf-8")
        ledger_path = self.storage / "ledger.jsonl"

        import safe_delete.cli as cli

        real_move = cli.atomic_move
        calls = 0

        def move_then_replace_ledger(src: str, dst: str, **kwargs: object) -> None:
            nonlocal calls
            calls += 1
            real_move(src, dst, **kwargs)
            if calls == 1:
                ledger_path.unlink()
                ledger_path.symlink_to(external)

        args = Namespace(
            root=str(self.storage), paths=[str(source)], dry_run=False,
            reason=None, project=None, session_id=None, agent=None, tool=None,
        )
        with patch.object(cli, "atomic_move", side_effect=move_then_replace_ledger):
            results, errors = cli._handle_add(args)
        self.assertEqual(results[0]["ok"], False)
        self.assertEqual(errors[0].code, "ledger_failure")
        self.assertEqual(external.read_text(encoding="utf-8"), "sentinel\n")
        self.assertTrue(source.is_file())
        self.assertTrue(ledger_path.is_symlink())

    def test_lock_symlink_is_rejected_before_flock(self) -> None:
        self.init_storage()
        lock_path = self.storage / "locks" / "ledger.lock"
        external = self.workspace / "external-lock"
        external.write_text("sentinel", encoding="utf-8")
        lock_path.unlink()
        lock_path.symlink_to(external)

        from safe_delete.errors import SafeDeleteError
        from safe_delete.storage import layout_for, ledger_lock

        with self.assertRaises(SafeDeleteError) as raised:
            with ledger_lock(layout_for(str(self.storage)), exclusive=True):
                pass
        self.assertEqual(raised.exception.code, "ledger_failure")
        self.assertEqual(external.read_text(encoding="utf-8"), "sentinel")

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

    def test_restore_parent_creation_rejects_symlink_race(self) -> None:
        self.init_storage()
        source = self.workspace / "source.txt"
        source.write_text("content", encoding="utf-8")
        code, add_payload = run_cli(self.storage, "add", "--", str(source))
        self.assertEqual(code, 0, add_payload)
        entry_id = add_payload["results"][0]["entry_id"]
        payload = Path(add_payload["results"][0]["trashed_path"])
        target = self.workspace / "raced" / "nested" / "target.txt"
        external = self.workspace / "external"
        external.mkdir()

        import safe_delete.cli as cli
        import safe_delete.restore as restore

        planted = False

        def plant_symlink(parent_fd: int, name: str) -> None:
            nonlocal planted
            # Adversary occupies the first-missing component name with a
            # symlink in the exact staging-to-publish window.
            if name == "raced" and not planted:
                (self.workspace / "raced").symlink_to(external, target_is_directory=True)
                planted = True

        args = Namespace(
            root=str(self.storage), entry_id=entry_id, restore_to=str(target),
            create_parents=True,
        )
        with patch.object(restore, "_before_publish_hook", side_effect=plant_symlink):
            results, errors = cli._handle_restore(args)
        self.assertTrue(planted)
        self.assertEqual(results, [])
        self.assertEqual(errors[0].code, "storage_failure")
        self.assertTrue(payload.is_file())
        self.assertEqual(len((self.storage / "ledger.jsonl").read_text().splitlines()), 1)
        raced = self.workspace / "raced"
        self.assertTrue(raced.is_symlink())
        self.assertFalse((external / "nested").exists())
        self.assertFalse(target.exists())

    def test_restore_parent_creation_rejects_real_directory_replacement(self) -> None:
        self.init_storage()
        source = self.workspace / "real-race-source.txt"
        source.write_text("content", encoding="utf-8")
        code, add_payload = run_cli(self.storage, "add", "--", str(source))
        self.assertEqual(code, 0, add_payload)
        entry_id = add_payload["results"][0]["entry_id"]
        payload = Path(add_payload["results"][0]["trashed_path"])
        target = self.workspace / "real-raced" / "nested" / "target.txt"

        import safe_delete.cli as cli
        import safe_delete.restore as restore

        replaced = False

        def plant_real_directory(parent_fd: int, name: str) -> None:
            nonlocal replaced
            # Adversary substitutes a real directory at the first-missing
            # component name after the new parent was created but before its
            # identity can be bound at the destination pathname.
            if name == "real-raced" and not replaced:
                (self.workspace / "real-raced").mkdir()
                replaced = True

        args = Namespace(
            root=str(self.storage), entry_id=entry_id, restore_to=str(target),
            create_parents=True,
        )
        with patch.object(restore, "_before_publish_hook", side_effect=plant_real_directory):
            results, errors = cli._handle_restore(args)
        self.assertTrue(replaced)
        self.assertEqual(results, [])
        self.assertEqual(errors[0].code, "storage_failure")
        self.assertIn("refusing to adopt", errors[0].message)
        self.assertTrue(payload.is_file())
        self.assertEqual(len((self.storage / "ledger.jsonl").read_text().splitlines()), 1)
        self.assertTrue((self.workspace / "real-raced").is_dir())
        self.assertFalse((self.workspace / "real-raced" / "nested").exists())
        self.assertFalse(target.exists())
        staging = self.storage / "trash" / "staging"
        if staging.exists():
            self.assertEqual(list(staging.iterdir()), [])

    def test_restore_append_failure_human_output_includes_restore_and_trash_paths(self) -> None:
        self.init_storage()
        source = self.workspace / "append-failure-restore.txt"
        source.write_text("content", encoding="utf-8")
        code, add_payload = run_cli(self.storage, "add", "--", str(source))
        self.assertEqual(code, 0, add_payload)
        entry_id = add_payload["results"][0]["entry_id"]
        payload = Path(add_payload["results"][0]["trashed_path"])

        import safe_delete.cli as cli
        import safe_delete.restore as restore
        from safe_delete.errors import SafeDeleteError

        args = Namespace(
            root=str(self.storage), entry_id=entry_id, restore_to=None,
            create_parents=False,
        )
        injected = SafeDeleteError("ledger_failure", "restore append blocked")
        with patch.object(restore, "append_event", side_effect=injected):
            results, errors = cli._handle_restore(args)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = cli._emit("restore", results, errors, False)
        self.assertEqual(code, 4)
        self.assertEqual(results, [])
        self.assertEqual(errors[0].code, "ledger_failure")
        self.assertIn(f"restore path: {source}", stderr.getvalue())
        self.assertIn(f"trash path: {payload}", stderr.getvalue())
        self.assertFalse(source.exists())
        self.assertTrue(payload.is_file())

    def test_restore_rollback_preserves_replaced_parent_directory(self) -> None:
        self.init_storage()
        source = self.workspace / "rollback-parent-source.txt"
        source.write_text("content", encoding="utf-8")
        code, add_payload = run_cli(self.storage, "add", "--", str(source))
        self.assertEqual(code, 0, add_payload)
        entry_id = add_payload["results"][0]["entry_id"]
        payload = Path(add_payload["results"][0]["trashed_path"])
        target = self.workspace / "rollback-raced" / "nested" / "target.txt"
        parked = self.workspace / "parked-rollback-race"
        parked.mkdir()

        import safe_delete.cli as cli
        import safe_delete.restore as restore
        from safe_delete.errors import SafeDeleteError

        injected = SafeDeleteError("ledger_failure", "restore append blocked")

        def replace_before_append(layout: object, record: dict[str, object]) -> None:
            created = self.workspace / "rollback-raced"
            os.rename(created, parked / "rollback-raced")
            created.mkdir()
            raise injected

        args = Namespace(
            root=str(self.storage), entry_id=entry_id, restore_to=str(target),
            create_parents=True,
        )
        with patch.object(restore, "append_event", side_effect=replace_before_append):
            results, errors = cli._handle_restore(args)
        self.assertEqual(results, [])
        self.assertEqual(errors[0].code, "rollback_failed")
        self.assertEqual(errors[0].details["cleanup_error"], "storage_failure")
        self.assertTrue(errors[0].details["cleanup_preserved"])
        self.assertTrue(payload.is_file())
        self.assertEqual(len((self.storage / "ledger.jsonl").read_text().splitlines()), 1)
        self.assertTrue((self.workspace / "rollback-raced").is_dir())
        self.assertTrue((parked / "rollback-raced").is_dir())
        self.assertFalse((self.workspace / "rollback-raced" / "nested").exists())
        self.assertFalse((self.workspace / "rollback-raced" / "nested" / "target.txt").exists())
        self.assertFalse((parked / "rollback-raced" / "nested" / "target.txt").exists())

    def test_restore_cleanup_preserves_replacement_at_reclaim_window(self) -> None:
        self.init_storage()
        source = self.workspace / "cleanup-race-source.txt"
        source.write_text("content", encoding="utf-8")
        code, add_payload = run_cli(self.storage, "add", "--", str(source))
        self.assertEqual(code, 0, add_payload)
        entry_id = add_payload["results"][0]["entry_id"]
        payload = Path(add_payload["results"][0]["trashed_path"])
        target = self.workspace / "cleanup-raced" / "nested" / "target.txt"
        parked = self.workspace / "parked-cleanup-race"
        parked.mkdir()

        import safe_delete.cli as cli
        import safe_delete.restore as restore
        from safe_delete.errors import SafeDeleteError

        injected = SafeDeleteError("ledger_failure", "restore append blocked")
        replaced = False

        def replace_at_reclaim(parent_fd: int, name: str) -> None:
            nonlocal replaced
            # Adversary swaps the created parent for an unrelated replacement
            # after cleanup resolved its identity, immediately before any
            # removal. The marker file proves the replacement is never
            # deleted, not even partially.
            current = self.workspace / "cleanup-raced"
            if name == "cleanup-raced" and not replaced:
                os.rename(current, parked / "cleanup-raced")
                current.mkdir()
                (current / "attacker-marker.txt").write_text("keep me", encoding="utf-8")
                replaced = True

        args = Namespace(
            root=str(self.storage), entry_id=entry_id, restore_to=str(target),
            create_parents=True,
        )
        with patch.object(restore, "append_event", side_effect=injected):
            with patch.object(
                restore,
                "_before_cleanup_reclaim_hook",
                side_effect=replace_at_reclaim,
            ):
                results, errors = cli._handle_restore(args)
        self.assertTrue(replaced)
        self.assertEqual(results, [])
        self.assertEqual(errors[0].code, "rollback_failed")
        self.assertEqual(errors[0].details["cleanup_error"], "storage_failure")
        self.assertTrue(errors[0].details["cleanup_preserved"])
        self.assertTrue(payload.is_file())
        self.assertEqual(len((self.storage / "ledger.jsonl").read_text().splitlines()), 1)
        self.assertEqual(
            (self.workspace / "cleanup-raced" / "attacker-marker.txt").read_text(
                encoding="utf-8"
            ),
            "keep me",
        )
        self.assertTrue((parked / "cleanup-raced").is_dir())
        self.assertFalse((self.workspace / "cleanup-raced" / "nested").exists())
        self.assertFalse(target.exists())
        staging = self.storage / "trash" / "staging"
        if staging.exists():
            self.assertEqual(list(staging.iterdir()), [])

    def test_restore_create_parents_leaves_no_staging_litter(self) -> None:
        self.init_storage()
        source = self.workspace / "hygiene-source.txt"
        source.write_text("content", encoding="utf-8")
        code, add_payload = run_cli(self.storage, "add", "--", str(source))
        self.assertEqual(code, 0, add_payload)
        entry_id = add_payload["results"][0]["entry_id"]
        target = self.workspace / "made" / "nested" / "target.txt"

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
        self.assertEqual(
            [str(path) for path in (self.workspace / "made").rglob(".safe-delete-*")],
            [],
        )
        staging = self.storage / "trash" / "staging"
        self.assertTrue(staging.is_dir())
        self.assertEqual(list(staging.iterdir()), [])

    def test_restore_explicit_empty_destination_is_usage_error(self) -> None:
        self.init_storage()
        source = self.workspace / "empty-destination.txt"
        source.write_text("content", encoding="utf-8")
        code, add_payload = run_cli(self.storage, "add", "--", str(source))
        self.assertEqual(code, 0, add_payload)
        entry_id = add_payload["results"][0]["entry_id"]
        payload = Path(add_payload["results"][0]["trashed_path"])
        ledger_before = (self.storage / "ledger.jsonl").read_text()

        code, failed = run_cli(self.storage, "restore", "--to", "", entry_id)
        self.assertEqual(code, 2, failed)
        self.assertEqual(failed["errors"][0]["code"], "usage_error")
        self.assertEqual(failed["results"], [])
        self.assertEqual((self.storage / "ledger.jsonl").read_text(), ledger_before)
        self.assertTrue(payload.is_file())
        self.assertFalse(source.exists())

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
