from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from safe_delete.hook import (
    OUT_OF_COVERAGE_BYPASSES,
    decide_request,
    execute_request,
    hook_disable,
    hook_install,
    hook_registry_path,
    hook_status,
    hook_uninstall,
    package_paths,
)
from safe_delete.storage import initialize_layout


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CLI = REPOSITORY_ROOT / "safe-delete"


class RecordingRunner:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[tuple[list[str], str, dict[str, str]]] = []

    def __call__(self, argv: list[str], *, cwd: str, env: dict[str, str]) -> SimpleNamespace:
        self.calls.append((argv, cwd, env))
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


class HookEnforcementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="safe-delete-hook-test-")
        self.base = Path(self.temp_dir.name)
        self.workspace = self.base / "workspace"
        self.workspace.mkdir()
        self.storage = self.base / "storage"
        self.environment = {
            "HOME": str(self.base / "home"),
            "XDG_DATA_HOME": str(self.base / "data"),
            "XDG_CONFIG_HOME": str(self.base / "config"),
            "SAFE_DELETE_ROOT": str(self.storage),
        }
        self.env_patch = patch.dict(os.environ, self.environment, clear=False)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)

    def request(self, argv: list[str], **context: object) -> dict[str, object]:
        value: dict[str, object] = {
            "protocol_version": 1,
            "request_id": "req-test",
            "tool": "shell",
            "argv": argv,
            "cwd": str(self.workspace),
        }
        value.update(context)
        return value

    def test_supported_vectors_have_one_exact_rewrite(self) -> None:
        cases = [
            (["rm", "item"], ["item"]),
            (["rm", "-r", "item"], ["item"]),
            (["rm", "-R", "-f", "item"], ["item"]),
            (["rm", "-rf", "item"], ["item"]),
            (["rm", "--", "-looks-like-an-option"], ["-looks-like-an-option"]),
            (["rm", "--", "--"], ["--"]),
            (["unlink", "one", "two"], ["one", "two"]),
            (["unlink", "--", "-one"], ["-one"]),
            (["rmdir", "directory"], ["directory"]),
            (["rmdir", "--", "-directory"], ["-directory"]),
        ]
        for argv, operands in cases:
            with self.subTest(argv=argv):
                response = decide_request(self.request(argv))
                self.assertEqual(response["decision"], "route")
                self.assertEqual(response["reason_code"], "raw_delete")
                self.assertEqual(
                    response["safe_delete_argv"],
                    [
                        "safe-delete",
                        "add",
                        "--tool",
                        "pretooluse:shell",
                        "--",
                        *[str(self.workspace / operand) for operand in operands],
                    ],
                )
                self.assertNotIn("-r", response["safe_delete_argv"])
                self.assertNotIn("-R", response["safe_delete_argv"])
                self.assertNotIn("-f", response["safe_delete_argv"])

    def test_metadata_is_mapped_without_inventing_identity(self) -> None:
        response = decide_request(
            self.request(
                ["rm", "-f", "item"],
                project=str(self.workspace),
                session_id="session-1",
                agent="codex/luna",
                reason="remove generated item",
                extensions={"example.org/trace": {"source": "test"}},
            )
        )
        self.assertEqual(
            response["safe_delete_argv"],
            [
                "safe-delete",
                "add",
                "--project",
                str(self.workspace),
                "--session-id",
                "session-1",
                "--agent",
                "codex/luna",
                "--reason",
                "remove generated item",
                "--extensions",
                '{"example.org/trace":{"source":"test"}}',
                "--tool",
                "pretooluse:shell",
                "--",
                str(self.workspace / "item"),
            ],
        )
        missing_identity = decide_request(self.request(["rm", "item"], reason="provided"))
        self.assertNotIn("--session-id", missing_identity["safe_delete_argv"])
        self.assertNotIn("--agent", missing_identity["safe_delete_argv"])

    def test_probes_and_already_safe_delete_pass_through(self) -> None:
        cases = [
            ["rm"],
            ["rm", "-f"],
            ["rm", "--help"],
            ["rm", "--version"],
            ["unlink"],
            ["unlink", "--"],
            ["rmdir"],
            ["rmdir", "--help"],
            ["safe-delete", "add", "--", str(self.workspace / "item")],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                response = decide_request(self.request(argv))
                self.assertEqual(response["decision"], "passthrough")
                expected_reason = "safe_delete_add" if argv[:2] == ["safe-delete", "add"] else "non_delete_probe"
                self.assertEqual(response["reason_code"], expected_reason)
                self.assertNotIn("safe_delete_argv", response)

    def test_unsupported_or_ambiguous_vectors_deny(self) -> None:
        cases = [
            ["rm", "-i", "item"],
            ["rm", "-rfv", "item"],
            ["rm", "item", "-f"],
            ["rm", "-item"],
            ["unlink", "-f", "item"],
            ["rmdir", "-p", "directory"],
            ["sudo", "rm", "item"],
            ["/bin/rm", "item"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                response = decide_request(self.request(argv))
                self.assertEqual(response["decision"], "deny")
                self.assertEqual(response["reason_code"], "unsupported_delete_invocation")

    def test_malformed_required_context_denies_with_echo_when_possible(self) -> None:
        missing_cwd = self.request(["rm", "item"])
        del missing_cwd["cwd"]
        response = decide_request(missing_cwd)
        self.assertEqual(response["decision"], "deny")
        self.assertEqual(response["reason_code"], "unsupported_delete_invocation")
        self.assertEqual(response["request_id"], "req-test")

        wrong_version = self.request(["rm", "item"], protocol_version=2)
        response = decide_request(wrong_version)
        self.assertEqual(response["protocol_version"], 2)
        self.assertEqual(response["request_id"], "req-test")
        self.assertEqual(response["reason_code"], "unsupported_delete_invocation")

        invalid_extensions = self.request(["rm", "item"], extensions=["not", "an", "object"])
        self.assertEqual(decide_request(invalid_extensions)["reason_code"], "unsupported_delete_invocation")

    def test_execute_routes_once_and_never_retries_raw_command(self) -> None:
        initialize_layout(str(self.storage))
        hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(CLI), root=str(self.storage))
        runner = RecordingRunner()
        response = execute_request(
            self.request(["rm", "-rf", "item"]),
            cli_path=str(CLI),
            runner=runner,
        )
        self.assertEqual(response.response["decision"], "route")
        self.assertTrue(response.executed)
        self.assertEqual(len(runner.calls), 1)
        child_argv, child_cwd, _ = runner.calls[0]
        self.assertEqual(child_cwd, str(self.workspace))
        self.assertEqual(
            child_argv,
            ["safe-delete", "add", "--tool", "pretooluse:shell", "--", str(self.workspace / "item")],
        )

    def test_nonzero_cli_is_denied_and_has_no_raw_fallback(self) -> None:
        initialize_layout(str(self.storage))
        hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(CLI), root=str(self.storage))
        runner = RecordingRunner(
            returncode=2,
            stderr="safe-delete: source_not_found: source does not exist",
        )
        response = execute_request(
            self.request(["rm", "item"]),
            cli_path=str(CLI),
            runner=runner,
        )
        self.assertEqual(response.response["decision"], "deny")
        self.assertEqual(response.response["reason_code"], "source_not_found")
        self.assertEqual(response.exit_code, 2)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0][0], "safe-delete")

    def test_cross_device_cli_error_is_propagated_without_raw_fallback(self) -> None:
        initialize_layout(str(self.storage))
        hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(CLI), root=str(self.storage))
        runner = RecordingRunner(
            returncode=2,
            stderr="safe-delete: cross_device: source and trash are on different filesystems",
        )
        response = execute_request(
            self.request(["rm", "item"]),
            cli_path=str(CLI),
            runner=runner,
        )
        self.assertEqual(response.response["decision"], "deny")
        self.assertEqual(response.response["reason_code"], "cross_device")
        self.assertEqual(response.exit_code, 2)
        self.assertEqual(len(runner.calls), 1)

    def test_unavailable_cli_and_storage_fail_closed_before_child(self) -> None:
        initialize_layout(str(self.storage))
        hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(CLI), root=str(self.storage))
        runner = RecordingRunner()
        unavailable_cli = execute_request(
            self.request(["rm", "item"]),
            cli_path=str(self.base / "missing-safe-delete"),
            runner=runner,
        )
        self.assertEqual(unavailable_cli.response["reason_code"], "cli_unavailable")
        self.assertFalse(unavailable_cli.executed)
        self.assertEqual(runner.calls, [])

        no_storage = self.base / "not-initialized"
        with patch.dict(os.environ, {"SAFE_DELETE_ROOT": str(no_storage)}, clear=False):
            storage_failure = execute_request(
                self.request(["rm", "item"]),
                cli_path=str(CLI),
                runner=runner,
            )
        self.assertEqual(storage_failure.response["reason_code"], "storage_unavailable")
        self.assertFalse(storage_failure.executed)
        self.assertEqual(runner.calls, [])

    def test_unregistered_or_disabled_integration_denies_raw_route(self) -> None:
        initialize_layout(str(self.storage))
        runner = RecordingRunner()
        unregistered = execute_request(
            self.request(["rm", "item"]),
            cli_path=str(CLI),
            runner=runner,
        )
        self.assertEqual(unregistered.response["reason_code"], "unsupported_delete_invocation")
        self.assertFalse(unregistered.executed)
        self.assertEqual(runner.calls, [])

        hook_install("path-shim", cli_path=str(CLI), root=str(self.storage))
        hook_disable("path-shim", root=str(self.storage))
        disabled = execute_request(
            self.request(["rm", "item"]),
            adapter="path-shim",
            command="rm",
            cli_path=str(CLI),
            runner=runner,
        )
        self.assertEqual(disabled.response["reason_code"], "unsupported_delete_invocation")
        self.assertFalse(disabled.executed)
        self.assertEqual(runner.calls, [])

    def test_direct_safe_delete_add_is_passed_through_once(self) -> None:
        initialize_layout(str(self.storage))
        runner = RecordingRunner()
        argv = ["safe-delete", "add", "--", str(self.workspace / "item")]
        response = execute_request(
            self.request(argv),
            runner=runner,
        )
        self.assertEqual(response.response["reason_code"], "safe_delete_add")
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0], argv)

    def test_passthrough_runner_is_called_exactly_once(self) -> None:
        initialize_layout(str(self.storage))
        runner = RecordingRunner()
        response = execute_request(
            self.request(["rm", "--help"]),
            runner=runner,
        )
        self.assertEqual(response.response["decision"], "passthrough")
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0], ["rm", "--help"])

    def test_installed_path_shim_moves_once_and_records_one_entry(self) -> None:
        initialize_layout(str(self.storage))
        hook_install("path-shim", cli_path=str(CLI), root=str(self.storage))
        target = self.workspace / "item"
        target.write_text("payload", encoding="utf-8")
        shim_dir = package_paths()["bin"]
        env = dict(os.environ)
        env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")
        completed = subprocess.run(
            [str(shim_dir / "rm"), "-f", str(target)],
            cwd=str(self.workspace),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(target.exists())
        lines = (self.storage / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)

    def test_all_installed_path_shims_route_supported_forms(self) -> None:
        initialize_layout(str(self.storage))
        hook_install("path-shim", cli_path=str(CLI), root=str(self.storage))
        shim_dir = package_paths()["bin"]
        env = dict(os.environ)
        env["PATH"] = str(shim_dir) + os.pathsep + env.get("PATH", "")

        rm_target = self.workspace / "rm-target"
        rm_target.write_text("rm", encoding="utf-8")
        unlink_target = self.workspace / "unlink-target"
        unlink_target.write_text("unlink", encoding="utf-8")
        directory = self.workspace / "rmdir-target"
        directory.mkdir()
        (directory / "child").write_text("child", encoding="utf-8")

        commands = (
            ("rm", ["-R", "--", str(rm_target)]),
            ("unlink", [str(unlink_target)]),
            ("rmdir", [str(directory)]),
        )
        for command, arguments in commands:
            with self.subTest(command=command):
                completed = subprocess.run(
                    [str(shim_dir / command), *arguments],
                    cwd=str(self.workspace),
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(rm_target.exists())
        self.assertFalse(unlink_target.exists())
        self.assertFalse(directory.exists())
        lines = (self.storage / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 3)

    def test_path_shim_context_maps_identity_and_metadata(self) -> None:
        from safe_delete.hook import path_shim_request

        request = path_shim_request(
            "unlink",
            ["/owned/bin/unlink", "item"],
            cwd=str(self.workspace),
            environ={
                "SAFE_DELETE_PROJECT": str(self.workspace),
                "SAFE_DELETE_SESSION_ID": "session-2",
                "SAFE_DELETE_AGENT": "agent-2",
            },
        )
        request["request_id"] = "shim-test"
        response = decide_request(request, adapter="path-shim", command="unlink")
        self.assertEqual(
            response["safe_delete_argv"],
            [
                "safe-delete",
                "add",
                "--project",
                str(self.workspace),
                "--session-id",
                "session-2",
                "--agent",
                "agent-2",
                "--tool",
                "path-shim:unlink",
                "--",
                str(self.workspace / "item"),
            ],
        )

    def test_install_status_disable_uninstall_are_idempotent_and_scoped(self) -> None:
        initialize_layout(str(self.storage))
        ledger_before = (self.storage / "ledger.jsonl").read_bytes()
        first = hook_install("path-shim", cli_path=str(CLI), root=str(self.storage))
        second = hook_install("rm-shim", cli_path=str(CLI), root=str(self.storage))
        self.assertTrue(first["enabled"])
        self.assertFalse(second["changed"])
        self.assertEqual(len(list(package_paths()["bin"].iterdir())), 3)

        shim_dir = package_paths()["bin"]
        with patch.dict(os.environ, {"PATH": str(shim_dir) + os.pathsep + os.environ.get("PATH", "")}, clear=False):
            status = hook_status("path-shim", root=str(self.storage))[0]
        self.assertTrue(status["enforced"])
        self.assertEqual(status["package"]["version"], "v1")
        self.assertEqual(status["out_of_coverage"], list(OUT_OF_COVERAGE_BYPASSES))
        self.assertEqual(status["boundary"]["prepend_path"], str(shim_dir))

        disabled = hook_disable("path-shim", root=str(self.storage))
        disabled_again = hook_disable("rm-shim", root=str(self.storage))
        self.assertFalse(disabled["enabled"])
        self.assertTrue(disabled["raw_delete_outside_boundary"])
        self.assertFalse(disabled_again["changed"])
        self.assertTrue((shim_dir / "rm").exists())
        self.assertEqual((self.storage / "ledger.jsonl").read_bytes(), ledger_before)

        uninstalled = hook_uninstall("path-shim", root=str(self.storage))
        self.assertFalse(uninstalled["installed"])
        self.assertFalse((shim_dir / "rm").exists())
        uninstalled_again = hook_uninstall("rm-shim", root=str(self.storage))
        self.assertFalse(uninstalled_again["changed"])
        self.assertEqual((self.storage / "ledger.jsonl").read_bytes(), ledger_before)

    def test_status_is_honest_for_missing_and_explicitly_wrong_boundaries(self) -> None:
        missing = hook_status("claude", root=str(self.storage))[0]
        self.assertFalse(missing["installed"])
        self.assertFalse(missing["enforced"])

        initialize_layout(str(self.storage))
        configured = self.base / "claude-settings.json"
        other = self.base / "other-settings.json"
        hook_install("claude", config=str(configured), cli_path=str(CLI), root=str(self.storage))
        selected = hook_status("claude", config=str(other), root=str(self.storage))[0]
        self.assertEqual(selected["boundary"]["config_path"], str(other))
        self.assertFalse(selected["enforced"])

    def test_malformed_registered_entry_denies_without_child(self) -> None:
        initialize_layout(str(self.storage))
        hook_install("path-shim", cli_path=str(CLI), root=str(self.storage))
        registry = json.loads(hook_registry_path().read_text(encoding="utf-8"))
        registry["integrations"]["path-shim"]["protocol_version"] = 2
        hook_registry_path().write_text(json.dumps(registry), encoding="utf-8")

        runner = RecordingRunner()
        response = execute_request(
            self.request(["rm", "item"]),
            adapter="path-shim",
            command="rm",
            cli_path=str(CLI),
            runner=runner,
        )
        self.assertEqual(response.response["reason_code"], "unsupported_delete_invocation")
        self.assertFalse(response.executed)
        self.assertEqual(runner.calls, [])

    def test_claude_registration_preserves_unrelated_config_and_default_management_binding(self) -> None:
        initialize_layout(str(self.storage))
        config = self.base / "claude-settings.json"
        config.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}), encoding="utf-8")
        hook_install("claude", config=str(config), cli_path=str(CLI), root=str(self.storage))
        installed_config = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(installed_config["permissions"]["allow"], ["Bash(ls)"])
        self.assertEqual(len(installed_config["hooks"]["PreToolUse"]), 1)
        self.assertFalse(hook_install("claude", config=str(config), cli_path=str(CLI), root=str(self.storage))["changed"])

        status = hook_status("claude", root=str(self.storage))[0]
        self.assertTrue(status["enforced"])
        self.assertEqual(status["boundary"]["config_path"], str(config))

        hook_disable("claude", root=str(self.storage))
        disabled_config = json.loads(config.read_text(encoding="utf-8"))
        self.assertEqual(disabled_config["permissions"]["allow"], ["Bash(ls)"])
        self.assertEqual(disabled_config["hooks"]["PreToolUse"], [])
        hook_uninstall("claude", root=str(self.storage))
        self.assertFalse(package_paths()["pretooluse"].exists())

    def test_cursor_explicit_config_and_unparseable_host_fail_closed(self) -> None:
        initialize_layout(str(self.storage))
        cursor_config = self.base / "cursor-hooks.json"
        result = hook_install("cursor", config=str(cursor_config), cli_path=str(CLI), root=str(self.storage))
        self.assertEqual(result["boundary"]["config_path"], str(cursor_config))
        cursor_payload = json.loads(cursor_config.read_text(encoding="utf-8"))
        self.assertEqual(len(cursor_payload["hooks"]["preToolUse"]), 1)
        hook_uninstall("cursor", config=str(cursor_config), root=str(self.storage))

        broken_config = self.base / "broken.json"
        broken_config.write_text("{", encoding="utf-8")
        from safe_delete.errors import SafeDeleteError

        with self.assertRaises(SafeDeleteError) as context:
            hook_install("claude", config=str(broken_config), cli_path=str(CLI), root=str(self.storage))
        self.assertEqual(context.exception.code, "storage_failure")
        self.assertFalse(package_paths()["pretooluse"].exists())
        registry = json.loads(hook_registry_path().read_text(encoding="utf-8"))
        self.assertNotIn("claude", registry["integrations"])

    def test_unwritable_ledger_fails_closed_without_child(self) -> None:
        initialize_layout(str(self.storage))
        hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(CLI), root=str(self.storage))
        ledger = self.storage / "ledger.jsonl"
        original_mode = ledger.stat().st_mode & 0o777
        ledger.chmod(0o400)
        try:
            runner = RecordingRunner()
            result = execute_request(
                self.request(["rm", "item"]),
                cli_path=str(CLI),
                runner=runner,
            )
            self.assertEqual(result.response["reason_code"], "storage_unavailable")
            self.assertEqual(runner.calls, [])
        finally:
            ledger.chmod(original_mode)

    def test_bypass_inventory_is_reported_as_out_of_coverage(self) -> None:
        self.assertGreaterEqual(len(OUT_OF_COVERAGE_BYPASSES), 10)
        for bypass in OUT_OF_COVERAGE_BYPASSES:
            with self.subTest(bypass=bypass):
                self.assertIsInstance(bypass, str)
        response = decide_request(self.request(["python", "-c", "import os; os.unlink('item')"]))
        self.assertEqual(response["reason_code"], "unsupported_delete_invocation")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
