"""Unit tests import the real classifier — do not redefine mapping locally."""
from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "classify_ref.py"

spec = importlib.util.spec_from_file_location("classify_ref", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["classify_ref"] = mod
spec.loader.exec_module(mod)


def test_kind_from_counts_matrix():
    assert mod.kind_from_counts(0, 0) == "SAME"
    assert mod.kind_from_counts(0, 5) == "ANCESTOR"
    assert mod.kind_from_counts(3, 0) == "AHEAD"
    assert mod.kind_from_counts(2, 4) == "DIVERGED"


if __name__ == "__main__":
    test_kind_from_counts_matrix()
    print("test_classify_kind OK")
