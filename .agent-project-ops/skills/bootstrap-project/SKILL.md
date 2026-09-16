---
name: bootstrap-project
description: >
  Initialize a new generic git project using Dylan5237/agent-project-ops:
  create a local folder, durable Agent binding files, a pinned methodology
  snapshot, .worktrees/, a GitHub origin as the single write authority, and an
  optional projection remote. Use for one-shot project initialization; not for
  product/domain setup or creating a second source of truth.
---

# Bootstrap project

Read [PRINCIPLES.md](../../PRINCIPLES.md) first. This skill creates and binds a repository; it does not Freeze product scope, implement features, or Accept phases.

Design: [RFC 0001](../../docs/rfcs/0001-bootstrap-and-binding.md) plus its [post-audit hardening contract](../../docs/rfcs/0001-bootstrap-and-binding-hardening-contract.md).

## Required path

1. Confirm the destination is new/empty. Existing repositories are an adoption task, not this bootstrap path.
2. Collect a real project slug and real disposer GitHub handle. Do not emit placeholder `@DISPOSER`.
3. Ask whether a projection remote is required. If yes, accept only a credential-free Git URL; it remains projection-only.
4. Run `scripts/bootstrap-project.sh --dry-run ...` first when environment behavior is uncertain, then the real command.
5. After scaffold, verify `.agent-project-ops/PIN` contains a real SHA and `.agent-project-ops/remotes` classifies authority/projection.
6. Verify `git config --get core.hooksPath` is `.githooks` in the bootstrap checkout. Remember a later clone will not inherit it; root `AGENTS.md` instructs the next Agent to run the installer.
7. If GitHub creation is enabled, read the reported protection capability: A (code-owner review enforced), B (PR-only), or C (unprotected/BLOCKED). Never upgrade the wording beyond what was verified.
8. Run `playbooks/start-project.md` next. No `feat/` / `fix/` implementation before Freeze.

## Important identity limit

If the local Agent and the human disposer use the **same GitHub identity**, GitHub cannot distinguish which one clicked/pushed/merged. CODEOWNERS cannot create a human-vs-Agent security boundary in that configuration. Default bootstrap therefore requests PR-only protection (B); request code-owner review (A) only when the repository has a genuinely independent reviewer/identity and the user wants that gate.

## Fail closed

- Methodology source is not a git checkout / SHA cannot be determined → stop; supported bootstrap never writes silent `sha=unknown`.
- GitHub creation requested but `gh` is unavailable/unauthenticated → stop.
- Unknown remote → no push.
- Projection candidate is not current authority tip → no projection push.
- Server protection request cannot be enabled/verified → report capability C / BLOCKED; do not claim protection exists.
- Do not use `--no-verify` as a workflow shortcut.
