#!/usr/bin/env bash
# Client-side pre-push guard for agent-project-ops.
# Bypassable with --no-verify; server-side repository policy remains the real gate.
#
# stdin: <local_ref> <local_sha> <remote_ref> <remote_sha>
# args:  $1 remote name, $2 remote URL
set -euo pipefail

remote_name="${1:-}"
remote_url="${2:-}"
zero="0000000000000000000000000000000000000000"

root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "${root}" ]] || { echo "agent-project-ops hook: cannot resolve repository root" >&2; exit 1; }

deny() {
  echo "agent-project-ops hook: $*" >&2
  echo "This client hook is bypassable; do not use --no-verify to defeat project policy." >&2
  exit 1
}

# Use one URL guard implementation in both the methodology repo and generated
# business repos. Missing guard is a configuration error, not permission to push.
url_guard=""
for candidate in \
  "${root}/.agent-project-ops/scripts/lib/url-guard.sh" \
  "${root}/scripts/lib/url-guard.sh"
do
  if [[ -f "${candidate}" ]]; then
    url_guard="${candidate}"
    break
  fi
done
[[ -n "${url_guard}" ]] || deny "shared URL guard not found; reinstall/refresh agent-project-ops binding"
# shellcheck source=/dev/null
source "${url_guard}"
url_has_secrets "${remote_url}" && deny "remote URL is unsafe or may embed credentials/query tokens"

[[ "${remote_name}" == "origin" ]] || \
  deny "only the registered GitHub origin remote is an allowed push target"

# Use the same complete authority contract as the worktree lifecycle commands;
# reading just the first authority row misses extra remotes and legacy entries.
origin_identity="$(github_worktree_authority "$root")" || \
  deny "origin authority, remote registry and non-mirror configuration must be valid"
push_identity="$(github_repo_identity "$remote_url")" || \
  deny "actual push URL is not a supported GitHub repository URL"
[[ "$push_identity" == "$origin_identity" ]] || \
  deny "actual push destination differs from the GitHub origin repository"

# Query the real authority, not a possibly stale local origin/HEAD or an
# environment override. Include heads in the same successful advertisement so
# an unreachable/ambiguous repository cannot be mistaken for an empty one.
advertisement="$(git ls-remote --symref origin HEAD 'refs/heads/*')" || \
  deny "cannot query origin default branch; no push allowed"
default_branch="$(printf '%s\n' "$advertisement" | awk '$1=="ref:" && $3=="HEAD" {sub(/^refs\/heads\//,"",$2); print $2}')"
initial=0
heads="$(printf '%s\n' "$advertisement" | awk '$1 ~ /^[0-9a-f]+$/ && $2 ~ /^refs\/heads\// {print $2}')"
if [[ -z "$heads" ]]; then
  # There is no default branch yet. Only an explicit bootstrap declaration may
  # create the first branch; this value never overrides a real remote HEAD.
  default_branch="${APO_INITIAL_BRANCH:-}"
  [[ -n "$default_branch" ]] || deny "empty origin: explicit APO_INITIAL_BRANCH required for first push"
  initial=1
else
  [[ -n "$default_branch" ]] || deny "origin has branches but its default HEAD is unknown; repair the remote default branch"
  printf '%s\n' "$heads" | grep -Fxq "refs/heads/$default_branch" || deny "origin default HEAD does not name an advertised branch"
fi
git check-ref-format "refs/heads/$default_branch" >/dev/null 2>&1 || deny "invalid origin default branch"
[[ "$default_branch" != *$'\n'* ]] || deny "ambiguous origin default branch"

# Selected-layout repositories verify the generated bindings on every push.
# The methodology's self-dogfood checkout has no vendored descriptor.
if [[ -f "$root/.agent-project-ops/templates/project-options.json" || -f "$root/.agent-project-ops/scripts/project-settings.py" ]]; then
  checker="$root/.agent-project-ops/scripts/project-settings.py"
  [[ -f "$checker" ]] || deny "project settings checker missing"
  command -v python3 >/dev/null || deny "python3 required for binding checks"
  python3 "$checker" check --root "$root" || deny "project bindings differ from selected settings"
  python3 "$checker" check-core --root "$root" || deny "project core contract failed"
fi

while read -r local_ref local_sha remote_ref remote_sha; do
  [[ -z "${local_ref:-}" ]] && continue
  if [[ "$initial" -eq 1 && "$remote_ref" != "refs/heads/$default_branch" ]]; then
    deny "empty origin: first push must create declared initial branch $default_branch"
  fi

  # Default branch deletion is forbidden on every registered remote.
  if [[ "${local_sha}" == "${zero}" ]]; then
    if [[ "${remote_ref}" == "refs/heads/${default_branch}" ]]; then
      deny "refusing to delete ${default_branch} on ${remote_name}"
    fi
    continue
  fi

  # Topic branches may be pushed to origin. Bootstrap may create the authority
  # default branch once; later direct updates must go through PRs.
  if [[ "${remote_ref}" == "refs/heads/${default_branch}" ]]; then
    if [[ "$initial" -eq 1 && "${remote_sha}" == "${zero}" ]]; then
      continue
    fi
    deny "direct push to ${default_branch} on authority 'origin' is forbidden; open a PR"
  fi
done
