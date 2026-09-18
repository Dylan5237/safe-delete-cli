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

- `feat: add CLI surface + ledger bootstrap` (P2-S0) — command dispatch,
  `init`, `list` (including orphan reconciliation), `show`, `version`, shared
  `--root`/`--json` output envelope, reserved exit categories, and the frozen
  machine-readable error vocabulary.
- `feat: add unified trash move primitive` — one focused move operation for the
  frozen file/directory and failure semantics.
- `feat: add minimum ledger writer` — append the frozen minimum record for each
  successful operation and replay the lifecycle/audit contract.
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

## P7 — CLI-first slice: agent docs, install honesty, freeze proposals

Status: **proposal skeleton only.** Nothing below is approved. The `feat:` items
are placeholders that require a disposer `FREEZE ACK` on the P7 Freeze Issue
before any implementation branch exists. Baseline: `main @ bf9d21e`.

Review input: `docs/project/p7-adversarial-review.md` (verdict
`REQUEST_CHANGES`; must-fix items 1–10).

### Docs (landed or in PR #21 — docs-only, no `safe_delete/` change)

- `docs: add P7 adversarial review of CLI-first slice proposal` — pre-freeze
  review of agent docs + install UX + doctor + purge hardening. Landed as
  `8d2f227` on `docs/1-p7-adversarial-review`.
- `docs: P7 agent usage, install notes, README honesty (pre-freeze)` —
  `docs/project/p7-agent-usage.md` (verified `--json` examples, purge three-step
  discipline, verbatim P4 bypass inventory, WSL path-form table, canonical
  storage root), `docs/project/p7-install-notes.md` (counterexamples A/B/C as
  known limits with workarounds), and README honesty fixes (root precedence,
  platform limits, cron environment). Same PR #21.

### Freeze-gated product work — 待 FREEZE ACK

Each item below is a placeholder for a separate P7 Freeze Issue decision and a
separate `feat/` or `fix/` branch. None is authorized by this document.

- `feat: add doctor read-only preflight` — **待 FREEZE ACK**. Aggregated
  read-only checks (`hook status` boundaries, storage root writable, platform
  preflight, payload source exists, `cli_path` not world-writable) plus the
  forbidden-claims list from review § 6.
- `fix: allow hook package paths colocated with the storage root` — **待 FREEZE
  ACK**. Resolves counterexample A (`path_forbidden` on default paths) in
  `_reject_storage_namespace`, or moves the package root; includes a
  default-environment install test.
- `fix: fail closed on multi-project hook config mismatch` — **待 FREEZE ACK**.
  Resolves counterexample B by keying the registry as `(selector, config_path)`
  or rejecting a mismatched install target.
- `feat: add unsupported-platform preflight` — **待 FREEZE ACK**. One-line
  `unsupported platform: requires Linux/macOS/WSL (fcntl)` instead of an import
  traceback.
- `feat: reject or warn on world-writable --cli` — **待 FREEZE ACK**.
- `feat: purge --before now sugar` — **待 FREEZE ACK**. Tradeoff only; `--before`
  with a future timestamp remains legal wipe-all until decided.
- `test: capture real Cursor host PreToolUse replay` — **待 FREEZE ACK**.
  Evidence task for the Cursor schema gap (protocol verified, real host not
  replayed).
- `docs: register Exception #12 hardening as a later phase` — **待 FREEZE ACK**.
  Registration only; no threat-model change in P7.

Explicitly out of scope for P7 (see review § 9): GUI/tray/web/dashboard,
Windows-native runtime, scheduler auto-install, ledger compaction, and any
reopening of accepted P0–P6 contracts.

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
