#!/usr/bin/env python3
"""Read-only scan of Agent rule files for an inverted write-authority contract.

MUST-FIX (not optional):
  - A non-GitHub Issues host (GitLab, Gitee, Bitbucket, …) named as
    production / write SoT / sole authority.
  - GitHub / origin demoted to "mirror only".
  - A deploy/manifest/projection tip called write SoT.

Does not rewrite files. Exit 1 if any must-fix hit; 0 if clean; 2 on usage error.

This is a wording contract check. It does not classify remotes or push.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

SKIP_DIR_NAMES = {
    ".git",
    ".agent-project-ops",
    ".worktrees",
    "node_modules",
    "vendor",
    "__pycache__",
}

DEFAULT_RELATIVE_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    "COPILOT.md",
    ".github/copilot-instructions.md",
    ".aider.conf.yml",
)

DEFAULT_GLOBS = (
    ".cursor/rules/**/*.md",
    ".cursor/rules/**/*.mdc",
    ".continue/rules/**/*.md",
    ".continue/rules/**/*.mdc",
    ".github/instructions/**/*.md",
)

FOREIGN_HOST = r"(?:gitlab|gitee|bitbucket|coding\.net|sourcehut|codeberg)"
GITHUBISH = r"(?:github|`origin`|\borigin\b)"
ASSIGN = r"(?:\bis\b|:|=|是|为|作为)"

WRITE_SOT = (
    r"(?:write\s+authority|write\s+sot|sole\s+(?:write\s+)?authority|"
    r"production\s+(?:sot|source(?:\s+of\s+truth)?)|source\s+of\s+truth|"
    r"写权威|写入权威|生产源码|生产源|部署事实源|事实源)"
)

MIRROR_ONLY = (
    r"(?:mirror\s+only|only\s+(?:a\s+|the\s+)?mirror|"
    r"仅为镜像|仅是镜像|只是镜像|只为镜像|仅镜像|仅为协作镜像)"
)

NEGATION = re.compile(
    r"(?:anti[- ]pattern|forbidden|prohibit(?:ed)?|\bnever\b|"
    r"\bdo not\b|\bdon't\b|\bmust not\b|\bis not\b|\bnot a\b|"
    r"\bnot write\b|\bnot\s+(?:the\s+)?(?:write|sot|authority)|"
    r"禁止|不得|不要|反模式|反置|不是|并非|≠)",
    re.IGNORECASE,
)

HOST_AS_SOT = re.compile(
    rf"{FOREIGN_HOST}.{{0,40}}{ASSIGN}.{{0,40}}{WRITE_SOT}",
    re.IGNORECASE | re.DOTALL,
)
SOT_AS_HOST = re.compile(
    rf"{WRITE_SOT}.{{0,20}}{ASSIGN}.{{0,30}}{FOREIGN_HOST}",
    re.IGNORECASE | re.DOTALL,
)
GITHUB_MIRROR = re.compile(
    rf"{GITHUBISH}.{{0,40}}{MIRROR_ONLY}",
    re.IGNORECASE | re.DOTALL,
)
MIRROR_GITHUB = re.compile(
    rf"{MIRROR_ONLY}.{{0,40}}{GITHUBISH}",
    re.IGNORECASE | re.DOTALL,
)
DEPLOY_AS_WRITE = re.compile(
    rf"(?:deploy(?:ment)?|manifest|projection|投影)\s+"
    rf"(?:tip|identity)\b.{{0,30}}{ASSIGN}.{{0,20}}"
    rf"(?:the\s+)?{WRITE_SOT}",
    re.IGNORECASE | re.DOTALL,
)
WRITE_AS_DEPLOY = re.compile(
    rf"{WRITE_SOT}.{{0,20}}{ASSIGN}.{{0,20}}"
    rf"(?:the\s+)?(?:deploy(?:ment)?|manifest|projection|投影)\s+"
    rf"(?:tip|identity)\b",
    re.IGNORECASE | re.DOTALL,
)

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("foreign-host-as-write-sot", HOST_AS_SOT),
    ("write-sot-assigned-to-foreign-host", SOT_AS_HOST),
    ("github-demoted-to-mirror-only", GITHUB_MIRROR),
    ("mirror-only-assigned-to-github", MIRROR_GITHUB),
    ("deploy-tip-called-write-sot", DEPLOY_AS_WRITE),
    ("write-sot-assigned-to-deploy-tip", WRITE_AS_DEPLOY),
)


@dataclass(frozen=True)
class Hit:
    path: str
    line: int
    rule: str
    excerpt: str


def _line_number(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _excerpt(text: str, start: int, end: int, radius: int = 48) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    chunk = text[lo:hi].replace("\n", " ").strip()
    return re.sub(r"\s+", " ", chunk)


def _negated(text: str, start: int, end: int, lookbehind: int = 32) -> bool:
    window = text[max(0, start - lookbehind) : end]
    return bool(NEGATION.search(window))


def find_hits(text: str, *, path: str = "") -> list[Hit]:
    """Return must-fix hits for one file body. Pure; unit-tested."""
    hits: list[Hit] = []
    seen: set[tuple[int, str]] = set()
    for rule, pattern in RULES:
        for match in pattern.finditer(text):
            if _negated(text, match.start(), match.end()):
                continue
            line = _line_number(text, match.start())
            key = (line, rule)
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                Hit(
                    path=path,
                    line=line,
                    rule=rule,
                    excerpt=_excerpt(text, match.start(), match.end()),
                )
            )
    hits.sort(key=lambda h: (h.line, h.rule))
    return hits


def iter_rule_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    for rel in DEFAULT_RELATIVE_FILES:
        candidate = root / rel
        if candidate.is_file():
            files.add(candidate.resolve())
    for pattern in DEFAULT_GLOBS:
        for candidate in root.glob(pattern):
            if not candidate.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in candidate.parts):
                continue
            files.add(candidate.resolve())
    return sorted(files)


def scan_root(root: Path) -> list[Hit]:
    hits: list[Hit] = []
    for path in iter_rule_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"cannot read {path}: {exc}") from exc
        rel = str(path.relative_to(root))
        hits.extend(find_hits(text, path=rel))
    return hits


def format_report(root: Path, hits: list[Hit], scanned: int) -> str:
    lines = [
        "# inverted-sot scan v1",
        f"root={root}",
        f"files_scanned={scanned}",
        f"must_fix={len(hits)}",
    ]
    if not hits:
        lines.append("status=clean")
        return "\n".join(lines) + "\n"
    lines.append("status=MUST-FIX")
    for hit in hits:
        lines.append(f"MUST-FIX {hit.path}:{hit.line} [{hit.rule}] {hit.excerpt}")
    lines.append(
        "fail-closed: rewrite the remote contract to GitHub origin = write "
        "authority (templates/AGENTS.md); only origin is supported. Preserve old "
        "remote settings for explicit migration review. PIN binding is not complete while must-fix hits remain."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        default=".",
        help="Business-repo root to scan (default: cwd)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Print hits as JSON instead of the text report",
    )
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR not a directory: {root}", file=sys.stderr)
        return 2

    try:
        hits = scan_root(root)
        scanned = len(iter_rule_files(root))
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([asdict(h) for h in hits], ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(format_report(root, hits, scanned))
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
