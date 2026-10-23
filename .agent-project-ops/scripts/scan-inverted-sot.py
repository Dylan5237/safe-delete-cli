#!/usr/bin/env python3
"""Stable entrypoint for the inverted-SoT wording scan.

Resolves the skill scanner relative to this file so the same wrapper works
from the methodology checkout (`scripts/`) and from a bound snapshot
(`.agent-project-ops/scripts/`).
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATES = (
    HERE.parent / "skills" / "repo-reconciliation-cleanup" / "scripts" / "scan_inverted_sot.py",
    HERE.parent / "repo-reconciliation-cleanup" / "scripts" / "scan_inverted_sot.py",
)

script = next((p for p in CANDIDATES if p.is_file()), None)
if script is None:
    sys.stderr.write("ERROR cannot locate scan_inverted_sot.py next to this wrapper\n")
    raise SystemExit(2)

sys.argv[0] = str(script)
runpy.run_path(str(script), run_name="__main__")
