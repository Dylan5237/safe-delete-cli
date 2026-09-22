"""P9 WorkBuddy host adapter contract tests (Issue #27)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from safe_delete.errors import SafeDeleteError
from safe_delete.hook import hook_status, select_integration

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CLI = REPOSITORY_ROOT / "safe-delete"


class WorkbuddyHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="safe-delete-p9-")
        self.base = Path(self.temp_dir.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.project = self.base / "project"
        self.project.mkdir()
        self.storage = self.base / "storage"
        self.addCleanup(self.temp_dir.cleanup)

    def environment(self) -> dict[str, str]:
        child = os.environ.copy()
        child["HOME"] = str(self.home)
        child["XDG_DATA_HOME"] = str(self.home / ".local" / "share")
        child["XDG_CONFIG_HOME"] = str(self.home / ".config")
        child["SAFE_DELETE_ROOT"] = str(self.storage)
        child.pop("WORKBUDDY_CONFIG_DIR", None)
        child.pop("CODEBUDDY_CONFIG_DIR", None)
        child.pop("SAFE_DELETE_RETENTION_DAYS", None)
        return child

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), "--root", str(self.storage), *arguments],
            cwd=str(REPOSITORY_ROOT),
            text=True,
            capture_output=True,
            env=self.environment(),
            check=False,
        )

    def run_json(self, *arguments: str) -> tuple[int, dict, str]:
        completed = self.run_cli("--json", *arguments)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:  # pragma: no cover
            raise AssertionError(
                f"CLI did not emit JSON\nstdout={completed.stdout!r}\nstderr={completed.stderr!r}"
            ) from exc
        return completed.returncode, payload, completed.stderr


class WorkbuddyContractTests(WorkbuddyHarness):
    def test_select_prefers_workbuddy_tree_and_env_override(self) -> None:
        with patch.dict(os.environ, self.environment(), clear=False):
            os.environ.pop("WORKBUDDY_CONFIG_DIR", None)
            default = select_integration("workbuddy")
            self.assertEqual(default.selector, "workbuddy")
            self.assertEqual(default.mode, "pretooluse")
            self.assertEqual(default.event_key, "PreToolUse")
            self.assertEqual(
                default.config_path,
                self.home / ".workbuddy" / "settings.json",
            )

            project = select_integration("workbuddy", project=str(self.project))
            self.assertEqual(
                project.config_path,
                self.project / ".workbuddy" / "settings.json",
            )

            override_root = self.base / "wb-config"
            with patch.dict(os.environ, {"WORKBUDDY_CONFIG_DIR": str(override_root)}):
                overridden = select_integration("workbuddy")
            self.assertEqual(overridden.config_path, override_root / "settings.json")

            with patch.dict(os.environ, {"CODEBUDDY_CONFIG_DIR": str(self.base / "cb")}):
                still = select_integration("workbuddy")
            self.assertEqual(
                still.config_path,
                self.home / ".workbuddy" / "settings.json",
            )

    def test_setup_workbuddy_init_writes_matcher_and_doctor_row(self) -> None:
        code, payload, stderr = self.run_json("setup", "workbuddy", "--init")
        self.assertEqual(code, 0, (payload, stderr))
        self.assertTrue(payload["ok"], payload)
        report = payload["results"][0]
        self.assertEqual(report["selector"], "workbuddy")
        install = report["install"]
        self.assertEqual(install["selector"], "workbuddy")
        self.assertTrue(install["installed"])
        config_path = Path(install["boundary"]["config_path"])
        self.assertEqual(config_path, self.home / ".workbuddy" / "settings.json")
        settings = json.loads(config_path.read_text(encoding="utf-8"))
        entries = settings["hooks"]["PreToolUse"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["matcher"], "Bash|execute_command")
        self.assertEqual(entries[0]["hooks"][0]["type"], "command")

        doctor = report["doctor"]
        self.assertTrue(doctor["read_only"])
        self.assertEqual(
            [item["selector"] for item in doctor["boundaries"]],
            ["claude", "cursor", "path-shim", "workbuddy"],
        )
        blob = json.dumps(payload).lower()
        self.assertNotIn("fully protected", blob)
        self.assertNotIn("codebuddy", blob)

    def test_codebuddy_selector_is_rejected(self) -> None:
        with patch.dict(os.environ, self.environment(), clear=False):
            with self.assertRaises(SafeDeleteError) as ctx:
                select_integration("codebuddy")
            self.assertEqual(ctx.exception.code, "unsupported_command")

        code, payload, _ = self.run_json("setup", "codebuddy")
        self.assertNotEqual(code, 0)
        self.assertFalse(payload.get("ok", True))
        errors = payload.get("errors") or []
        self.assertTrue(errors)
        self.assertEqual(errors[0]["code"], "unsupported_command")
        self.assertFalse((self.home / ".codebuddy").exists())
        self.assertFalse((self.home / ".workbuddy" / "settings.json").exists())

    def test_status_lists_workbuddy(self) -> None:
        with patch.dict(os.environ, self.environment(), clear=False):
            statuses = hook_status(root=str(self.storage))
        self.assertEqual(
            [item["selector"] for item in statuses],
            ["claude", "cursor", "path-shim", "workbuddy"],
        )


if __name__ == "__main__":
    unittest.main()
