# P9 WORKBUDDY HOST ADAPTER — CONTRACT FREEZE PROPOSAL

**Status:** `freeze:pending` — this is a **proposal only**. It contains no
`FREEZE ACK`, no `PHASE ACCEPT`, no Phase PASS, and no verification result. No
`feat/`, `fix/`, `test/`, or `evidence/` branch is authorized until the named
disposer records `FREEZE ACK` on
[Issue #27](https://github.com/Dylan5237/safe-delete-cli/issues/27). It does not
reopen, amend, or reinterpret any accepted P0–P8 contract.

**Phase Issue:** [#27](https://github.com/Dylan5237/safe-delete-cli/issues/27) ·
**Command Center:** [#1](https://github.com/Dylan5237/safe-delete-cli/issues/1)

**Baseline:** `main @ 2434d6c` (P8 usability merged via PR #26). Every "current
behavior" statement below was read from that baseline; nothing in this document
is implemented on it.

**Review artifact:** the docs PR opened from `docs/27-p9-workbuddy-freeze`.

**Disposer:** `@Dylan5237`. Per `.agent-project-ops/PRINCIPLES.md` § 1/§ 4, the
Agent that authored this proposal may not ACK it, merge it into a Phase PASS, or
carry the freeze forward on its own authority.

**Research input (committed alongside this freeze):**
[docs/project/workbuddy-integration-research-2026.md](workbuddy-integration-research-2026.md)
(2026-09-22 read-only survey). Incremental fold-ins: WorkBuddy v2.48.0 config
separation; IDE `Bash`↔`execute_command` matcher; Spike→Freeze→Implement gate.

**Subordinate documents (unchanged by this proposal):**
[docs/architecture/freeze.md](../architecture/freeze.md),
[docs/architecture/exceptions.md](../architecture/exceptions.md),
[docs/project/p4-hook-coverage.md](p4-hook-coverage.md),
[docs/project/p8-usability-freeze.md](p8-usability-freeze.md).

**Scope discipline.** P9 adds one new **WorkBuddy** host adapter selector. It
reuses the frozen `pretooluse` decision kernel and Claude-like host registration
shape. It does not change storage, ledger, identity, restore, purge, or the
existing `claude` / `cursor` / `path-shim` contracts. Public CLI spelling is
**`workbuddy` only** — no `codebuddy` selector and no advertised `codebuddy`
alias.

**Process shape (binding):** **Spike → Freeze → Implement (gated).** This
document is the Freeze proposal. Implementation is authorized only after
`FREEZE ACK` **and** a green Spike that satisfies the machine verification gates
in § 3.1 and § 5. Spike red → document-only close / no implement (see § 7.2).

---

## 1. Goal and boundaries

### 1.1 Core problem (one phase, one problem)

WorkBuddy (Tencent desktop AI workstation) can delete via Agent tools, but
safe-delete has **no** host adapter for it. Claude, Cursor, and path-shim are
covered; WorkBuddy operators get no one-shot PreToolUse wiring. Research
(2026-09-22) showed the product already exposes Claude-family PreToolUse
(deny / rewrite); the missing piece is our selector and IntegrationSpec, not
host capability.

Rejected framings for this phase: "reuse the `claude` selector against
WorkBuddy paths", "path-shim alone is enough", "ship a `codebuddy` public
name", "expand Exception #12", "add an App", "support native Windows Python".
See § 7.

### 1.2 Goals, in disposer-priority order

| # | Goal | Blocking for P9 ACCEPT |
| --- | --- | --- |
| G1 | Spike proves WorkBuddy desktop loads `hooks.PreToolUse` from the resolved WorkBuddy config root and can deny or rewrite a Bash/execute_command deletion vector to `safe-delete add` (or fail closed). | **yes** — hard gate before implement |
| G2 | New selector `workbuddy` with IntegrationSpec: config-root resolution (§ 3.1), event `PreToolUse`, matcher `Bash\|execute_command`, reuse `pretooluse` kernel. | **yes** |
| G3 | `safe-delete setup workbuddy` / `hook install workbuddy` surface + `doctor` / `hook status` honesty (no coverage claim; WSL/platform residual explicit). | **yes** |
| G4 | Fail-closed rules + residual bypass inventory (Claude family + Windows Git Bash hook constraint + WSL CLI requirement). | **yes** |
| G5 | Evidence on a real or documented WorkBuddy settings layout after implement. | **yes** (post-implement) |
| G6 | Optional path-shim as defense-in-depth only (already exists; P9 may document recommending it alongside WorkBuddy, not as substitute). | **no** |

### 1.3 Non-goals (binding)

- No public CLI selector or alias named `codebuddy`. Engine/CLI sibling paths
  that happen to use `.codebuddy` or `CODEBUDDY_CONFIG_DIR` may be mentioned as
  **implementation facts** in resolution notes; they are never user-facing
  product names in help text, setup spellings, or status selectors.
- No native Windows Python runtime, no `msvcrt`/Win32 lock port, no claim that
  Win32 `Remove-Item` is covered.
- No expansion or reinterpretation of Exception #12.
- No GUI / App / tray / dashboard.
- No reopening of accepted P0–P8 contracts; no change to `claude` / `cursor` /
  `path-shim` semantics.
- No claiming coverage beyond the registered WorkBuddy PreToolUse boundary plus
  optional path-shim.
- No replacing Claude or Cursor adapters.
- No hardcoding a single config root without the § 3.1 machine verification
  gate.
- Path-shim alone is **not** the primary delivery for WorkBuddy.

---

## 2. Current baseline (what P9 is changing), for reviewers

Read from `main @ 2434d6c`:

| Surface | Current behavior | P9 delta |
| --- | --- | --- |
| Hook selectors | `claude`, `cursor`, `path-shim` (+ `rm-shim` alias); setup spellings `claude` \| `cursor` \| `path` | Add **`workbuddy`** only |
| `IntegrationSpec` | Claude: `~/.claude/settings.json` or project `.claude/…`, `PreToolUse`, matcher `Bash`; Cursor: project `.cursor/hooks.json`, `preToolUse` | New WorkBuddy IntegrationSpec (§ 3) |
| Decision kernel | Shared `pretooluse` adapter + protocol v1 | **Reuse unchanged** |
| `setup` | `claude` \| `cursor` \| `path` | Add `setup workbuddy` |
| `doctor` / `hook status` | Lists existing selectors; out_of_coverage inventory | Include `workbuddy` row; honest residuals (§ 4) |
| Platform | Linux / macOS / WSL; native Windows Python unsupported (`fcntl`) | Unchanged; WorkBuddy-on-Windows requires WSL-hosted CLI (§ 4.2) |

---

## 3. WorkBuddy IntegrationSpec (proposed contract)

### 3.1 Config root resolution — **verification-gated**

Desktop WorkBuddy (v2.48.0+) uses an **independent** `.workbuddy/` configuration
directory, **separated from** the coding CLI's `.codebuddy/` layout
([release notes v2.48.0](https://www.workbuddy.ai/docs/cli/release-notes/v2.48.0)).
Therefore the **default discovery preference for the `workbuddy` selector** is
the WorkBuddy product tree — **not** a hardcode of only `~/.codebuddy`.

**Proposed candidate order (user-global install, no `--config` / `--project`):**

1. If env `CODEBUDDY_CONFIG_DIR` is set **and** Spike/machine check proves the
   running WorkBuddy desktop actually honors it for hooks → use
   `$CODEBUDDY_CONFIG_DIR/settings.json`. Until proven, treat this env as an
   **engine/CLI sibling fact**, not as a frozen default for desktop WorkBuddy.
2. `~/.workbuddy/settings.json` — **preferred default for desktop WorkBuddy**
   (aligned with v2.48.0 separation and observed `~/.workbuddy/skills` layout).
3. `~/.codebuddy/settings.json` — **only if** a machine check proves the
   operator's WorkBuddy build still loads hooks from the CLI tree (legacy /
   unseparated builds). Must not be hardcoded as the sole root.

**Project-local (when `--project DIR` is passed):**

1. `<DIR>/.workbuddy/settings.json` (preferred)
2. `<DIR>/.codebuddy/settings.json` (only if proven for that host build)

**Explicit override:** `--config PATH` always wins and records that exact
boundary (same fail-closed registry semantics as Claude/Cursor).

#### Machine verification gate (hard; blocks implement)

Before any `feat/` commit may hardcode a default root, Spike evidence MUST
record, on a representative WorkBuddy install:

| Check | Required artifact |
| --- | --- |
| V1 | Which file WorkBuddy actually reads for `hooks.PreToolUse` (path + screenshot or file hash before/after install). |
| V2 | Whether `~/.workbuddy/settings.json` alone is sufficient on Dylan's (or equivalent) desktop build. |
| V3 | Whether `CODEBUDDY_CONFIG_DIR` / `~/.codebuddy/settings.json` is consulted, ignored, or only used by the separate coding CLI. |
| V4 | `tool_name` values observed on stdin for shell execution (`Bash` vs `execute_command` vs both). |

If V1–V2 fail (desktop never loads `.workbuddy` hooks), Spike is **red** → no
implement (§ 7.2). The Freeze may still ship as documentation of "unsupported
until host loads hooks".

**Freeze text rule:** implementation MUST encode the **proven** order from Spike,
preferring `.workbuddy` when V2 is green. Docs and doctor messages MUST say
"WorkBuddy config root" and show the resolved path; they MUST NOT tell operators
to "run setup codebuddy".

### 3.2 Event, matcher, and registration shape

| Field | Contract |
| --- | --- |
| Selector | `workbuddy` (exact public spelling; case-insensitive input normalized to lowercase) |
| Mode | `pretooluse` (reuse frozen kernel; protocol v1) |
| `event_key` | `PreToolUse` (Claude-compatible; CodeBuddy/WorkBuddy hooks docs) |
| Matcher | `Bash\|execute_command` — IDE tools use `execute_command` where CLI uses `Bash` ([IDE hooks](https://www.codebuddy.ai/docs/ide/Features/hooks)). Runtime `tool_name` on stdin is authority; matcher is the registration filter only. |
| Host registration | Claude-like object: `{"matcher":"Bash\|execute_command","hooks":[{"type":"command","command":"<adapter_path>"}]}` appended under `hooks.PreToolUse` |
| Scope | **User-global by default** (`~/.workbuddy/settings.json` after gate); project-local via `--project` / `--config` |

Spike may narrow the matcher to a single proven `tool_name` if the host rejects
alternation — that narrowing requires an explicit line in `FREEZE ACK` or a
`FREEZE RETURN` amending this section. Default freeze assumes alternation is
accepted (as in IDE docs' bidirectional alias guidance).

### 3.3 CLI surface deltas

Additive only; no existing selector is renamed or removed.

```text
safe-delete setup workbuddy [--init] [--config PATH] [--project DIR] [--cli PATH] [--human|--json]
safe-delete hook install workbuddy [--config PATH] [--project DIR] [--cli PATH]
safe-delete hook status workbuddy
safe-delete hook disable workbuddy
safe-delete hook uninstall workbuddy
```

- `setup workbuddy` follows the frozen P8 sequencer: platform preflight →
  `hook install workbuddy` → read-only `doctor` → next steps. It NEVER claims
  the workspace is "protected".
- Help / error strings that list selectors become:
  `claude, cursor, path-shim` (and setup: `claude | cursor | path | workbuddy`).
- **No** `codebuddy` token in argparse choices, alias maps, or user-facing
  messages.

### 3.4 Decision / fail-closed behavior (inherited + WorkBuddy-specific)

Inherited from frozen PreToolUse adapter (P4 / `freeze.md` hook section):

- Malformed / missing required host context → deny / fail closed; no raw
  fallback.
- Unavailable CLI, unregistered/disabled integration, unwritable root/ledger,
  nonzero `safe-delete add` → deny or failed shim exit; original vector does
  **not** execute.
- Unsupported / ambiguous argv forms → deny (same recognition rules as Claude
  Bash routing).
- Pass-through for non-deletion probes (`--help`, `--version`, no-operand)
  unchanged in spirit; apply when `tool_name` is Bash/execute_command and argv
  matches frozen recognition.

WorkBuddy-specific:

- If settings JSON is present but `hooks` is the wrong type → install/status
  fail closed with `storage_failure` / clear message (mirror Claude).
- If Spike shows hooks require Git Bash on Windows hosts → the registered
  `command` MUST be a POSIX-friendly invocation that reaches the WSL-hosted
  `safe-delete` CLI (exact argv string is an implement detail; Freeze requires
  it be documented in install result / doctor). Native Win32 Python remains
  unsupported.
- Settings changes are **not** assumed hot-loaded; next-steps text MUST tell
  the operator to open the host `/hooks` panel or start a new session
  (per vendor docs).

---

## 4. Honesty, residuals, and bypasses

### 4.1 Residual bypasses (same family as Claude + WorkBuddy notes)

The ten frozen `OUT_OF_COVERAGE_BYPASSES` entries remain verbatim and apply.
Additionally, P9 documentation and `doctor` / skill touchpoints MUST state:

| Residual | Classification |
| --- | --- |
| Windows Git Bash–only hook runner (vendor constraint) | Supported host constraint; not a safe-delete bug. Hook `command` must be Git-Bash-safe. |
| safe-delete CLI requires Linux/macOS/WSL (`fcntl`) | Operator must run CLI inside WSL (or native POSIX). Native Windows Python out of coverage. |
| Absolute `/bin/rm`, language APIs, `find -delete`, `git clean`, PATH reorder, other agents | Same P4 inventory — out of coverage. |
| Non-shell deletion tools (Write/Edit wipe, dedicated delete tools, MCP) unless matcher extended later | Out of coverage for P9. |
| Hooks marked Beta by vendor; behavior may evolve | Version-lock guidance in doctor warning when detectable; not a coverage claim. |

### 4.2 Platform honesty

- Supported runtime for the CLI: Linux / macOS / WSL with POSIX `python3`.
- WorkBuddy **desktop on native Windows** is a valid *host*, but the hook must
  invoke the CLI via WSL (or equivalent POSIX environment). P9 does **not**
  deliver native Windows Python.
- `doctor` and `setup workbuddy` MUST print the WSL requirement when platform
  preflight would fail on native Windows, and MUST NOT print a green coverage
  claim.

### 4.3 Exception #12

Unchanged. No P9 text may imply #12 is fixed. `exceptions.md` is not edited.

### 4.4 Path-shim role

Optional depth only. Operators may also `setup path` inside WSL. Path-shim does
**not** substitute for WorkBuddy PreToolUse on the desktop agent tool path.

---

## 5. Acceptance gates (phase-level, replayable)

All gates run from a clean checkout of the implementation SHA (after ACK + green
Spike). Gate ids are stable.

| Gate | Exact command / proof | Expected |
| --- | --- | --- |
| **P9-S0 — Spike config root** | On target WorkBuddy: write a distinctive PreToolUse probe into candidate paths in order; trigger one shell deletion tool call; record which path fired. Commands are operator/host-specific; artifact MUST name the winning path. | Winning path is `~/.workbuddy/settings.json` **or** an explicitly documented proven alternate; evidence attached to Issue #27. |
| **P9-S1 — Spike deny/rewrite** | With probe hook installed at the winning path, issue a deletion-shaped `Bash` or `execute_command` vector; capture host decision + whether target survived / was rewritten to trash. | Deny or rewrite→`safe-delete add` succeeds; raw delete does not land. |
| **P9-S2 — Spike tool_name** | Log stdin `tool_name` for CLI and IDE-shaped calls if both exist on the machine. | Documented `Bash` and/or `execute_command`; matcher choice confirmed. |
| **P9-1 — install workbuddy** | `safe-delete setup workbuddy --init --json` in disposable `HOME` with fixture settings layout matching Spike winner. | Exit `0`; envelope `ok` true; `results[0].install.selector == "workbuddy"`; `boundary.config_path` equals the gated root; `doctor.read_only == true`; no coverage claim string. |
| **P9-2 — status/doctor honesty** | `safe-delete hook status workbuddy --json` and `safe-delete doctor --json`. | `workbuddy` row present; `enforced` only means this boundary; `out_of_coverage` still lists the ten verbatim bypasses; WSL/Git-Bash residual visible in human mode. |
| **P9-3 — fail-closed install** | Corrupt `hooks` type / boundary mismatch (if registry already records another path) / missing CLI. | Nonzero exit; `storage_failure` or frozen usage codes; no partial silent success. |
| **P9-4 — route once** | Unit/integration: installed WorkBuddy-shaped PreToolUse payload with `tool_name` in `{Bash, execute_command}` and frozen `rm`/`unlink`/`rmdir` argv forms. | Exactly one `safe-delete add` child; no raw fallback; one ledger event per success. Mirror P4 pretooluse tests. |
| **P9-5 — no selector drift** | `safe-delete setup codebuddy` / `hook install codebuddy` (and any alias). | Usage/`unsupported` failure; **no** install. Grep of user-facing strings shows no advertised `codebuddy` selector. |
| **P9-6 — regression** | `python3 -m unittest discover -s tests -v` | Full suite PASS; Claude/Cursor/path-shim behavior unchanged. |
| **P9-7 — evidence** | Documented install on real or fixture WorkBuddy layout + one live or recorded vector → ledger. | Artifact under `evidence/` (post-implement); notes WSL requirement. |

Spike gates P9-S0…S2 are **pre-implement**. If any is red, stop (§ 7.2).

---

## 6. Risks and mitigations

| Risk | Severity | Mitigation frozen here |
| --- | --- | --- |
| Hardcoding `~/.codebuddy` against a desktop that only reads `.workbuddy` | High | § 3.1 preference + V1–V3 machine gate; default prefer `.workbuddy` |
| Official hooks docs still emphasize `.codebuddy` paths | Medium | Treat as engine/CLI sibling; product selector remains `workbuddy`; Spike decides |
| `Bash` vs `execute_command` mismatch | Medium | Matcher `Bash\|execute_command`; runtime `tool_name` authority; P9-S2 |
| Hooks Beta / schema drift | Medium | doctor warning; lock observed host version in evidence |
| Native Windows without WSL | Blocking for CLI | Fail closed at preflight; document WSL; no native Python port |
| Path-shim mistaken for primary fix | Medium | § 4.4; NON-GOALS |
| Effort overrun if Spike red late | Medium | Process shape forces Spike before implement; red → doc-only |

**Effort (from research, indicative):** Spike 0.5–1 pd; Freeze (this doc) 0.5;
implement + tests 1–2; evidence 0.5–1. **Spike green ≈ 3–5 person-days total.**
Spike red → ≤0.5 pd doc closeout.

---

## 7. Out of scope / deferred

### 7.1 Explicitly out of scope (binding NON-GOALS)

- Public `codebuddy` selector or alias
- Native Windows Python / Win32 locks
- Exception #12 expansion
- GUI / App
- Replacing or weakening Claude/Cursor/path-shim
- Claiming coverage beyond WorkBuddy PreToolUse (+ optional path-shim)
- Automatic cron/scheduler changes
- Hardcoding config root without § 3.1 verification

### 7.2 Spike-red exit

If P9-S0…S2 cannot show PreToolUse loading from a WorkBuddy-readable settings
path with deny/rewrite on a deletion vector, P9 implementation is **not**
authorized. Disposer options: close as document-only (this freeze + research
stand as "host gap"), or `FREEZE RETURN` with a narrowed experiment. Do not
ship a dead selector.

### 7.3 Proposed commit slices (proposal only — not authorized)

None authorized before `FREEZE ACK` **and** green Spike.

1. `docs:` this freeze + research (this PR) — no product code.
2. After ACK + Spike green: `feat: add workbuddy IntegrationSpec and hook install`
3. `feat: add setup workbuddy surface and doctor/status honesty`
4. `test: cover p9 workbuddy contract` (P9-1…P9-6)
5. `evidence: p9 workbuddy host replay` (P9-7)

No `safe_delete/**` changes in slice 1.

---

## 8. Explicit ask

This is a proposal, not a self-freeze, and not a Phase Accept.

Disposer `@Dylan5237`, please review [Issue #27](https://github.com/Dylan5237/safe-delete-cli/issues/27)
and this document and reply with exactly one of:

- **`FREEZE ACK`** — the P9 contract above is ready; Spike gates P9-S0…S2 remain
  mandatory before any `feat/` branch; implement slices 2–5 authorized only after
  Spike green against baseline `2434d6c` (or later `main` noted in ACK).
- **`FREEZE RETURN`** — followed by required deltas (config order, matcher,
  naming, gates).

Until that comment exists, no P9 implementation branch may be opened, and no
part of this document may be cited as an approved contract.

---

## Sources (freeze-relevant)

1. https://www.workbuddy.ai/docs/cli/release-notes/v2.48.0 — `.workbuddy/` separated from `.codebuddy/`
2. https://www.workbuddy.ai/docs/cli/hooks — PreToolUse, settings shape, Git Bash on Windows
3. https://www.codebuddy.ai/docs/ide/Features/hooks — Claude-compatible hooks; `Bash`↔`execute_command`
4. https://www.workbuddy.ai/docs/cli/installation — config dir / `CODEBUDDY_CONFIG_DIR` (engine/CLI sibling fact)
5. In-repo: `safe_delete/hook.py` IntegrationSpec; `docs/project/p4-hook-coverage.md`; `docs/project/p8-usability-freeze.md`
6. Research: [workbuddy-integration-research-2026.md](workbuddy-integration-research-2026.md)
