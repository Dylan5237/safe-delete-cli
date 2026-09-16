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
default_branch="${APO_DEFAULT_BRANCH:-main}"

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

registry="${root}/.agent-project-ops/remotes"
[[ -f "${registry}" ]] || deny "remote registry missing: ${registry}; classify remotes before pushing"

authority="$(sed -n 's/^authority=//p' "${registry}" | head -1)"
projection_csv="$(sed -n 's/^projection=//p' "${registry}" | head -1)"
[[ -n "${authority}" ]] || deny "remote registry has no authority entry"

is_authority=0
is_projection=0
[[ "${remote_name}" == "${authority}" ]] && is_authority=1

if [[ -n "${projection_csv}" && "${projection_csv}" != "(none)" ]]; then
  IFS=',' read -r -a projection_names <<< "${projection_csv}"
  for p in "${projection_names[@]}"; do
    p="${p//[[:space:]]/}"
    [[ -n "${p}" && "${remote_name}" == "${p}" ]] && is_projection=1
  done
fi

if [[ "${is_authority}" -eq 0 && "${is_projection}" -eq 0 ]]; then
  deny "remote '${remote_name}' is unregistered (authority='${authority}', projection='${projection_csv:-none}'); fail closed"
fi

resolve_authority_tip() {
  local tip=""
  tip="$(git rev-parse --verify -q "refs/remotes/${authority}/${default_branch}" 2>/dev/null || true)"
  [[ -n "${tip}" ]] || return 1
  printf '%s\n' "${tip}"
}

while read -r local_ref local_sha remote_ref remote_sha; do
  [[ -z "${local_ref:-}" ]] && continue

  # Default branch deletion is forbidden on every registered remote.
  if [[ "${local_sha}" == "${zero}" ]]; then
    if [[ "${remote_ref}" == "refs/heads/${default_branch}" ]]; then
      deny "refusing to delete ${default_branch} on ${remote_name}"
    fi
    continue
  fi

  if [[ "${is_projection}" -eq 1 ]]; then
    [[ "${remote_ref}" == "refs/heads/${default_branch}" ]] || \
      deny "projection accepts only ${default_branch}; topic branches push to ${authority}"

    authority_tip="$(resolve_authority_tip || true)"
    [[ -n "${authority_tip}" ]] || \
      deny "cannot resolve refs/remotes/${authority}/${default_branch}; fetch authority before projecting"

    # A projection is a projection of the current authority tip, not merely any
    # commit that happens to be a fast-forward of its previous state.
    [[ "${local_sha}" == "${authority_tip}" ]] || \
      deny "projection candidate ${local_sha} is not current authority tip ${authority_tip}"

    if [[ "${remote_sha}" != "${zero}" ]]; then
      git merge-base --is-ancestor "${remote_sha}" "${local_sha}" 2>/dev/null || \
        deny "non-fast-forward projection update is forbidden"
    fi
    continue
  fi

  # Registered authority: topic branches are allowed. Bootstrap may create the
  # authority default branch once; later direct updates must go through PRs.
  if [[ "${remote_ref}" == "refs/heads/${default_branch}" ]]; then
    if [[ "${remote_sha}" == "${zero}" ]]; then
      continue
    fi
    deny "direct push to ${default_branch} on authority '${authority}' is forbidden; open a PR"
  fi
done
