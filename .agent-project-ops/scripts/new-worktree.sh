#!/usr/bin/env bash
# Create one worktree + topic branch from origin/main.
# Usage: new-worktree.sh <issue> <owner> <slug> [feat|fix|docs|evidence]
# Path: {repo}/.worktrees/{issue}-{owner}-{slug}
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: $0 <issue> <owner> <slug> [feat|fix|docs|evidence]" >&2
  exit 2
fi

issue="$1"
owner="$2"
slug="$3"
kind="${4:-feat}"

case "$kind" in
  feat|fix|docs|evidence) ;;
  *)
    echo "invalid kind: $kind (use feat|fix|docs|evidence)" >&2
    exit 2
    ;;
esac

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "run from inside a git repository" >&2
  exit 1
fi

root="$(git rev-parse --show-toplevel)"
slot="${issue}-${owner}-${slug}"
path="${root}/.worktrees/${slot}"
branch="${kind}/${issue}-${slug}"

mkdir -p "${root}/.worktrees"
git fetch origin
if git show-ref --verify --quiet "refs/heads/${branch}"; then
  git worktree add "${path}" "${branch}"
else
  git worktree add -b "${branch}" "${path}" origin/main
fi

echo "worktree: ${path}"
echo "branch:   ${branch}"
echo "next:     cd \"${path}\" && git push -u origin HEAD"
