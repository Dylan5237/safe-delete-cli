#!/usr/bin/env bash
set -euo pipefail

root="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "install-hooks: not inside a git repository" >&2
  exit 1
}

hook="${root}/.githooks/pre-push"
[[ -f "${hook}" ]] || {
  echo "install-hooks: missing tracked hook: ${hook}" >&2
  echo "Refresh/bootstrap agent-project-ops binding before enabling hooks." >&2
  exit 1
}

chmod +x "${hook}"
git -C "${root}" config core.hooksPath .githooks

actual="$(git -C "${root}" config --get core.hooksPath || true)"
[[ "${actual}" == ".githooks" ]] || {
  echo "install-hooks: failed to set core.hooksPath=.githooks" >&2
  exit 1
}

printf 'hooks installed: core.hooksPath=%s\n' "${actual}"
