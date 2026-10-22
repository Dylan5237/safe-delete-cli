#!/usr/bin/env python3
"""Preview/apply Command Center section 1, or check declared dispatch file scopes."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys


class Invalid(ValueError):
    pass


def run(args: list[str], *, data=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(args, input=data, capture_output=True, text=True,
                            encoding="utf-8", timeout=90, env=env)
    if result.returncode:
        raise Invalid("command failed: " + args[0] + ": " + result.stderr.strip())
    return result.stdout


def authority(root: Path) -> str:
    # Reuse the same resolved-URL/all-pushurl guard as the pre-push hook.
    guard = Path(__file__).parent / "lib/url-guard.sh"
    bash = shutil.which("bash")
    if sys.platform == "win32":
        git = shutil.which("git")
        candidate = Path(git).resolve().parents[1] / "bin/bash.exe" if git else Path("")
        if candidate.is_file():
            bash = str(candidate)
    if not bash:
        raise Invalid("Git Bash/bash required for the shared origin URL guard")
    identity = run([bash, "-c", 'source "$1"; github_origin_identity "$2"',
                    "apo-authority", str(guard), str(root)]).strip()
    if not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", identity):
        raise Invalid("origin identity unavailable")
    return identity


class GitHub:
    def __init__(self, repo: str):
        self.repo = repo

    def api(self, path: str, *, data=None, pages=False):
        args = ["gh", "api", "--hostname", "github.com", "repos/" + self.repo + "/" + path]
        if data is not None:
            args += ["--method", "PATCH", "--input", "-"]
        elif pages:
            args += ["--paginate", "--slurp"]
        value = json.loads(run(args, data=None if data is None else json.dumps(data)))
        return [item for page in value for item in page] if pages else value


def one_line(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n\0"):
        raise Invalid(field + " must contain one nonempty line")
    # These fields become GitHub prose. Human handles remain permitted.
    if re.search(r"@(?:(?:codex|claude|workbuddy|codebuddy|chatgpt|grok)\b|[\w-]+\[bot\])", value, re.I):
        raise Invalid(field + ": rewrite Agent/bot mentions as 'at name'")
    return value.replace("|", "&#124;")


def marker(body: str, kind: str):
    first = body.splitlines()[0] if body else ""
    match = re.fullmatch(r"<!-- " + kind + r" v1 \| (.*?) -->", first)
    if not match:
        return None
    pairs = [part.strip().partition(":") for part in match[1].split("|")]
    if any(not sep for _, sep, _ in pairs):
        raise Invalid("malformed formal decision marker")
    values = {key: value.strip() for key, _, value in pairs}
    if len(values) != len(pairs):
        raise Invalid("duplicate decision fields")
    if not re.fullmatch(r"D-[1-9][0-9]*", values.get("id", "")) or not re.fullmatch(r"[1-9][0-9]*", values.get("rev", "")):
        raise Invalid("invalid formal decision identity/revision")
    if kind == "apo-decision":
        if (not re.fullmatch(r"#[1-9][0-9]*(?: +#[1-9][0-9]*)*", values.get("target", ""))
                or not values.get("type") or not re.fullmatch(r"@[A-Za-z0-9][A-Za-z0-9-]*", values.get("disposer", ""))):
            raise Invalid("formal decision requires target, type and disposer")
    return values


def pending_decisions(records: list[dict], phase: int) -> str:
    latest = {}
    results = {}
    requests = set()
    for record in records:
        request = marker(record.get("body") or "", "apo-decision")
        result = marker(record.get("body") or "", "apo-decision-result")
        if (request or result) and not isinstance(record.get("_apo_issue"), int):
            raise Invalid("formal decision record has no source discussion")
        if request:
            identity = (request["id"], request["rev"])
            if identity in requests:
                raise Invalid("duplicate formal decision id/revision; reconcile the source discussions")
            requests.add(identity)
            old = latest.get(request["id"])
            if old is None or int(request["rev"]) > int(old[0]["rev"]):
                latest[request["id"]] = (request, record)
        if result:
            if result.get("result") not in ("批准 A", "改用 B", "退回", "撤回") or not result.get("reply"):
                raise Invalid("invalid decision result marker")
            results.setdefault((result["id"], result["rev"], record["_apo_issue"]), []).append(record)
    pending = []
    for ident, (request, record) in sorted(latest.items(), key=lambda pair: int(pair[0][2:])):
        if str(phase) not in re.findall(r"#([0-9]+)", request["target"]):
            continue
        # A result for an older revision never settles the latest request.
        settled = any(r.get("created_at", "") >= record.get("created_at", "")
                      for r in results.get((ident, request["rev"], record["_apo_issue"]), []))
        if not settled:
            pending.append(f'[{ident} rev {request["rev"]}]({record["html_url"]})（{request.get("type", "决定")}）')
    return "；".join(pending) or "无"


def first_section(body: str):
    pattern = re.compile(r"(?m)^## 1\. 一眼状态[^\n]*\n")
    starts = list(pattern.finditer(body))
    if len(starts) != 1:
        raise Invalid("expected exactly one Command Center section 1")
    start = starts[0].start()
    match = re.search(r"(?m)^## ", body[starts[0].end():])
    end = starts[0].end() + match.start() if match else len(body)
    return start, end


def status_plan(gh: GitHub, args):
    cc = gh.api(f"issues/{args.cc}")
    phase = gh.api(f"issues/{args.phase}")
    if "pull_request" in cc or "pull_request" in phase:
        raise Invalid("CC and phase/task must be Issues")
    if "type:command-center" not in {label["name"] for label in cc["labels"]}:
        raise Invalid("CC must carry type:command-center")
    if not {"type:phase", "type:task"} & {label["name"] for label in phase["labels"]}:
        raise Invalid("target must carry type:phase or type:task")
    body = cc.get("body") or ""
    index = re.search(r"(?ms)^## (?:阶段索引|阶段记录|Phase index)\s*\n(.*?)(?=^## |\Z)", body)
    if not index or not re.search(r"(?<!\d)#" + str(args.phase) + r"(?!\d)", index[1]):
        raise Invalid("target phase/task is absent from the Command Center index")
    labels = [label["name"] for label in phase["labels"] if label["name"].startswith("status:")]
    words = {"status:backlog": "未开工", "status:in-progress": "进行中", "status:blocked": "卡住",
             "status:verification": "待验收", "status:done": "已完成"}
    if len(labels) != 1 or labels[0] not in words:
        raise Invalid("target must have exactly one known status label")
    if (phase["state"] == "closed") != (labels[0] == "status:done"):
        raise Invalid("target state and status label disagree")
    records = [{**cc, "_apo_issue": args.cc}, {**phase, "_apo_issue": args.phase}]
    for number in (args.cc, args.phase):
        records += [{**record, "_apo_issue": number}
                    for record in gh.api(f"issues/{number}/comments?per_page=100", pages=True)]
    values = [f'#{args.phase} {phase["title"]}', words[labels[0]], pending_decisions(records, args.phase),
              args.recent, args.blocker, args.next_action, args.tidy]
    fields = ["当前工作", "状态", "待你决定", "最近完成", "卡点", "下一步", "收尾检查"]
    rows = [f"| **{field}** | {one_line(value, field)} |" for field, value in zip(fields, values)]
    section = ("## 1. 一眼状态\n\n<!-- Generated by project-automation.py; preview before apply. -->\n\n"
               "| 项目 | 现在 |\n| --- | --- |\n" + "\n".join(rows) +
               f"\n\n更新于 {date.today().isoformat()}。状态和待决项来自 GitHub；叙述与证据由主 Agent 核对。\n\n")
    start, end = first_section(body)
    new_body = body[:start] + section + body[end:]
    # Bind every read and the output; approval is never manufactured here.
    fingerprint = {"repo": gh.repo, "cc": cc, "phase": phase, "records": records,
                   "new_body": new_body}
    token = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return token, section, body, new_body


def update_status(gh: GitHub, args):
    token, section, body, new_body = status_plan(gh, args)
    print(section, end="")
    print("plan_id=" + token)
    if not args.apply:
        print("PREVIEW: no GitHub writes; confirm with --apply --expect-plan " + token)
        return
    if not args.expect_plan or token != args.expect_plan:
        raise Invalid("STALE_PLAN: preview current GitHub state before applying")
    # Narrow the optimistic-concurrency window; GitHub issue PATCH is not CAS.
    again = status_plan(gh, args)
    if again[0] != token:
        raise Invalid("STALE_PLAN: GitHub changed after confirmation")
    if body == new_body:
        print("UNCHANGED")
        return
    response = gh.api(f"issues/{args.cc}", data={"body": new_body})
    if response.get("body") != new_body:
        raise Invalid("WRITE_UNVERIFIED: inspect CC before retrying")
    print("APPLIED: " + response["html_url"])


def file_scope(body: str):
    begin, end = "<!-- apo-file-scope v1 -->", "<!-- /apo-file-scope -->"
    if body.count(begin) != 1 or body.count(end) != 1:
        raise Invalid("UNKNOWN_SCOPE: expected one apo-file-scope block")
    if body.index(end) < body.index(begin):
        raise Invalid("UNKNOWN_SCOPE: invalid block order")
    lines = body.split(begin, 1)[1].split(end, 1)[0].strip().splitlines()
    paths = []
    for line in lines:
        match = re.fullmatch(r"(file|dir): (\S(?:.*\S)?)", line)
        if not match:
            raise Invalid("UNKNOWN_SCOPE: use file: path or dir: path/")
        kind, raw = match.groups()
        path = raw[:-1] if kind == "dir" and raw.endswith("/") else raw
        if (not path or path.startswith("/") or any(x in path for x in ("\\", ":", "*", "?", "[", "]", "\0"))
                or any(part in ("", ".", "..") for part in path.split("/"))):
            raise Invalid("UNKNOWN_SCOPE: unsafe or noncanonical repo-relative path")
        if PurePosixPath(path).is_absolute():
            raise Invalid("UNKNOWN_SCOPE: absolute path")
        paths.append((kind, path))
    if not paths or len(set(paths)) != len(paths):
        raise Invalid("UNKNOWN_SCOPE: empty/duplicate paths")
    return paths


def overlap(left, right):
    # Casefold is conservative across Windows/macOS/Linux checkouts.
    lk, lp = left[0], left[1].casefold()
    rk, rp = right[0], right[1].casefold()
    return (lp == rp or lk == "dir" and rp.startswith(lp + "/")
            or rk == "dir" and lp.startswith(rp + "/"))


def task_status(task: dict) -> str:
    labels = [label["name"] for label in task["labels"] if label["name"].startswith("status:")]
    if len(labels) != 1 or labels[0] not in ("status:backlog", "status:in-progress", "status:verification", "status:blocked"):
        raise Invalid("UNKNOWN_SCOPE: open task requires exactly one valid non-done status")
    return labels[0]


def dispatch_check(gh: GitHub, numbers) -> int:
    numbers = [numbers] if isinstance(numbers, int) else numbers
    if not numbers or len(set(numbers)) != len(numbers) or any(n <= 0 for n in numbers):
        raise Invalid("provide unique positive --task numbers")
    candidates = []
    for number in numbers:
        candidate = gh.api(f"issues/{number}")
        if "pull_request" in candidate or candidate["state"] != "open" or "type:task" not in {x["name"] for x in candidate["labels"]}:
            raise Invalid("candidate must be an open type:task Issue")
        if task_status(candidate) not in ("status:backlog", "status:in-progress"):
            raise Invalid("candidate must be backlog or in-progress for START/recheck")
        candidates.append((number, file_scope(candidate.get("body") or "")))
    tasks = gh.api("issues?state=open&labels=type%3Atask&per_page=100", pages=True)
    conflicts, unknown = [], []
    def compare(number, desired, other, active):
        for left in desired:
            for right in active:
                if overlap(left, right):
                    conflicts.append(f'#{number} {left[0]}:{left[1]} <-> #{other} {right[0]}:{right[1]}')
    for i, (number, desired) in enumerate(candidates):
        for other, active in candidates[i+1:]:
            compare(number, desired, other, active)
    for task in tasks:
        if "pull_request" in task:
            continue
        try:
            status = task_status(task)
            if task["number"] in numbers or status != "status:in-progress":
                continue
            active = file_scope(task.get("body") or "")
        except Invalid as exc:
            unknown.append(f'#{task["number"]}: {exc}')
            continue
        for number, desired in candidates:
            compare(number, desired, task["number"], active)
    for conflict in conflicts:
        print("CONFLICT: " + conflict)
    for item in unknown:
        print(item)
    if unknown:
        return 2
    if conflicts:
        print("Resolve by serializing tasks or reviewing nonoverlapping scope before dispatch; nothing dispatched.")
        return 3
    print("NO_CONFLICT: " + ", ".join("#" + str(n) for n in numbers) + "; declared paths only; no dispatch or writes performed")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.add_argument("--cc", type=int, required=True)
    status.add_argument("--phase", type=int, required=True)
    status.add_argument("--recent", required=True)
    status.add_argument("--blocker", default="无")
    status.add_argument("--next-action", required=True)
    status.add_argument("--tidy", required=True)
    status.add_argument("--apply", action="store_true")
    status.add_argument("--expect-plan", default="")
    dispatch = commands.add_parser("dispatch-check")
    dispatch.add_argument("--task", type=int, action="append", required=True)
    args = parser.parse_args()
    try:
        gh = GitHub(authority(args.root.resolve()))
        if args.command == "status":
            update_status(gh, args)
            return 0
        return dispatch_check(gh, args.task)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print("project-automation: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
