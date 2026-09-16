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
