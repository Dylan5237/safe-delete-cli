#!/usr/bin/env bash
# Retire finished task folders (worktrees) and branches automatically, without losing work.
#
# Usage:
#   tidy-worktrees.sh [--apply] [--quiet] [--no-fetch] [--include-other] [--stale-days N]
#   tidy-worktrees.sh --park <branch>      pushed + clean task: remove its folder, keep the branch
#   tidy-worktrees.sh --abandon <branch>   decided on the Issue: push an archive tag, then delete
#
# Default is a read-only plan; --apply acts. Something is retired only with proof:
#   merged  GitHub PR MERGED whose head equals or contains the local tip (squash/rebase safe), or,
#           without gh, upstream origin/<branch> was deleted and the tip is in origin/<default>
#   closed  GitHub PR CLOSED unmerged: tag archive/<branch>-<sha7> is pushed to origin first
# Uncommitted/ignored files, commits newer than a merged head, open PRs, no PR, locked or detached
# folders, folders outside .worktrees/ (other tools) and anything unverifiable are kept and listed.
# Never touches the default branch, the configured task_base, or long-lived branch names.
# The last line is a fixed summary for status reports and acceptance proposals.
# Exit: 0 ok; 1 an action failed or was refused (e.g. folder busy on Windows; retried next run); 2 usage.
set -euo pipefail

die() { printf 'tidy-worktrees: error: %s\n' "$*" >&2; exit 2; }
refuse() { printf 'tidy-worktrees: refused: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; }

apply=0; quiet=0; do_fetch=1; include_other=0; stale_days=7; park=""; abandon=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) apply=1; shift ;;
    --quiet) quiet=1; shift ;;
    --no-fetch) do_fetch=0; shift ;;
    --include-other) include_other=1; shift ;;
    --stale-days)
      [[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] || die "--stale-days requires a whole number"
      stale_days="$2"; shift 2 ;;
    --park)
      [[ $# -ge 2 && -n "$2" ]] || die "--park requires a branch"
      park="$2"; shift 2 ;;
    --abandon)
      [[ $# -ge 2 && -n "$2" ]] || die "--abandon requires a branch"
      abandon="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done
[[ -z "$park" || -z "$abandon" ]] || die "--park and --abandon cannot be combined"

git rev-parse --git-dir >/dev/null 2>&1 || die "run inside a git repository"
primary="$(git worktree list --porcelain | sed -n '1s/^worktree //p')"
[[ -n "$primary" && -d "$primary" ]] || die "cannot resolve the primary checkout"
script_dir="$(cd "$(dirname "$0")" && pwd)"
source "$script_dir/lib/url-guard.sh"
authority="$(github_worktree_authority "$primary")" \
  || die "origin authority check failed: require only GitHub origin, matching resolved fetch/push URLs and authority=origin registry"
assert_authority() {
  local current
  current="$(github_worktree_authority "$primary")" \
    || die "origin authority check failed; no further worktree actions permitted"
  [[ "$current" == "$authority" ]] || die "origin authority changed during retirement"
}
g() {
  case "$1" in fetch|push) assert_authority ;; esac
  git -C "$primary" "$@"
}
caller_top="$(git rev-parse --show-toplevel 2>/dev/null || true)"

fetch_state=skipped
if [[ "$do_fetch" -eq 1 ]]; then
  if g fetch --quiet --prune origin >/dev/null 2>&1; then fetch_state=ok; else fetch_state=failed; fi
fi

default_ref="$(g symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
if [[ -z "$default_ref" && "$fetch_state" == ok ]]; then
  remote_head="$(g ls-remote --symref origin HEAD 2>/dev/null | awk '$1=="ref:" && $3=="HEAD" {print $2; exit}' || true)"
  if [[ "$remote_head" == refs/heads/* ]]; then default_ref="origin/${remote_head#refs/heads/}"; fi
fi
if [[ -n "$default_ref" ]] && ! g show-ref --verify --quiet "refs/remotes/$default_ref"; then default_ref=""; fi
default_name="${default_ref#origin/}"

config="$primary/.agent-project-ops/project-config"
task_base_name=""; max_worktrees=3
if [[ -f "$config" ]]; then
  task_base_name="$(sed -n 's#^task_base=origin/##p' "$config" | tr -d '\r' | head -1)"
  configured_max="$(sed -n 's/^max_worktrees=//p' "$config" | tr -d '\r' | head -1)"
  if [[ "$configured_max" =~ ^[0-9]+$ ]]; then max_worktrees="$configured_max"; fi
fi

# PR facts come from the GitHub CLI; without it only offline proof is used.
gh_repo="$authority"
gh_ok=0
if [[ -n "$gh_repo" ]] && command -v gh >/dev/null 2>&1 \
  && (cd "$primary" && GH_PROMPT_DISABLED=1 gh repo view "$gh_repo" --json name </dev/null >/dev/null 2>&1); then
  gh_ok=1
fi

is_protected() {
  local b="$1"
  if [[ -n "$default_name" && "$b" == "$default_name" ]]; then return 0; fi
  if [[ -n "$task_base_name" && "$b" == "$task_base_name" ]]; then return 0; fi
  case "$b" in
    main|master|develop|dev|trunk|staging|production|prod|gh-pages|release|release/*|hotfix/*) return 0 ;;
  esac
  return 1
}
in_scope() {
  local b="$1"
  if is_protected "$b"; then return 1; fi
  if [[ "$b" =~ ^(feat|fix|docs|evidence)/. ]]; then return 0; fi
  if [[ "$include_other" -eq 1 ]]; then return 0; fi
  return 1
}

removed=0; deleted=0; deleted_remote=0; archived=0; kept=0; stale=0; failed=0
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
errf="$work/err"
: > "$work/handled"

say() { printf '%-6s %-15s %s  (%s)\n' "$1" "$2" "$3" "$4"; }
rel() { printf '%s' "${1#"$primary"/}"; }
age_days() {
  local ts now
  ts="$(g log -1 --format=%ct "$1" 2>/dev/null || printf 0)"
  now="$(date +%s)"
  printf '%s' $(( (now - ${ts:-0}) / 86400 ))
}
keep() { # kind target reason [sha]
  local note="$3" d
  if [[ -n "${4:-}" ]]; then
    d="$(age_days "$4")"
    if [[ "$d" -gt "$stale_days" ]]; then note="$note; stale ${d}d"; stale=$((stale + 1)); fi
  fi
  kept=$((kept + 1))
  if [[ "$quiet" -eq 0 ]]; then say keep "$1" "$2" "$note"; fi
  return 0
}
act() { # action target reason command...
  local action="$1" target="$2" reason="$3"
  shift 3
  if [[ "$apply" -eq 0 ]]; then say plan "$action" "$target" "$reason"; return 0; fi
  assert_authority
  if "$@" >/dev/null 2>"$errf" </dev/null; then say done "$action" "$target" "$reason"; return 0; fi
  failed=$((failed + 1))
  say failed "$action" "$target" "$reason; $(tr '\n' ' ' < "$errf" | cut -c1-200)"
  return 1
}

status_of() { # ignored data is local-only too; exclude only the primary's task-folder root
  if [[ "$1" == "$primary" && -d "$primary/.worktrees" && ! -L "$primary/.worktrees" ]]; then
    # Git still reports an ignored nested repository despite the pathspec exclusion.
    git -C "$1" status --porcelain --untracked-files=all --ignored=matching -- . ':(top,exclude).worktrees' \
      | sed '\#^!! \.worktrees/$#d'
  else
    git -C "$1" status --porcelain --untracked-files=all --ignored=matching
  fi
}
local_files_reason() {
  if [[ "$1" == '!! '* || "$1" == *$'\n!! '* ]]; then
    printf 'ignored files (not backed up by Git archive tags)'
  else
    printf 'uncommitted changes'
  fi
}
contains() { # ancestor descendant
  g cat-file -e "$2^{commit}" 2>/dev/null && g merge-base --is-ancestor "$1" "$2" 2>/dev/null
}
upstream_gone() { # pushed with -u to origin/<branch>, and that branch is gone now
  local b="$1"
  [[ "$(g config --get "branch.$b.remote" || true)" == origin ]] || return 1
  [[ "$(g config --get "branch.$b.merge" || true)" == "refs/heads/$b" ]] || return 1
  if g show-ref --verify --quiet "refs/remotes/origin/$b"; then return 1; fi
  return 0
}
pr_lines() {
  (cd "$primary" && GH_PROMPT_DISABLED=1 gh pr list -R "$gh_repo" --head "$1" --state all --limit 20 \
    --json number,state,headRefOid --jq '.[] | "\(.number) \(.state) \(.headRefOid)"' </dev/null 2>/dev/null)
}

v_state=""; v_pr=""; v_head=""
judge() { # branch tip -> v_state: merged|landed|closed|open|ahead|none|unknown
  local b="$1" tip="$2" lines num state head open_pr="" merged_pr="" merged_head="" closed_pr="" ahead_pr=""
  v_state=unknown; v_pr=""; v_head=""
  if [[ "$gh_ok" -eq 1 ]] && lines="$(pr_lines "$b")"; then
    while read -r num state head; do
      [[ -n "${num:-}" ]] || continue
      case "$state" in
        OPEN) open_pr="$num" ;;
        CLOSED) closed_pr="$num" ;;
        MERGED)
          if ! g cat-file -e "$head^{commit}" 2>/dev/null; then
            g fetch --quiet origin "refs/pull/$num/head" >/dev/null 2>&1 || true
          fi
          if [[ "$head" == "$tip" ]] || contains "$tip" "$head"; then
            merged_pr="$num"; merged_head="$head"
          else
            ahead_pr="$num"
          fi ;;
      esac
    done <<< "$lines"
    if [[ -n "$open_pr" ]]; then v_state=open; v_pr="$open_pr"
    elif [[ -n "$merged_pr" ]]; then v_state=merged; v_pr="$merged_pr"; v_head="$merged_head"
    elif [[ -n "$closed_pr" ]]; then v_state=closed; v_pr="$closed_pr"
    elif [[ -n "$ahead_pr" ]]; then v_state=ahead; v_pr="$ahead_pr"
    else v_state=none
    fi
  fi
  if [[ "$v_state" == unknown || "$v_state" == none ]] && [[ -n "$default_ref" ]] \
    && upstream_gone "$b" && contains "$tip" "refs/remotes/$default_ref"; then
    v_state=landed
  fi
  return 0
}
why() {
  case "$v_state" in
    merged) printf 'merged PR #%s' "$v_pr" ;;
    landed) printf 'origin branch deleted after landing in %s' "$default_ref" ;;
    closed) printf 'PR #%s closed without merge' "$v_pr" ;;
    open) printf 'PR #%s open (in progress)' "$v_pr" ;;
    ahead) printf 'has commits newer than merged PR #%s' "$v_pr" ;;
    none) printf 'no PR yet (new, parked, or never opened)' ;;
    *) printf 'cannot verify merge without gh (GitHub CLI)' ;;
  esac
}

archive_tag() { printf 'archive/%s-%s' "$1" "${2:0:7}"; }
push_archive() { # branch sha
  local tag
  tag="$(archive_tag "$1" "$2")"
  g check-ref-format "refs/tags/$tag" || return 1
  if ! g rev-parse -q --verify "refs/tags/$tag" >/dev/null; then g tag "$tag" "$2"; fi
  [[ "$(g rev-parse "refs/tags/$tag^{commit}")" == "$2" ]] || return 1
  g push --quiet origin "refs/tags/$tag:refs/tags/$tag"
}
archive() { # branch sha reason
  if act archive "$1 -> $(archive_tag "$1" "$2")" "$3" push_archive "$1" "$2"; then
    if [[ "$apply" -eq 1 ]]; then archived=$((archived + 1)); fi
    return 0
  fi
  return 1
}
drop_remote() { # branch expected_sha reason
  if act delete-remote "origin/$1" "$3" \
    g push --quiet --force-with-lease="refs/heads/$1:$2" origin ":refs/heads/$1"; then
    if [[ "$apply" -eq 1 ]]; then deleted_remote=$((deleted_remote + 1)); fi
  fi
  return 0
}
retire_branch() { # branch tip reason (uses v_head)
  local b="$1" tip="$2" reason="$3" r
  printf '%s\n' "$b" >> "$work/handled"
  if g show-ref --verify --quiet "refs/heads/$b"; then
    if act delete-branch "$b" "$reason" g branch -D "$b"; then
      if [[ "$apply" -eq 1 ]]; then deleted=$((deleted + 1)); fi
    else return 0; fi
  fi
  if g show-ref --verify --quiet "refs/remotes/origin/$b"; then
    r="$(g rev-parse "refs/remotes/origin/$b")"
    if [[ "$r" == "$tip" ]] || contains "$r" "$tip" \
      || { [[ -n "$v_head" ]] && { [[ "$r" == "$v_head" ]] || contains "$r" "$v_head"; }; }; then
      drop_remote "$b" "$r" "$reason"
    else
      keep remote "origin/$b" "has commits not in the retired tip" "$r"
    fi
  fi
  return 0
}
switch_primary() {
  local merge_error
  if g show-ref --verify --quiet "refs/heads/$default_name"; then
    g switch --quiet "$default_name" || return 1
  else
    g switch --quiet -c "$default_name" --track "origin/$default_name" || return 1
  fi
  if ! merge_error="$(g merge --ff-only --quiet "refs/remotes/origin/$default_name" 2>&1)"; then
    echo "fast-forward failed: primary checkout $default_name -> origin/$default_name; task branch preserved; reconcile the mainline before retrying" >&2
    printf '%s\n' "$merge_error" >&2
    return 1
  fi
}
release_checkout() { # path reason
  local dirty label
  label="$(rel "$1")"
  if [[ "$1" == "$primary" ]]; then label="primary checkout"; fi
  # Recheck immediately before removing a folder or switching the primary checkout.
  if ! dirty="$(status_of "$1" 2>/dev/null)"; then keep folder "$label" "cannot read status"; return 1; fi
  if [[ -n "$dirty" ]]; then keep folder "$label" "$(local_files_reason "$dirty"); preserved"; return 1; fi
  if [[ "$1" == "$primary" ]]; then
    [[ -n "$default_name" ]] || { keep folder "primary checkout" "$2; default branch unknown, cannot switch back"; return 1; }
    act switch-primary "primary checkout -> $default_name" "$2" switch_primary
  else
    if act remove-folder "$(rel "$1")" "$2" g worktree remove "$1"; then
      if [[ "$apply" -eq 1 ]]; then removed=$((removed + 1)); fi
      return 0
    fi
    return 1
  fi
}

# Snapshot of checkouts: path<TAB>branch<TAB>locked<TAB>prunable; the first record is the primary.
g worktree list --porcelain | awk '
  /^worktree /{ if (p != "") print p "\t" b "\t" l "\t" x; p = substr($0, 10); b = ""; l = 0; x = 0; next }
  /^branch /{ b = substr($0, 8); sub(/^refs\/heads\//, "", b); next }
  /^locked/{ l = 1; next }
  /^prunable/{ x = 1; next }
  END { if (p != "") print p "\t" b "\t" l "\t" x }' > "$work/checkouts"
cut -f2 "$work/checkouts" | sed '/^$/d' > "$work/checked-out"
locate_checkout() { awk -F'\t' -v b="$1" '$2 == b { print $1; exit }' "$work/checkouts"; }

if [[ -n "$park" ]]; then
  in_scope "$park" || refuse "$park is not a task branch"
  path="$(locate_checkout "$park")"
  [[ -n "$path" ]] || refuse "$park is not checked out; nothing to park"
  dirty="$(status_of "$path")" || refuse "cannot read status in $(rel "$path")"
  [[ -z "$dirty" ]] || refuse "$(local_files_reason "$dirty") in $(rel "$path"); local files preserved"
  tip="$(git -C "$path" rev-parse HEAD)"
  [[ "$(g rev-parse -q --verify "refs/remotes/origin/$park" || true)" == "$tip" ]] \
    || refuse "origin/$park is not at $tip; push first: git -C \"$path\" push -u origin HEAD"
  apply=1
  release_checkout "$path" "parked $park; branch kept locally and on origin" || exit 1
  echo "parked: $park (resume: new-worktree.sh with the same issue, owner, slug and kind)"
  exit 0
fi

if [[ -n "$abandon" ]]; then
  b="$abandon"
  if is_protected "$b"; then refuse "$b is a protected long-lived branch"; fi
  path="$(locate_checkout "$b")"
  if [[ -n "$path" ]]; then
    dirty="$(status_of "$path")" || refuse "cannot read status in $(rel "$path")"
    [[ -z "$dirty" ]] || refuse "$(local_files_reason "$dirty") in $(rel "$path"); local files preserved"
  fi
  local_tip="$(g rev-parse -q --verify "refs/heads/$b" || true)"
  remote_tip="$(g rev-parse -q --verify "refs/remotes/origin/$b" || true)"
  [[ -n "$local_tip$remote_tip" ]] || refuse "no branch named $b locally or on origin"
  if [[ "$gh_ok" -eq 1 ]]; then
    judge "$b" "${local_tip:-$remote_tip}"
    [[ "$v_state" != open ]] || refuse "PR #$v_pr is still open; close it first"
  fi
  apply=1
  if [[ -n "$local_tip" ]]; then archive "$b" "$local_tip" "abandoned (decision on the Issue)" || exit 1; fi
  if [[ -n "$remote_tip" && "$remote_tip" != "$local_tip" ]] \
    && ! { [[ -n "$local_tip" ]] && contains "$remote_tip" "$local_tip"; }; then
    archive "$b" "$remote_tip" "abandoned (decision on the Issue; origin copy)" || exit 1
  fi
  if [[ -n "$path" ]]; then release_checkout "$path" "abandoned $b" || exit 1; fi
  if [[ -n "$local_tip" ]]; then act delete-branch "$b" "abandoned; archived" g branch -D "$b" || exit 1; fi
  if [[ -n "$remote_tip" ]]; then
    act delete-remote "origin/$b" "abandoned; archived" \
      g push --quiet --force-with-lease="refs/heads/$b:$remote_tip" origin ":refs/heads/$b" || exit 1
  fi
  echo "abandoned: $b (restore any time: git switch -c $b <archive tag>)"
  exit 0
fi

process_checkout() { # path branch
  local path="$1" b="$2" label dirty tip reason
  label="$(rel "$path")"
  if [[ "$path" == "$primary" ]]; then label="primary checkout"; fi
  if ! dirty="$(status_of "$path" 2>/dev/null)"; then keep folder "$label" "cannot read status"; return 0; fi
  tip="$(git -C "$path" rev-parse HEAD)"
  if [[ -n "$dirty" ]]; then keep folder "$label" "$(local_files_reason "$dirty") on $b" "$tip"; return 0; fi
  judge "$b" "$tip"
  reason="$(why)"
  case "$v_state" in
    merged|landed|closed)
      if [[ "$v_state" == closed ]]; then archive "$b" "$tip" "$reason" || return 0; fi
      release_checkout "$path" "$reason" || return 0
      retire_branch "$b" "$tip" "$reason" ;;
    *) keep folder "$label" "$b: $reason" "$tip" ;;
  esac
  return 0
}

prunable=0; first=1
while IFS=$'\t' read -r path b locked prun <&3; do
  if [[ "$first" -eq 1 ]]; then
    first=0
    if [[ -n "$b" ]] && in_scope "$b"; then process_checkout "$path" "$b"; fi
    continue
  fi
  if [[ "$prun" -eq 1 ]]; then prunable=$((prunable + 1)); continue; fi
  if [[ "$path" != "$primary/.worktrees/"* ]]; then keep folder "$path" "outside .worktrees/ (another tool); left alone"; continue; fi
  if [[ "$locked" -eq 1 ]]; then keep folder "$(rel "$path")" "locked"; continue; fi
  if [[ -n "$caller_top" && "$path" == "$caller_top" ]]; then keep folder "$(rel "$path")" "current directory of this command"; continue; fi
  if [[ -z "$b" ]]; then keep folder "$(rel "$path")" "detached HEAD"; continue; fi
  if ! in_scope "$b"; then keep folder "$(rel "$path")" "$b is not a task branch"; continue; fi
  process_checkout "$path" "$b"
done 3< "$work/checkouts"

# Local branches without a checkout (finished elsewhere, parked, or left behind).
g for-each-ref --format='%(refname)' refs/heads | sed 's#^refs/heads/##' > "$work/local"
while read -r b <&3; do
  if grep -Fxq -- "$b" "$work/checked-out" || ! in_scope "$b"; then continue; fi
  tip="$(g rev-parse "refs/heads/$b")"
  judge "$b" "$tip"
  reason="$(why)"
  case "$v_state" in
    merged|landed) retire_branch "$b" "$tip" "$reason" ;;
    closed) if archive "$b" "$tip" "$reason"; then retire_branch "$b" "$tip" "$reason"; fi ;;
    *) keep branch "$b" "$reason" "$tip" ;;
  esac
done 3< "$work/local"

# Branches that exist only on origin.
g for-each-ref --format='%(refname)' refs/remotes/origin | sed 's#^refs/remotes/origin/##' | grep -vx 'HEAD' > "$work/remote" || true
while read -r b <&3; do
  if g show-ref --verify --quiet "refs/heads/$b" || grep -Fxq -- "$b" "$work/handled" || ! in_scope "$b"; then continue; fi
  r="$(g rev-parse "refs/remotes/origin/$b")"
  judge "$b" "$r"
  reason="$(why)"
  case "$v_state" in
    merged) drop_remote "$b" "$r" "$reason" ;;
    closed) if archive "$b" "$r" "$reason"; then drop_remote "$b" "$r" "$reason"; fi ;;
    *) keep remote "origin/$b" "$reason" "$r" ;;
  esac
done 3< "$work/remote"

if [[ "$prunable" -gt 0 ]]; then
  act prune ".git/worktrees" "$prunable registered folder(s) already deleted" g worktree prune || true
fi

left=0
for folder in "$primary/.worktrees/"* "$primary/.worktrees/".[!.]* "$primary/.worktrees/"..?*; do
  if [[ -d "$folder" ]]; then left=$((left + 1)); fi
done
mode=apply; limit="$max_worktrees"; gh_word=off
if [[ "$apply" -eq 0 ]]; then mode=report; fi
if [[ "$limit" -eq 0 ]]; then limit=unlimited; fi
if [[ "$gh_ok" -eq 1 ]]; then gh_word=ok; fi
printf 'apo-tidy: mode=%s gh=%s fetch=%s folders_removed=%s branches_deleted=%s remote_deleted=%s archived=%s kept=%s stale=%s failed=%s folders_left=%s/%s\n' \
  "$mode" "$gh_word" "$fetch_state" "$removed" "$deleted" "$deleted_remote" "$archived" "$kept" "$stale" "$failed" "$left" "$limit"
[[ "$failed" -eq 0 ]] || exit 1
