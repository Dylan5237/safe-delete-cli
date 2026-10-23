#!/usr/bin/env python3
"""Classify REF vs TIP using git rev-list --left-right --count.

KIND in {SAME, ANCESTOR, AHEAD, DIVERGED}.
Does not decide delete/keep — that remains a disposer/AI decision.
"""
from __future__ import annotations

import argparse
import subprocess
import sys


def kind_from_counts(ahead: int, behind: int) -> str:
    """Map ahead/behind counts to KIND. Pure; unit-tested."""
    if ahead == 0 and behind == 0:
        return "SAME"
    if ahead == 0 and behind > 0:
        return "ANCESTOR"
    if ahead > 0 and behind == 0:
        return "AHEAD"
    return "DIVERGED"


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or f"fail: {cmd}")
    return p.stdout.strip()


def classify(cwd: str, tip: str, ref: str) -> str:
    tip_sha = run(["git", "-C", cwd, "rev-parse", tip])
    ref_sha = run(["git", "-C", cwd, "rev-parse", ref])
    counts = run(
        ["git", "-C", cwd, "rev-list", "--left-right", "--count", f"{tip_sha}...{ref_sha}"]
    )
    left_s, right_s = counts.split()
    behind, ahead = int(left_s), int(right_s)
    kind = kind_from_counts(ahead, behind)
    return f"KIND={kind} ahead={ahead} behind={behind} tip={tip_sha[:12]} ref={ref_sha[:12]}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tip", required=True, help="Authority tip ref (e.g. origin/main)")
    ap.add_argument("--ref", required=True, help="Branch/worktree/commit to classify")
    ap.add_argument("--cwd", default=".", help="Git repo working directory")
    args = ap.parse_args()
    print(classify(args.cwd, args.tip, args.ref))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"ERROR {e}", file=sys.stderr)
        raise SystemExit(2)
