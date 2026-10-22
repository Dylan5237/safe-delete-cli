#!/usr/bin/env bash
# Start a task from a verified origin ref, not an assumed origin/main.
# auto (default): an idle primary checkout hosts the task branch, so a single task needs no
# extra folder; otherwise the task gets {repo}/.worktrees/{issue}-{owner}-{slug}, capped by
# max_worktrees (default 3; 0 = unlimited; exit 3 at the cap). Finished work is retired first
# by tidy-worktrees.sh (merged/closed PRs only, never uncommitted or unmerged work).
# Usage: new-worktree.sh <issue> <owner> <slug> [feat|fix|docs|evidence] [--base origin/BRANCH] [--save-base] [--here|--worktree]
set -euo pipefail

usage() { echo "usage: $0 <issue> <owner> <slug> [feat|fix|docs|evidence] [--base origin/BRANCH] [--save-base] [--here|--worktree]"; }
die() { printf 'new-worktree: error: %s\n' "$*" >&2; exit 2; }
script_dir="$(cd "$(dirname "$0")" && pwd)"

if [[ $# -lt 3 ]]; then usage >&2; exit 2; fi
issue="$1"
owner="$2"
slug="$3"
shift 3
for token in "$issue" "$owner" "$slug"; do
  [[ "$token" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ && "$token" != *..* ]] || die "unsafe issue/owner/slug: $token"
done
kind="feat"
if [[ $# -gt 0 && "$1" != --* ]]; then kind="$1"; shift; fi
case "$kind" in feat|fix|docs|evidence) ;; *) die "invalid kind: $kind" ;; esac

explicit_base=""
save_base=0
mode_flag=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      [[ $# -ge 2 && -n "$2" ]] || die "--base requires origin/BRANCH"
      [[ -z "$explicit_base" ]] || die "--base specified twice"
      explicit_base="$2"; shift 2 ;;
    --save-base) save_base=1; shift ;;
    --here|--worktree)
      [[ -z "$mode_flag" ]] || die "choose only one of --here or --worktree"
      mode_flag="${1#--}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

git rev-parse --show-toplevel >/dev/null 2>&1 || die "run inside a git repository"
# Anchor on the primary checkout so task folders never nest inside another task folder.
root="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"
[[ -n "$root" && -d "$root" ]] || die "cannot resolve the primary checkout"
source "$script_dir/lib/url-guard.sh"
authority="$(github_worktree_authority "$root")" \
  || die "origin authority check failed: require only GitHub origin, matching resolved fetch/push URLs and authority=origin registry"
assert_authority() {
  local current
  current="$(github_worktree_authority "$root")" \
    || die "origin authority check failed; no new task created"
  [[ "$current" == "$authority" ]] || die "origin authority changed; no new task created"
}
branch="$kind/$issue-$slug"
git check-ref-format --branch "$branch" >/dev/null 2>&1 || die "invalid branch: $branch"
git -C "$root" fetch --quiet --prune origin || die "cannot fetch origin; no worktree created"

# Ordinary retirement failures keep their existing warning behavior. An
# authority/preflight refusal is a hard stop, never a warning-and-continue.
if [[ -f "$script_dir/tidy-worktrees.sh" ]]; then
  if bash "$script_dir/tidy-worktrees.sh" --apply --quiet --no-fetch >&2; then
    :
  else
    tidy_rc=$?
    [[ "$tidy_rc" -ne 2 ]] || die "tidy-worktrees authority/preflight refused; no new task created"
    echo "new-worktree: warning: tidy-worktrees reported a problem (see above); continuing" >&2
  fi
fi
assert_authority

project_base=""
max_worktrees=3
worktree_mode=auto
seen_base=0
seen_max=0
seen_mode=0
seen_process=0
seen_selections=0
config="$root/.agent-project-ops/project-config"
if [[ -f "$config" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    case "$line" in
      ''|\#*) ;;
      task_base=*)
        [[ "$seen_base" -eq 0 ]] || die "duplicate task_base in $config"
        seen_base=1
        project_base="${line#task_base=}" ;;
      max_worktrees=*)
        [[ "$seen_max" -eq 0 ]] || die "duplicate max_worktrees in $config"
        seen_max=1
        max_worktrees="${line#max_worktrees=}"
        [[ "$max_worktrees" =~ ^[0-9]+$ ]] || die "max_worktrees must be a whole number (0 = unlimited): $line" ;;
      worktree_mode=*)
        [[ "$seen_mode" -eq 0 ]] || die "duplicate worktree_mode in $config"
        seen_mode=1
        worktree_mode="${line#worktree_mode=}"
        case "$worktree_mode" in auto|always) ;; *) die "worktree_mode must be auto or always: $line" ;; esac ;;
      process_mode=*)
        # Disposer-chosen process mode (PRINCIPLES §0). Validated only; it does
        # not change how this helper creates branches or folders.
        [[ "$seen_process" -eq 0 ]] || die "duplicate process_mode in $config"
        seen_process=1
        case "${line#process_mode=}" in light|standard) ;; *) die "process_mode must be light or standard: $line" ;; esac ;;
      agent_tools=*|external_tools=*) seen_selections=1 ;;
      *) die "unknown project-config entry (not executed): $line" ;;
    esac
  done < "$config"
  if [[ "$seen_selections" -eq 1 ]]; then
    python3 "$script_dir/project-settings.py" validate-config --root "$root" --source "$script_dir/.." \
      || die "invalid project selections in $config"
  fi
fi

base=""
source_name=""
if [[ -n "$explicit_base" ]]; then
  base="$explicit_base"; source_name="explicit --base"
elif [[ -n "$project_base" ]]; then
  base="$project_base"; source_name="project-config"
else
  remote_head="$(git -C "$root" ls-remote --symref origin HEAD 2>/dev/null | awk '$1=="ref:" && $3=="HEAD" {print $2; exit}' || true)"
  local_head="$(git -C "$root" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  if [[ "$remote_head" == refs/heads/* ]]; then
    base="$(printf '%s\n' "$remote_head" | sed 's#^refs/heads/#origin/#')"
    source_name="verified remote HEAD"
    if [[ -n "$local_head" && "$local_head" != "$base" ]]; then
      die "local origin/HEAD ($local_head) conflicts with verified remote default ($base); review and pass --base"
    fi
  else
    candidates="$(git -C "$root" for-each-ref --format='%(refname:short)' refs/remotes/origin | grep -v '^origin/HEAD$' || true)"
    count="$(printf '%s\n' "$candidates" | grep -c . || true)"
    if [[ "$count" -eq 1 ]]; then
      base="$candidates"; source_name="only origin branch"
    else
      printf 'new-worktree: available origin refs:\n%s\n' "$candidates" >&2
      die "task base is ambiguous; ask user with the host choice tool or pass --base origin/BRANCH"
    fi
  fi
fi

[[ "$base" == origin/* && "$base" != origin/HEAD ]] || die "task base must be origin/BRANCH, got: $base"
git check-ref-format "refs/remotes/$base" >/dev/null 2>&1 || die "invalid origin ref: $base"
git -C "$root" show-ref --verify --quiet "refs/remotes/$base" || die "origin ref not found after fetch: $base"
git -C "$root" rev-parse --verify --quiet "refs/remotes/$base^{commit}" >/dev/null || die "origin ref is not a commit: $base"

local_branch=0
remote_branch=0
if git -C "$root" show-ref --verify --quiet "refs/heads/$branch"; then local_branch=1; fi
if git -C "$root" show-ref --verify --quiet "refs/remotes/origin/$branch"; then remote_branch=1; fi
if [[ "$local_branch" -eq 1 || "$remote_branch" -eq 1 ]]; then
  [[ -z "$explicit_base" && "$save_base" -eq 0 ]] || die "branch exists; cannot change its base with --base/--save-base"
fi

# The primary checkout is idle when it is not on a task branch and has no changes at all.
current="$(git -C "$root" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
primary_status_paths=(.)
if [[ -d "$root/.worktrees" && ! -L "$root/.worktrees" ]]; then
  primary_status_paths+=(':(top,exclude).worktrees')
fi
primary_status="$(git -C "$root" status --porcelain --untracked-files=all --ignored=matching -- "${primary_status_paths[@]}")" \
  || die "cannot read primary checkout status"
if [[ -d "$root/.worktrees" && ! -L "$root/.worktrees" ]]; then
  primary_status="$(printf '%s\n' "$primary_status" | sed '\#^!! \.worktrees/$#d')"
fi
primary_idle=0
if [[ -n "$current" && ! "$current" =~ ^(feat|fix|docs|evidence)/ \
  && -z "$primary_status" ]]; then
  primary_idle=1
fi
mode=worktree
case "$mode_flag" in
  here)
    [[ "$primary_idle" -eq 1 ]] || die "primary checkout is busy (on ${current:-a detached HEAD} or has local/ignored files); use --worktree"
    mode=here ;;
  worktree) mode=worktree ;;
  *) if [[ "$worktree_mode" == auto && "$primary_idle" -eq 1 ]]; then mode=here; fi ;;
esac

assert_authority
if [[ "$mode" == here ]]; then
  path="$root"
  if [[ "$local_branch" -eq 1 ]]; then
    git -C "$root" switch --quiet "$branch"
  elif [[ "$remote_branch" -eq 1 ]]; then
    git -C "$root" switch --quiet --track -c "$branch" "origin/$branch"
  else
    git -C "$root" switch --quiet -c "$branch" "refs/remotes/$base"
  fi
else
  path="$root/.worktrees/$issue-$owner-$slug"
  [[ ! -e "$path" ]] || die "worktree slot already exists: $path"
  if [[ "$max_worktrees" -gt 0 ]]; then
    in_use="$(git -C "$root" worktree list --porcelain | sed -n 's/^worktree //p' | grep -F "$root/.worktrees/" || true)"
    in_use_count="$(printf '%s' "$in_use" | grep -c . || true)"
    if [[ "$in_use_count" -ge "$max_worktrees" ]]; then
      printf 'new-worktree: task folders in use (%s of max_worktrees=%s):\n%s\n' "$in_use_count" "$max_worktrees" "$in_use" >&2
      printf 'new-worktree: error: folder limit reached; nothing created. Finish, merge or park one (tidy-worktrees.sh --park <branch>) and retry, or queue this task.\n' >&2
      exit 3
    fi
  fi
  mkdir -p "$root/.worktrees"
  if [[ "$local_branch" -eq 1 ]]; then
    git -C "$root" worktree add "$path" "$branch"
  elif [[ "$remote_branch" -eq 1 ]]; then
    git -C "$root" worktree add --track -b "$branch" "$path" "origin/$branch"
  else
    git -C "$root" worktree add -b "$branch" "$path" "refs/remotes/$base"
  fi
fi

if [[ "$save_base" -eq 1 ]]; then
  assert_authority
  cfg="$path/.agent-project-ops/project-config"
  mkdir -p "$path/.agent-project-ops"
  { if [[ -f "$cfg" ]]; then grep -v '^task_base=' "$cfg" || true; fi; printf 'task_base=%s\n' "$base"; } > "$cfg.new"
  mv "$cfg.new" "$cfg"
  echo "project default created on task branch; include project-config in the reviewed PR"
fi

echo "mode:     $mode"
if [[ "$mode" == here ]]; then
  echo "workdir:  $path (primary checkout; single task, no extra folder)"
else
  echo "worktree: $path"
fi
echo "branch:   $branch"
echo "base:     $base ($source_name)"
echo "next:     cd \"$path\" && git push -u origin HEAD"
echo "finish:   after the PR merges, tidy-worktrees.sh --apply retires it (also runs before every new task)"
