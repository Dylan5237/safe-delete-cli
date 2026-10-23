#!/usr/bin/env bash
# Read-only git/workspace inventory for repo-reconciliation-cleanup.
# Prints metadata only; does not delete or modify.
set -euo pipefail
export GIT_OPTIONAL_LOCKS=0

usage() { echo "usage: $0 <repo-root>" >&2; exit 64; }
[[ $# -eq 1 ]] || usage
[[ -d "$1" ]] || { echo "[ERR] not a directory: $1" >&2; exit 66; }
ROOT="$(cd "$1" && pwd -P)"

printf '# repo-reconciliation-cleanup inventory v1\n'
printf 'project_root=%s\n' "$ROOT"
printf 'generated_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

if ! git -C "$ROOT" rev-parse --show-toplevel >/dev/null 2>&1; then
  printf 'git_root=none\n'
  exit 0
fi

GIT_ROOT="$(git -C "$ROOT" rev-parse --show-toplevel 2>/dev/null)"
printf 'git_root=%s\n' "$GIT_ROOT"
printf '\n## remotes\n'
# This Skill can be installed on its own: do not depend on source-repo libs.
# Classify local URL metadata without ever printing URLs or Git error text.
python3 -B - "$GIT_ROOT" <<'PY'
import re
import subprocess
import sys

def query(*args):
    try:
        result = subprocess.run(['git', '-C', sys.argv[1], *args], capture_output=True,
                                text=True, encoding='utf-8', errors='replace')
        return result.returncode, result.stdout
    except OSError:
        return -1, ''

def identity(url):
    if not url.isascii():
        return None
    match = re.fullmatch(r'(?:https://github.com/|ssh://git@github.com/|git@github.com:)'
                         r'([a-z0-9_.-]+)/([a-z0-9_.-]+)/?', url.lower())
    if not match:
        return None
    owner, repo = match.groups()
    repo = repo.removesuffix('.git')
    return (owner, repo) if owner not in {'.', '..'} and repo not in {'', '.', '..'} else None

code, names = query('remote')
if code:
    print('remote_inventory=REVIEW_REQUIRED')
else:
    for name in names.splitlines():
        if not re.fullmatch(r'[A-Za-z0-9._/-]+', name):
            print('remote_inventory=REVIEW_REQUIRED')
            continue
        # SAFE_GITHUB describes origin's URL metadata, never write permission,
        # reachability, branch protection or acceptance. Extra remotes need review.
        safe = name == 'origin'
        identities = []
        counts = {}
        for key in ('url', 'pushurl'):
            rc, raw = query('config', '--null', '--get-all', f'remote.{name}.{key}')
            counts[key] = len(raw.split('\0')) - 1 if rc == 0 else 0
            safe = safe and (rc == 0 or key == 'pushurl' and rc == 1)
        for push in (False, True):
            args = ['remote', 'get-url', *(['--push'] if push else []), '--all', name]
            rc, raw = query(*args)
            urls = raw.splitlines()
            expected = counts['pushurl'] or counts['url'] if push else counts['url']
            safe = safe and rc == 0 and expected > 0 and len(urls) == expected
            identities.extend(identity(url) for url in urls)
        safe = safe and bool(identities) and None not in identities and len(set(identities)) == 1
        print(name + '\t' + ('SAFE_GITHUB' if safe else 'REVIEW_REQUIRED'))
PY

printf '\n## head\n'
printf 'branch=%s\n' "$(git -C "$GIT_ROOT" branch --show-current 2>/dev/null || echo DETACHED)"
head="$(git -C "$GIT_ROOT" rev-parse HEAD 2>/dev/null)" || head=UNKNOWN
printf 'head=%s\n' "$head"
for c in origin/HEAD origin/main origin/master; do
  if git -C "$GIT_ROOT" rev-parse "$c" >/dev/null 2>&1; then
    printf '%s=%s\n' "$c" "$(git -C "$GIT_ROOT" rev-parse --short=12 "$c" 2>/dev/null)"
  fi
done

printf '\n## status\n'
printf 'porcelain_lines=%s\n' "$(git -C "$GIT_ROOT" status --porcelain=v1 2>/dev/null | wc -l | tr -d ' ')"
# Branch identity is reported above. Do not repeat upstream remote names here:
# a rejected name could contain the same sensitive text hidden in ## remotes.
git -C "$GIT_ROOT" status --short 2>/dev/null || true

printf '\n## worktrees\n'
git -C "$GIT_ROOT" worktree list 2>/dev/null || true

printf '\n## local-branches\n'
git -C "$GIT_ROOT" for-each-ref --format='%(refname:short) %(objectname:short)' refs/heads 2>/dev/null || true

printf '\n## remote-branches (origin)\n'
git -C "$GIT_ROOT" for-each-ref --format='%(refname:short) %(objectname:short)' refs/remotes/origin 2>/dev/null | head -200 || true

printf '\n## residue-candidates (names only)\n'
# common session leftovers — existence only
git -C "$GIT_ROOT" status --porcelain=v1 2>/dev/null | awk '{print $2}' | head -200 || true
find "$GIT_ROOT" -maxdepth 2 \( -name '*_old*' -o -name '*_backup*' -o -name '*_v2*' -o -name '_scan*' -o -name 'PLAN.md' -o -name 'TODO.md' \) 2>/dev/null | head -100 || true

printf '\n## done\n'
