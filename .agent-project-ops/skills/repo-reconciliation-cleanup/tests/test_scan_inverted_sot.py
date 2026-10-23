"""Unit tests import the real inverted-SoT scanner — do not redefine rules locally."""
from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scan_inverted_sot.py"

spec = importlib.util.spec_from_file_location("scan_inverted_sot", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["scan_inverted_sot"] = mod
spec.loader.exec_module(mod)


INVERTED_ZH = (
    "GitLab 是生产源码与部署事实源。GitHub 仅为镜像与协作。\n"
)
INVERTED_EN = (
    "GitLab is the production source of truth. GitHub is a mirror only.\n"
)
INVERTED_WRITE = "Write authority: GitLab. GitHub is only a mirror.\n"
INVERTED_DEPLOY = (
    "The release skill consumes the GitLab default branch. "
    "Deploy tip is the write authority.\n"
)

CORRECT_TEMPLATE = (
    "origin (GitHub) is the only write authority. "
    "Projection remotes are same-history mirror/FF only. "
    "Colleague GitLab is share-export (filtered business tree), not a projection.\n"
)
CORRECT_TIPS = (
    "Write authority tip: origin/main (GitHub). "
    "Deploy/manifest tip: projection/main (same-history FF; not write SoT).\n"
)
ANTIPATTERN_DOC = (
    "禁止把 GitLab 写成唯一生产/写权威、GitHub 降为「仅镜像」。\n"
    "Inverted contract is an anti-pattern: never treat GitLab as write authority.\n"
)


class FindHitsTests(unittest.TestCase):
    def test_inverted_zh_is_must_fix(self):
        hits = mod.find_hits(INVERTED_ZH)
        rules = {h.rule for h in hits}
        self.assertIn("foreign-host-as-write-sot", rules)
        self.assertIn("github-demoted-to-mirror-only", rules)

    def test_inverted_en_is_must_fix(self):
        hits = mod.find_hits(INVERTED_EN)
        rules = {h.rule for h in hits}
        self.assertIn("foreign-host-as-write-sot", rules)
        self.assertIn("github-demoted-to-mirror-only", rules)

    def test_write_authority_gitlab_is_must_fix(self):
        hits = mod.find_hits(INVERTED_WRITE)
        self.assertTrue(hits)
        self.assertTrue(any("foreign" in h.rule or "write-sot" in h.rule for h in hits))

    def test_deploy_tip_called_write_sot_is_must_fix(self):
        hits = mod.find_hits(INVERTED_DEPLOY)
        self.assertTrue(any("deploy" in h.rule for h in hits))

    def test_correct_template_is_clean(self):
        self.assertEqual(mod.find_hits(CORRECT_TEMPLATE), [])

    def test_authority_vs_deploy_tip_split_is_clean(self):
        self.assertEqual(mod.find_hits(CORRECT_TIPS), [])

    def test_antipattern_documentation_is_clean(self):
        self.assertEqual(mod.find_hits(ANTIPATTERN_DOC), [])

    def test_gitee_as_production_is_must_fix(self):
        hits = mod.find_hits("Gitee is the sole write authority.\n")
        self.assertTrue(hits)

    def test_github_authority_projection_mirror_is_clean(self):
        text = (
            "GitHub origin is the sole write authority. "
            "The optional projection is a same-history mirror only.\n"
        )
        self.assertEqual(mod.find_hits(text), [])


class ScanRootTests(unittest.TestCase):
    def test_scans_agents_md_and_skips_pinned_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "AGENTS.md").write_text(INVERTED_ZH, encoding="utf-8")
            pinned = root / ".agent-project-ops" / "playbooks"
            pinned.mkdir(parents=True)
            (pinned / "note.md").write_text(INVERTED_EN, encoding="utf-8")
            (root / "README.md").write_text(INVERTED_EN, encoding="utf-8")
            hits = mod.scan_root(root)
            self.assertTrue(hits)
            self.assertTrue(all(h.path == "AGENTS.md" for h in hits))

    def test_clean_agents_md_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "AGENTS.md").write_text(CORRECT_TEMPLATE, encoding="utf-8")
            self.assertEqual(mod.main(["--root", str(root)]), 0)

    def test_inverted_agents_md_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "AGENTS.md").write_text(INVERTED_EN, encoding="utf-8")
            self.assertEqual(mod.main(["--root", str(root)]), 1)

    def test_missing_root_exits_two(self):
        self.assertEqual(mod.main(["--root", "/no/such/adopt-root"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
