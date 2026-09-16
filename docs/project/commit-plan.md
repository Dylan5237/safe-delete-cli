# safe-delete-cli atomic commit plan

Status: proposed on 2026-09-16 by `Codex / Luna`. This plan is subordinate to
the Phase contracts and disposer decisions recorded in GitHub Issues. It does
not authorize implementation before `FREEZE ACK`.

## P0 — control plane

- `chore: bootstrap agent-project-ops binding` — generated binding, pinned
  methodology snapshot, templates, hooks, and origin-only registry. Landed as
  `46a2066` on `main` by the bootstrap playbook.
- `docs: add control-plane pointers and phase map` — this document and the
  Command Center/Phase index links. Proposed in the PR for Issue #1.

P0 deliberately contains no safe-delete product code.

## P1 — Architecture Contract Freeze

Issue: [#3](https://github.com/Dylan5237/safe-delete-cli/issues/3)

- `docs: draft safe-delete architecture contract` — behavior, storage, CLI,
  hook, purge, and evidence boundaries in one reviewable contract.
- `docs: map phase interfaces to frozen contract` — link P2–P6 acceptance
  tests to named contract sections and record unresolved questions.
- `docs: record P1 freeze decision` — update the issue only after the disposer
  posts `FREEZE ACK`; no implementation code belongs here.

## P2 — CLI + ledger + restore

Issue: [#4](https://github.com/Dylan5237/safe-delete-cli/issues/4)

- `feat: add unified trash move primitive` — one focused move operation for the
  frozen file/directory and failure semantics.
- `feat: add minimum ledger writer` — append the frozen minimum record for each
  successful operation.
- `feat: add restore command` — lookup, collision handling, and recovery under
  the frozen contract.
- `test: cover cli ledger and restore contract` — implementation tests only;
  proof artifacts remain separate from the implementation PR.

## P3 — Rich metadata

Issue: [#5](https://github.com/Dylan5237/safe-delete-cli/issues/5)

- `feat: add rich deletion metadata schema` — stable fields and versioning.
- `feat: record project session reason agent and timestamp` — source and
  missing-value policy for `original_path`, `project`, `session_id`, `reason`,
  `agent`, and `timestamp`.
- `test: preserve legacy ledger restore compatibility` — prove P2 records and
  restore behavior remain valid.

## P4 — Hook enforcement

Issue: [#6](https://github.com/Dylan5237/safe-delete-cli/issues/6)

- `feat: add safe-delete hook boundary` — PreToolUse/rm-shim contract and
  supported installation path.
- `feat: reject raw deletion attempts` — deterministic routing/denial and
  operator-visible errors, within the frozen client-side limits.
- `test: cover hook enforcement paths` — allowed, rejected, disabled, and
  unsupported host cases.

## P5 — Timed purge

Issue: [#7](https://github.com/Dylan5237/safe-delete-cli/issues/7)

- `feat: add retention eligibility policy` — age, clock, timezone, and
  exclusion rules.
- `feat: add periodic purge runner` — idempotent candidate processing and
  auditable outcomes.
- `test: cover purge dry-run and partial failure` — retention safety, retry,
  and restore interaction.

## P6 — Full-path evidence

Issue: [#8](https://github.com/Dylan5237/safe-delete-cli/issues/8)

- `test: add full-path replay harness` — clean-checkout invocation across the
  frozen P2–P5 boundaries.
- `docs: publish acceptance-to-proof matrix` — command, cwd, SHA, result, and
  artifact location for every frozen acceptance test.
- `evidence: capture full-path verification` — proof-only branch/PR labeled
  `pr:evidence`; it must contain no feature/fix/product implementation diff.

## Landing rules

- Each commit maps to one Phase contract slice and one issue/PR.
- Every Phase gets a dated `CONTRACT FREEZE` and disposer `FREEZE ACK` before
  any `feat/` or `fix/` branch.
- Implementation PRs and evidence PRs stay separate.
- Merge is not Phase PASS. Codex proposes `EVIDENCE READY`; only `@Dylan5237`
  records `PHASE ACCEPT` and permits `status:done`.
- All topic branches are created from the current `origin/main` tip, use the
  `feat|fix|docs|evidence/{issue}-{slug}` convention, and push only to
  `origin`.
