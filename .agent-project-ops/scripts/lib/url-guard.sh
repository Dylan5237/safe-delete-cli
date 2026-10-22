#!/usr/bin/env bash
# Shared URL safety checks for agent-project-ops shell tooling.
# Source this file; do not execute it as a standalone command.

url_has_secrets() {
  local u="${1:-}"

  # Query strings do not belong in canonical Git remote URLs in this
  # methodology. Treat any query as secret-bearing / unsafe by default.
  case "${u}" in
    http://*\?*|https://*\?*) return 0 ;;
  esac

  # Reject HTTP(S) user:password/token@host credentials. SSH forms such as
  # ssh://git@host/repo.git and git@host:group/repo.git remain valid.
  case "${u}" in
    http://*:*@*|https://*:*@*) return 0 ;;
  esac

  # Defense in depth for common token prefixes even when URL syntax is odd.
  case "${u}" in
    *ghp_*|*github_pat_*|*glpat-*) return 0 ;;
  esac

  return 1
}

# Public GitHub authority identity, independent of HTTPS/SSH spelling. Reject
# ambiguous paths, credentials, URL options, other hosts and local transports.
github_repo_identity() {
  local value owner repo
  url_has_secrets "${1:-}" && return 1
  value="$(printf '%s' "${1:-}" | LC_ALL=C tr '[:upper:]' '[:lower:]')"
  case "$value" in
    https://github.com/*) value="${value#https://github.com/}" ;;
    ssh://git@github.com/*) value="${value#ssh://git@github.com/}" ;;
    git@github.com:*) value="${value#git@github.com:}" ;;
    *) return 1 ;;
  esac
  value="${value%/}"
  [[ "$value" =~ ^([a-z0-9_.-]+)/([a-z0-9_.-]+)$ ]] || return 1
  owner="${BASH_REMATCH[1]}"
  repo="${BASH_REMATCH[2]%.git}"
  case "$owner" in .|..) return 1 ;; esac
  case "$repo" in ''|.|..) return 1 ;; esac
  printf '%s/%s\n' "$owner" "$repo"
}

# Inspect resolved URLs so url.*.insteadOf / pushInsteadOf and every pushurl
# participate in the same check. This is local and never contacts a server.
github_origin_identity() {
  local root="$1" fetch_urls push_urls url current identity="" fetch_count=0 push_count=0 count=0
  # A sentinel preserves embedded/trailing newlines instead of letting command
  # substitution trim them into an apparently valid address.
  fetch_urls="$(git -C "$root" remote get-url --all origin 2>/dev/null && printf '.')" || return 1
  push_urls="$(git -C "$root" remote get-url --push --all origin 2>/dev/null && printf '.')" || return 1
  fetch_urls="${fetch_urls%.}"; fetch_urls="${fetch_urls%$'\n'}"
  push_urls="${push_urls%.}"; push_urls="${push_urls%$'\n'}"
  [[ -n "$fetch_urls" && -n "$push_urls" ]] || return 1
  while IFS= read -r -d '' url; do fetch_count=$((fetch_count + 1)); done \
    < <(git -C "$root" config --null --get-all remote.origin.url)
  while IFS= read -r -d '' url; do push_count=$((push_count + 1)); done \
    < <(git -C "$root" config --null --get-all remote.origin.pushurl)
  [[ "$fetch_count" -gt 0 ]] || return 1
  [[ "$push_count" -gt 0 ]] || push_count="$fetch_count"
  while IFS= read -r url; do
    current="$(github_repo_identity "$url")" || return 1
    if [[ -z "$identity" ]]; then identity="$current"; fi
    [[ "$current" == "$identity" ]] || return 1
    count=$((count + 1))
  done <<< "${fetch_urls}
${push_urls}"
  [[ "$count" -eq $((fetch_count + push_count)) ]] || return 1
  printf '%s\n' "$identity"
}

# Worktree lifecycle commands must validate their authority themselves; hooks
# are not inherited by clones and cannot protect fetches or local retirement.
# Return only the safe identity, never an untrusted URL or registry value.
github_worktree_authority() {
  local root="$1" registry line entries=0 mirror rc
  [[ "$(git -C "$root" remote 2>/dev/null)" == origin ]] || return 1
  registry="$root/.agent-project-ops/remotes"
  [[ -f "$registry" && ! -L "$registry" ]] || return 1
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == authority=origin ]] || return 1
    entries=$((entries + 1))
  done < "$registry"
  [[ "$entries" -eq 1 ]] || return 1
  if mirror="$(git -C "$root" config --bool --get remote.origin.mirror 2>/dev/null)"; then
    [[ "$mirror" == false ]] || return 1
  else
    rc=$?
    [[ "$rc" -eq 1 ]] || return 1
  fi
  github_origin_identity "$root"
}
