from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from safe_delete.errors import SafeDeleteError
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
from safe_delete.metadata import EXTENSIONS_MAX_DEPTH
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

    def instrumented_cli(self) -> tuple[Path, Path]:
        """Return a real CLI wrapper and its one-line-per-call counter."""

        wrapper = self.base / "instrumented-safe-delete"
        counter = self.base / "safe-delete-calls.log"
        wrapper.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> {shlex.quote(str(counter))}\n"
            f"exec {shlex.quote(str(CLI))} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o700)
        return wrapper, counter

    def raw_sentinels(self) -> tuple[Path, Path]:
        """Install raw command sentinels that fail if a hook falls back."""

        directory = self.base / "raw-command-sentinels"
        directory.mkdir()
        marker = self.base / "raw-command-used.log"
        for command in ("rm", "unlink", "rmdir"):
            sentinel = directory / command
            sentinel.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' {command} >> {shlex.quote(str(marker))}\n"
                "exit 97\n",
                encoding="utf-8",
            )
            sentinel.chmod(0o700)
        return directory, marker

    def run_installed_pretooluse(
        self,
        request: dict[str, object],
        *,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [str(package_paths()["pretooluse"])],
            input=json.dumps(request).encode("utf-8"),
            cwd=str(self.workspace),
            env=environment,
            capture_output=True,
            check=False,
        )

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
            [str(CLI), "add", "--tool", "pretooluse:shell", "--", str(self.workspace / "item")],
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
        self.assertEqual(runner.calls[0][0][0], str(CLI))

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

    def test_install_rejects_storage_namespace_and_preserves_runtime_bytes(self) -> None:
        initialize_layout(str(self.storage))
        ledger = self.storage / "ledger.jsonl"
        lock = self.storage / "locks" / "ledger.lock"
        sentinel = self.storage / "trash" / "sentinel"
        ledger.write_bytes(b"ledger bytes\n")
        lock.write_bytes(b"lock bytes\n")
        sentinel.write_bytes(b"trash bytes\n")
        watched = (ledger, lock, sentinel)
        before = {path: path.read_bytes() for path in watched}

        with patch.dict(os.environ, {"XDG_DATA_HOME": str(self.storage / "trash")}, clear=False):
            with self.assertRaises(SafeDeleteError):
                hook_install("path-shim", cli_path=str(CLI), root=str(self.storage))

        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse((self.storage / "trash" / "safe-delete").exists())

        for reserved in (ledger, lock):
            with self.subTest(reserved=reserved):
                with self.assertRaises(SafeDeleteError):
                    hook_install("claude", config=str(reserved), cli_path=str(CLI), root=str(self.storage))
                self.assertEqual(ledger.read_bytes(), before[ledger])
                self.assertEqual(lock.read_bytes(), before[lock])
                self.assertEqual(sentinel.read_bytes(), before[sentinel])

    def test_default_paths_hook_install_succeeds(self) -> None:
        """Counterexample A: stock machine must not self-lock.

        ``SAFE_DELETE_ROOT`` and ``XDG_DATA_HOME`` are both unset so the default
        package root and the default storage root collapse to the *same*
        directory, which is exactly the configuration that used to fail closed
        with ``path_forbidden``.
        """

        disposable_home = self.base / "default-home"
        disposable_home.mkdir()
        default_env = {
            "HOME": str(disposable_home),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }
        with patch.dict(os.environ, default_env, clear=True):
            from safe_delete.storage import layout_for

            package = package_paths()
            storage = layout_for(None)
            self.assertEqual(
                package["root"],
                storage.root,
                "this test is only meaningful when the defaults collapse",
            )
            self.assertTrue(
                str(package["hooks"]).startswith(str(storage.root)),
                package["hooks"],
            )

            # Runtime namespaces stay forbidden even though the package root is
            # allowed to share the storage root.
            for reserved in (
                storage.trash,
                storage.trash / "objects",
                storage.ledger,
                storage.lock,
                storage.lock.parent,
            ):
                with self.subTest(reserved=str(reserved)):
                    with self.assertRaises(SafeDeleteError) as context:
                        hook_install("claude", config=str(reserved), cli_path=str(CLI))
                    self.assertEqual(context.exception.code, "path_forbidden")

            # The default-path install itself must succeed at both boundaries.
            claude = hook_install("claude", cli_path=str(CLI))
            self.assertTrue(claude["enabled"], claude)
            self.assertEqual(
                claude["boundary"]["config_path"],
                str(disposable_home / ".claude" / "settings.json"),
            )
            self.assertTrue(package["pretooluse"].exists())

            shim = hook_install("path-shim", cli_path=str(CLI))
            self.assertTrue(shim["enabled"], shim)
            self.assertEqual(len(list(package["bin"].iterdir())), 3)

            # Installing does not require the storage layer to exist yet, but
            # the boundary can only be *enforced* once it does.  Prove both
            # halves at the true default root.
            undeclared = hook_status("path-shim", root=None)[0]
            self.assertTrue(undeclared["installed"])
            self.assertFalse(undeclared["enforced"])
            self.assertEqual(
                undeclared["storage"]["root"],
                str(disposable_home / ".local" / "share" / "safe-delete"),
            )

            initialize_layout(None)
            shim_dir = disposable_home / ".local" / "share" / "safe-delete" / "bin"
            with patch.dict(
                os.environ,
                {"PATH": str(shim_dir) + os.pathsep + os.environ.get("PATH", "")},
                clear=False,
            ):
                status = hook_status("path-shim", root=None)[0]
            self.assertTrue(status["enforced"], status)
            self.assertEqual(status["boundary"]["shim_dir"], str(shim_dir))

    def test_runtime_namespaces_stay_forbidden_when_defaults_collapse(self) -> None:
        """The pre-fix blanket rejection of the storage root must not return."""

        disposable_home = self.base / "collapsed-home"
        disposable_home.mkdir()
        default_env = {
            "HOME": str(disposable_home),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }
        with patch.dict(os.environ, default_env, clear=True):
            from safe_delete.storage import layout_for

            storage = layout_for(None)
            # The package namespace under the storage root is writable...
            self.assertTrue(str(package_paths()["bin"]).startswith(str(storage.root)))
            result = hook_install("path-shim", cli_path=str(CLI))
            self.assertTrue(result["enabled"], result)
            # ...while the runtime ledger/trash/lock namespaces are not.
            ledger_before = (storage.ledger).read_bytes() if storage.ledger.exists() else None
            with self.assertRaises(SafeDeleteError) as context:
                hook_install("claude", config=str(storage.ledger), cli_path=str(CLI))
            self.assertEqual(context.exception.code, "path_forbidden")
            if ledger_before is None:
                self.assertFalse(storage.ledger.exists())
            else:
                self.assertEqual(storage.ledger.read_bytes(), ledger_before)

    def test_cursor_second_project_install_requires_explicit_target(self) -> None:
        """Counterexample B: a second project must never be a silent no-op.

        The registry keys a host by selector alone, so a default install from a
        different project used to adopt the *recorded* boundary and report
        ``changed: false`` while the new project stayed unprotected.
        """

        initialize_layout(str(self.storage))
        project_a = self.base / "project-a"
        project_b = self.base / "project-b"
        project_a.mkdir()
        project_b.mkdir()

        first = hook_install(
            "cursor",
            project=str(project_a),
            cli_path=str(CLI),
            root=str(self.storage),
        )
        config_a = project_a / ".cursor" / "hooks.json"
        config_b = project_b / ".cursor" / "hooks.json"
        self.assertEqual(first["boundary"]["config_path"], str(config_a))
        self.assertTrue(config_a.exists())
        self.assertEqual(
            len(json.loads(config_a.read_text(encoding="utf-8"))["hooks"]["preToolUse"]),
            1,
        )
        registry_before = hook_registry_path().read_bytes()

        original_cwd = os.getcwd()
        self.addCleanup(os.chdir, original_cwd)
        os.chdir(project_b)
        with self.assertRaises(SafeDeleteError) as context:
            hook_install("cursor", cli_path=str(CLI), root=str(self.storage))
        self.assertEqual(context.exception.code, "storage_failure")
        details = context.exception.as_dict()
        self.assertEqual(details["selector"], "cursor")
        self.assertEqual(details["recorded_config_path"], str(config_a))
        self.assertEqual(details["resolved_config_path"], str(config_b))
        self.assertIn("--project", details["message"])
        self.assertIn("--config", details["message"])

        # Nothing was created for project B and the recorded boundary is intact.
        self.assertFalse(config_b.exists())
        self.assertFalse((project_b / ".cursor").exists())
        self.assertEqual(hook_registry_path().read_bytes(), registry_before)
        self.assertEqual(
            hook_status("cursor", project=str(project_a), root=str(self.storage))[0]["boundary"][
                "config_path"
            ],
            str(config_a),
        )

        # An explicit target is the supported retarget spelling and is still
        # checked against the recorded boundary rather than silently adopted.
        with self.assertRaises(SafeDeleteError) as explicit:
            hook_install(
                "cursor",
                project=str(project_b),
                cli_path=str(CLI),
                root=str(self.storage),
            )
        self.assertEqual(explicit.exception.code, "storage_failure")
        self.assertFalse(config_b.exists())

        # Uninstalling the recorded integration first makes project B installable.
        hook_uninstall("cursor", project=str(project_a), root=str(self.storage))
        retargeted = hook_install(
            "cursor",
            project=str(project_b),
            cli_path=str(CLI),
            root=str(self.storage),
        )
        self.assertEqual(retargeted["boundary"]["config_path"], str(config_b))
        self.assertTrue(config_b.exists())

    def test_install_reports_checkout_pinning_and_world_writable_cli(self) -> None:
        initialize_layout(str(self.storage))

        # The repository this suite runs from is itself a checkout, so the
        # default install must say so rather than let the boundary silently
        # depend on a path that can move.
        checkout = hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(CLI), root=str(self.storage))
        self.assertTrue(
            any("git checkout" in warning for warning in checkout["install_warnings"]),
            checkout["install_warnings"],
        )
        self.assertTrue(
            any(str(REPOSITORY_ROOT) in warning for warning in checkout["install_warnings"]),
            checkout["install_warnings"],
        )

        # A world-writable CLI is called out: another user could replace the
        # command this boundary runs.
        loose_cli = self.base / "loose-safe-delete"
        loose_cli.write_bytes(CLI.read_bytes())
        loose_cli.chmod(0o777)
        hook_uninstall("claude", config=str(self.base / "claude.json"), root=str(self.storage))
        loose = hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(loose_cli), root=str(self.storage))
        self.assertEqual(loose["cli_path"], str(loose_cli))
        self.assertIn(
            f"registered CLI is world-writable: {loose_cli}",
            " ".join(loose["install_warnings"]),
            loose["install_warnings"],
        )

        # A tightly permissioned CLI produces no world-writable claim.
        tight_cli = self.base / "tight-safe-delete"
        tight_cli.write_bytes(CLI.read_bytes())
        tight_cli.chmod(0o755)
        hook_uninstall("claude", config=str(self.base / "claude.json"), root=str(self.storage))
        tight = hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(tight_cli), root=str(self.storage))
        self.assertFalse(
            any("world-writable" in warning for warning in tight["install_warnings"]),
            tight["install_warnings"],
        )

    def test_path_shim_activation_message_names_bin_and_recheck(self) -> None:
        initialize_layout(str(self.storage))
        result = hook_install("path-shim", cli_path=str(CLI), root=str(self.storage))
        self.assertEqual(
            result["path_activation"],
            f"prepend {package_paths()['bin']} to PATH, then re-check with "
            "`safe-delete hook status path-shim` or `safe-delete doctor`",
        )
        claude = hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(CLI), root=str(self.storage))
        self.assertIsNone(claude["path_activation"])

    def test_install_registry_failure_rolls_back_package_and_host_registration(self) -> None:
        initialize_layout(str(self.storage))
        config = self.base / "claude.json"
        failure = SafeDeleteError("storage_failure", "injected registry write failure")
        with patch("safe_delete.hook._write_registry", side_effect=failure):
            with self.assertRaises(SafeDeleteError):
                hook_install("claude", config=str(config), cli_path=str(CLI), root=str(self.storage))

        self.assertFalse(config.exists())
        self.assertFalse(package_paths()["pretooluse"].exists())
        self.assertFalse(hook_registry_path().exists())

    def test_install_missing_payload_fails_before_host_registration(self) -> None:
        initialize_layout(str(self.storage))
        config = self.base / "claude.json"
        with patch("safe_delete.hook._install_owned_file", return_value=False):
            with self.assertRaises(SafeDeleteError):
                hook_install("claude", config=str(config), cli_path=str(CLI), root=str(self.storage))
        self.assertFalse(config.exists())
        self.assertFalse(hook_registry_path().exists())

    def test_disable_and_uninstall_refuse_wrong_config_or_unowned_registry(self) -> None:
        initialize_layout(str(self.storage))
        configured = self.base / "configured.json"
        wrong = self.base / "wrong.json"
        hook_install("claude", config=str(configured), cli_path=str(CLI), root=str(self.storage))
        registry_before = hook_registry_path().read_bytes()
        config_before = configured.read_bytes()

        with self.assertRaises(SafeDeleteError):
            hook_disable("claude", config=str(wrong), root=str(self.storage))
        with self.assertRaises(SafeDeleteError):
            hook_uninstall("claude", config=str(wrong), root=str(self.storage))
        self.assertEqual(configured.read_bytes(), config_before)
        self.assertEqual(hook_registry_path().read_bytes(), registry_before)
        self.assertFalse(wrong.exists())

        registry = json.loads(registry_before.decode("utf-8"))
        registry["integrations"]["claude"]["adapter_path"] = str(self.base / "foreign-adapter")
        hook_registry_path().write_text(json.dumps(registry), encoding="utf-8")
        unowned_registry = hook_registry_path().read_bytes()
        with self.assertRaises(SafeDeleteError):
            hook_disable("claude", config=str(configured), root=str(self.storage))
        self.assertEqual(hook_registry_path().read_bytes(), unowned_registry)

    def test_route_pins_registered_cli_against_shadowed_path(self) -> None:
        initialize_layout(str(self.storage))
        hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(CLI), root=str(self.storage))
        shadow = self.base / "shadow"
        shadow.mkdir()
        marker = self.base / "shadow-used"
        shadow_cli = shadow / "safe-delete"
        shadow_cli.write_text(f"#!/bin/sh\nprintf used > {marker}\nexit 0\n", encoding="utf-8")
        shadow_cli.chmod(0o700)
        environment = dict(os.environ)
        environment["PATH"] = str(shadow) + os.pathsep + environment.get("PATH", "")
        target = self.workspace / "missing"
        result = execute_request(
            self.request(["rm", str(target)]),
            environment=environment,
        )
        self.assertEqual(result.response["reason_code"], "source_not_found")
        self.assertEqual(result.exit_code, 2)
        self.assertFalse(marker.exists())

    def test_registered_cli_ignores_safe_delete_cli_override(self) -> None:
        initialize_layout(str(self.storage))
        registered_cli, calls = self.instrumented_cli()
        hook_install(
            "claude",
            config=str(self.base / "claude.json"),
            cli_path=str(registered_cli),
            root=str(self.storage),
        )
        fake_marker = self.base / "fake-cli-used"
        fake_cli = self.base / "fake-safe-delete"
        fake_cli.write_text(
            "#!/bin/sh\n"
            f"printf used > {shlex.quote(str(fake_marker))}\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_cli.chmod(0o700)
        target = self.workspace / "registered-cli-target"
        target.write_text("payload", encoding="utf-8")

        with patch.dict(os.environ, {"SAFE_DELETE_CLI": str(fake_cli)}, clear=False):
            result = execute_request(
                self.request(["rm", str(target)]),
                environment=dict(os.environ),
            )

        self.assertEqual(result.response["decision"], "route")
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(target.exists())
        self.assertFalse(fake_marker.exists())
        self.assertEqual(len(calls.read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(len((self.storage / "ledger.jsonl").read_text(encoding="utf-8").splitlines()), 1)

    def test_installed_pretooluse_routes_real_vectors_once_without_raw_fallback(self) -> None:
        initialize_layout(str(self.storage))
        registered_cli, calls = self.instrumented_cli()
        raw_dir, raw_marker = self.raw_sentinels()
        hook_install(
            "claude",
            config=str(self.base / "claude.json"),
            cli_path=str(registered_cli),
            root=str(self.storage),
        )
        environment = dict(os.environ)
        environment["PATH"] = str(raw_dir) + os.pathsep + environment.get("PATH", "")
        cases = (
            ("rm", ["-rf", "--"], self.workspace / "pretooluse-rm"),
            ("unlink", ["--"], self.workspace / "pretooluse-unlink"),
            ("rmdir", ["--"], self.workspace / "pretooluse-rmdir"),
        )
        for command, options, target in cases:
            with self.subTest(command=command):
                if command == "rmdir":
                    target.mkdir()
                else:
                    target.write_text(command, encoding="utf-8")
                completed = self.run_installed_pretooluse(
                    self.request([command, *options, str(target)]),
                    environment=environment,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr.decode())
                response = json.loads(completed.stdout.decode("utf-8"))
                self.assertEqual(response["decision"], "route")
                self.assertFalse(target.exists())

        self.assertFalse(raw_marker.exists())
        self.assertEqual(len(calls.read_text(encoding="utf-8").splitlines()), 3)
        self.assertEqual(len((self.storage / "ledger.jsonl").read_text(encoding="utf-8").splitlines()), 3)

    def test_installed_path_routes_real_vectors_once_without_raw_fallback(self) -> None:
        initialize_layout(str(self.storage))
        registered_cli, calls = self.instrumented_cli()
        raw_dir, raw_marker = self.raw_sentinels()
        hook_install("path-shim", cli_path=str(registered_cli), root=str(self.storage))
        shim_dir = package_paths()["bin"]
        environment = dict(os.environ)
        environment["PATH"] = os.pathsep.join(
            [str(shim_dir), str(raw_dir), environment.get("PATH", "")]
        )
        cases = (
            ("rm", ["-R", "-f", "--"], self.workspace / "path-rm"),
            ("unlink", ["--"], self.workspace / "path-unlink"),
            ("rmdir", ["--"], self.workspace / "path-rmdir"),
        )
        for command, options, target in cases:
            with self.subTest(command=command):
                if command == "rmdir":
                    target.mkdir()
                else:
                    target.write_text(command, encoding="utf-8")
                completed = subprocess.run(
                    [command, *options, str(target)],
                    cwd=str(self.workspace),
                    env=environment,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr.decode())
                self.assertFalse(target.exists())

        self.assertFalse(raw_marker.exists())
        self.assertEqual(len(calls.read_text(encoding="utf-8").splitlines()), 3)
        self.assertEqual(len((self.storage / "ledger.jsonl").read_text(encoding="utf-8").splitlines()), 3)

    def test_installed_route_propagates_real_cli_failure_without_raw_fallback(self) -> None:
        initialize_layout(str(self.storage))
        registered_cli, calls = self.instrumented_cli()
        raw_dir, raw_marker = self.raw_sentinels()
        hook_install(
            "claude",
            config=str(self.base / "claude.json"),
            cli_path=str(registered_cli),
            root=str(self.storage),
        )
        environment = dict(os.environ)
        environment["PATH"] = str(raw_dir) + os.pathsep + environment.get("PATH", "")
        completed = self.run_installed_pretooluse(
            self.request(["rm", "missing-real-route-target"]),
            environment=environment,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr.decode())
        response = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual(response["decision"], "deny")
        self.assertEqual(response["reason_code"], "source_not_found")
        self.assertFalse(raw_marker.exists())
        self.assertEqual(len(calls.read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual((self.storage / "ledger.jsonl").read_text(encoding="utf-8"), "")

    def test_status_rejects_relocated_or_broken_payload_dependency(self) -> None:
        initialize_layout(str(self.storage))
        hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(CLI), root=str(self.storage))
        adapter = package_paths()["pretooluse"]
        lines = adapter.read_text(encoding="utf-8").splitlines()
        lines = [
            'sys.path.insert(0, "/missing/relocated/safe-delete-source")' if line.startswith("sys.path.insert(0, ") else line
            for line in lines
        ]
        adapter.write_text("\n".join(lines) + "\n", encoding="utf-8")

        status = hook_status("claude", root=str(self.storage))[0]
        self.assertFalse(status["package"]["adapter_runnable"])
        self.assertFalse(status["enforced"])

    def test_deep_extensions_are_stable_denials_at_both_hook_boundaries(self) -> None:
        extensions: dict[str, object] = {}
        cursor: dict[str, object] = extensions
        for _ in range(EXTENSIONS_MAX_DEPTH + 8):
            nested: dict[str, object] = {}
            cursor["nested"] = nested
            cursor = nested
        payload = self.request(["rm", "item"], extensions=extensions)
        decision = decide_request(payload)
        self.assertEqual(decision["decision"], "deny")
        self.assertEqual(decision["reason_code"], "unsupported_delete_invocation")

        runner = RecordingRunner()
        execution = execute_request(payload, runner=runner, require_registration=False)
        self.assertEqual(execution.response["decision"], "deny")
        self.assertEqual(execution.exit_code, 1)
        self.assertEqual(runner.calls, [])

    def test_status_storage_gate_includes_trash_writability(self) -> None:
        initialize_layout(str(self.storage))
        hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(CLI), root=str(self.storage))
        trash = self.storage / "trash"
        original_mode = trash.stat().st_mode & 0o777
        trash.chmod(0o500)
        try:
            status = hook_status("claude", root=str(self.storage))[0]
            self.assertFalse(status["storage"]["usable"])
            self.assertFalse(status["enforced"])
        finally:
            trash.chmod(original_mode)

    def test_decide_denies_missing_non_directory_and_inaccessible_cwd(self) -> None:
        missing = self.request(["rm", "item"], cwd=str(self.base / "missing-cwd"))
        self.assertEqual(decide_request(missing)["decision"], "deny")

        file_cwd = self.base / "cwd-file"
        file_cwd.write_text("not a directory", encoding="utf-8")
        self.assertEqual(
            decide_request(self.request(["rm", "item"], cwd=str(file_cwd)))["decision"],
            "deny",
        )

        inaccessible = self.base / "inaccessible-cwd"
        inaccessible.mkdir()
        original_mode = inaccessible.stat().st_mode & 0o777
        inaccessible.chmod(0)
        try:
            self.assertEqual(decide_request(self.request(["rm", "item"], cwd=str(inaccessible)))["decision"], "deny")
        finally:
            inaccessible.chmod(original_mode)

    def test_installed_pretooluse_payload_routes_real_request(self) -> None:
        initialize_layout(str(self.storage))
        hook_install("claude", config=str(self.base / "claude.json"), cli_path=str(CLI), root=str(self.storage))
        target = self.workspace / "pretooluse-target"
        target.write_text("payload", encoding="utf-8")
        request = self.request(["rm", "--", str(target)])
        completed = subprocess.run(
            [str(package_paths()["pretooluse"])] ,
            input=json.dumps(request).encode("utf-8"),
            cwd=str(self.workspace),
            env=dict(os.environ),
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", errors="replace"))
        response = json.loads(completed.stdout.decode("utf-8"))
        self.assertEqual(response["decision"], "route")
        self.assertFalse(target.exists())
        self.assertEqual(len((self.storage / "ledger.jsonl").read_text(encoding="utf-8").splitlines()), 1)

    def test_bypass_replay_is_documented_as_out_of_coverage(self) -> None:
        representative_vectors = {
            "Python/Go/Node filesystem APIs": ["python", "-c", "import os; os.unlink('item')"],
            "find -delete": ["find", ".", "-delete"],
            "git clean": ["git", "clean", "-fd"],
            "busybox rm": ["busybox", "rm", "item"],
            "absolute /bin/rm, /bin/unlink, or /bin/rmdir": ["/bin/rm", "item"],
            "another unconfigured agent/tool": ["other-agent", "rm", "item"],
        }
        self.assertTrue(set(representative_vectors).issubset(OUT_OF_COVERAGE_BYPASSES))
        for bypass, argv in representative_vectors.items():
            with self.subTest(bypass=bypass):
                response = decide_request(self.request(argv))
                self.assertEqual(response["decision"], "deny")
                self.assertEqual(response["reason_code"], "unsupported_delete_invocation")

    def test_bypass_replay_executes_representative_out_of_coverage_commands(self) -> None:
        initialize_layout(str(self.storage))
        ledger = self.storage / "ledger.jsonl"
        ledger_before = ledger.read_bytes()
        raw_dir = self.base / "raw-bypass"
        raw_dir.mkdir()
        raw_marker = self.base / "raw-bypass-used.log"
        raw_rm = raw_dir / "rm"
        raw_rm.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' raw-rm >> {shlex.quote(str(raw_marker))}\n"
            f"exec /bin/rm \"$@\"\n",
            encoding="utf-8",
        )
        raw_rm.chmod(0o700)

        replays: list[tuple[str, list[str], str, int]] = []

        def run_bypass(label: str, argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
            completed = subprocess.run(
                argv,
                cwd=str(cwd),
                env=dict(os.environ) if env is None else env,
                capture_output=True,
                check=False,
            )
            replays.append((label, argv, str(cwd), completed.returncode))
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())

        api_target = self.workspace / "api-target"
        api_target.write_text("api", encoding="utf-8")
        run_bypass(
            "Python filesystem API",
            [sys.executable, "-c", "import os; os.unlink('api-target')"],
            self.workspace,
        )

        find_target = self.workspace / "find-target"
        find_target.write_text("find", encoding="utf-8")
        run_bypass(
            "find -delete",
            ["find", ".", "-maxdepth", "1", "-name", "find-target", "-delete"],
            self.workspace,
        )

        git_workspace = self.base / "git-workspace"
        git_workspace.mkdir()
        initialized = subprocess.run(
            ["git", "init", "-q"],
            cwd=str(git_workspace),
            env=dict(os.environ),
            capture_output=True,
            check=False,
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr.decode())
        git_target = git_workspace / "git-target"
        git_target.write_text("git", encoding="utf-8")
        run_bypass("git clean", ["git", "clean", "-fdq"], git_workspace)

        absolute_target = self.workspace / "absolute-target"
        absolute_target.write_text("absolute", encoding="utf-8")
        run_bypass("absolute /bin/rm", ["/bin/rm", str(absolute_target)], self.workspace)

        hook_install("path-shim", cli_path=str(CLI), root=str(self.storage))
        reordered_target = self.workspace / "path-reordered-target"
        reordered_target.write_text("reordered", encoding="utf-8")
        reordered_environment = dict(os.environ)
        reordered_environment["PATH"] = str(raw_dir) + os.pathsep + str(package_paths()["bin"])
        run_bypass("PATH reordering", ["rm", str(reordered_target)], self.workspace, reordered_environment)

        removed_target = self.workspace / "removed-shim-target"
        removed_target.write_text("removed", encoding="utf-8")
        removed_environment = dict(os.environ)
        removed_environment["PATH"] = os.defpath
        run_bypass("removed PATH shim", ["rm", str(removed_target)], self.workspace, removed_environment)

        self.assertFalse(api_target.exists())
        self.assertFalse(find_target.exists())
        self.assertFalse(git_target.exists())
        self.assertFalse(absolute_target.exists())
        self.assertFalse(reordered_target.exists())
        self.assertFalse(removed_target.exists())
        self.assertEqual(raw_marker.read_text(encoding="utf-8").splitlines(), ["raw-rm"])
        self.assertEqual(ledger.read_bytes(), ledger_before)
        self.assertEqual(len(replays), 6)

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
