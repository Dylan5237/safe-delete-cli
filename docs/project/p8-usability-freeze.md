# P8 UI/UX USABILITY — CONTRACT FREEZE PROPOSAL

**Status:** `freeze:pending` — this is a **proposal only**. It contains no
`FREEZE ACK`, no `PHASE ACCEPT`, no Phase PASS, and no verification result. No
`feat/`, `fix/`, `test/`, or `evidence/` branch is authorized until the named
disposer records `FREEZE ACK` on
[Issue #24](https://github.com/Dylan5237/safe-delete-cli/issues/24). It does not
reopen, amend, or reinterpret any accepted P0–P7 contract.

**Phase Issue:** [#24](https://github.com/Dylan5237/safe-delete-cli/issues/24) ·
**Command Center:** [#1](https://github.com/Dylan5237/safe-delete-cli/issues/1)

**Baseline:** `main @ 37f270e` (P7 merged; `fix/22-install-doctor` landed as
PR #23). Every "current behavior" statement below was read from that baseline;
nothing in this document is implemented on it.

**Review artifact:** the docs PR opened from `docs/24-p8-usability-freeze`.

**Disposer:** `@Dylan5237`. Per `.agent-project-ops/PRINCIPLES.md` § 1/§ 4, the
Agent that authored this proposal may not ACK it, merge it into a Phase PASS, or
carry the freeze forward on its own authority.

**Subordinate documents (unchanged by this proposal):**
[docs/architecture/freeze.md](../architecture/freeze.md) (P1 architecture
contract, P3/P4/P5/P6 refinements), [docs/architecture/exceptions.md](../architecture/exceptions.md)
(Exception #12), [docs/project/p7-agent-usage.md](p7-agent-usage.md),
[docs/project/p7-install-notes.md](p7-install-notes.md),
[docs/project/p7-adversarial-review.md](p7-adversarial-review.md),
[docs/project/p4-hook-coverage.md](p4-hook-coverage.md).

**Scope discipline.** P8 changes *presentation and entry points*. It does not
change storage, ledger, identity, restore, purge eligibility, hook recognition,
or error semantics. Every P8 addition is a thin layer over behavior that is
already frozen and implemented; where a P8 command appears to duplicate a P7
command, this freeze states which one owns the semantics.

---

## 1. Goal and boundaries

### 1.1 Core problem (one phase, one problem)

After P0–P7 the protocol is correct but the **operator interface is not
self-teaching**: install is multi-step, the human default output of `list` and
`doctor` is a raw JSON dump, the only way to reclaim space is a two-flag
incantation that agents are tempted to memorize, and agent onboarding still
depends on tribal knowledge from `docs/project/p7-agent-usage.md`. P8 fixes the
*usability* of the existing protocol; it does not extend the protocol.

Rejected as a framing for this phase: "add an App", "make install automatic",
"make doctor green mean protected". See § 7.

### 1.2 Goals, in disposer-priority order

| # | Goal | Blocking for P8 ACCEPT |
| --- | --- | --- |
| G1 | `safe-delete setup <cursor\|claude\|path>` — one-shot hook install + read-only `doctor`, with human-readable, actionable failures for multi-project Cursor, PATH ordering, and the WSL/native-Windows split. | **yes** |
| G2 | Shorter daily UX — a safe `empty` that wraps purge preview → explicit confirmation, plus human-default `list`/`restore`. Never teaches `--execute --yes` as a habit. | **yes** |
| G3 | Human-default output for `list`, `doctor`, and related commands; `--json` remains the agent/machine interface and is unchanged. | **yes** |
| G4 | In-repo agent skill packaging (Cursor/Claude loadable) built from `docs/project/p7-agent-usage.md`, containing real flags only. | **yes** |
| G5 | Optional stretch: `safe-delete.cmd` Windows→WSL bridge. | **no** — deferred by default (§ 7.2) |

### 1.3 Non-goals (binding)

- No GUI, desktop App, tray, dashboard, web viewer, or "App-level
  observability". `list --json` + `doctor --json` remain the observability
  ceiling. (`p7-adversarial-review.md` § 9 literally named `list --json` +
  `hook status --json` before `doctor` existed; P7 added `doctor --json` as
  the aggregate read-only surface, and that is the ceiling P8 preserves.)
- No change to the Exception #12 threat model, and no wording anywhere in P8
  that reads as "#12 fixed". See § 6.3 and § 4.4.
- No native Windows Python runtime, no `msvcrt`/Win32 lock port, no attempt to
  make `/mnt/*` or `\\wsl$\...` supported. The supported shapes remain
  Linux / macOS / WSL with a POSIX `python3`.
- No automatic cron/systemd installation. Scheduler setup remains
  operator-owned (`freeze.md` § Purge policy).
- No reopening of accepted P0–P7 contracts, and no edit to the *semantics* of
  `docs/architecture/freeze.md` or `docs/architecture/exceptions.md`.
- No `doctor` that repairs, configures, writes, or "fixes" anything. P8 keeps
  `doctor` read-only.
- No vendored/self-contained hook payload (P7 counterexample C stays a warned
  limit), and no change to `safe_delete/hook.py` install/registry semantics
  beyond what § 3.3 requires for messaging.
- No new ledger fields, no new lifecycle events, no `schema_version` bump, no
  ledger rewrite. P8 output is presentation plus entry points.

---

## 2. Current baseline (what P8 is changing), for reviewers

Read from `main @ 37f270e`:

| Surface | Current behavior | P8 delta |
| --- | --- | --- |
| `list` human mode | `_print_human` prints one `json.dumps(result)` line per entry (`safe_delete/cli.py:149-154`). Effectively JSON. | Human table default on a TTY (§ 3.1). |
| `doctor` human mode | Same generic JSON dump; no readable sections. | Sectioned human report (§ 3.1). |
| Daily removal | `purge` preview, then `purge --execute --yes`. Correct but memorizable as one incantation. | `empty` preview → `--confirm TOKEN` (§ 3.2). |
| Install | `hook install <selector>` + manual `hook status`/`doctor`; multi-project Cursor fails closed with a good message but no guided next step. | `setup` sequences install + doctor + next steps (§ 3.3). |
| Agent onboarding | `docs/project/p7-agent-usage.md` only; no loadable skill. | `skills/safe-delete/SKILL.md` (§ 3.4). |

Global surface on the baseline: `--root DIR`, `--json`; commands
`{init, add, list, show, restore, purge, hook, doctor, version}`; no top-level
`status`. P8 **does not** add a top-level `status`.

---

## 3. CLI surface deltas

All new flags and commands are additive. No existing flag is renamed, removed,
or given a new default. Where this section and
[docs/architecture/freeze.md](../architecture/freeze.md) appear to overlap, the
frozen architecture governs the *semantics* and this section governs only the
new *spelling*.

### 3.1 Output mode: `--human`, `--json`, and the non-TTY invariant

`--json` already exists and is unchanged byte-for-byte. P8 adds one global flag:

| Flag | Contract |
| --- | --- |
| `--human` | Force human-readable rendering. Presentation only; never changes results, ordering, filters, exit codes, or mutations. |
| `--json` | Force the frozen JSON envelope. Unchanged from P2. |
| *(neither)* | **Auto**: human rendering when `sys.stdout.isatty()` is true; the JSON envelope when it is false. |

**Frozen invariant (non-negotiable):** when stdout is **not** a TTY and neither
flag is passed, the output MUST be the JSON envelope exactly as produced on
`37f270e`. A pipe, a redirect, a cron job, or a captured subprocess must never
start receiving human text because of P8. `--json` and `--human` together are
`usage_error` (exit category `2`).

**Frozen invariant:** human rendering is **not** a stable parsing interface. It
may change wording, ordering, color, and layout in any later commit. The only
stable elements in human output are: the error `code` values, the exit category,
and — for the commands named below — the presence of `entry_id` and
`original_path`. Agents, hooks, cron, and tests MUST use `--json`.

Human rendering, per command:

| Command | Required human content |
| --- | --- |
| `list` | A header with the resolved root and the count; one line per entry showing at least `entry_id`, `state`, `kind`, age, and `original_path`; a footer naming the active/orphan counts. Zero entries prints an explicit "no entries" line, not nothing. |
| `list --orphans` / audit errors | Every audit error is visible with its `code`, and the command still exits nonzero exactly as today. |
| `show` | Labelled fields for the requested entry plus its ordered lifecycle events. |
| `doctor` | Sections for platform preflight, storage, boundaries, artifacts, and CLI paths; a `problems` list; the read-only statement; the verbatim Exception #12 residual line (§ 6.3); and the honest footer from § 4.5. |
| `restore` | `entry_id`, resulting `state`, `original_path`, and effective `restore_path`; the verbatim Exception #12 residual line. |
| `purge` preview | `mode`, the resolved policy source and cutoff, the candidate count and list, the mandatory wipe-all warning when applicable, and an explicit "nothing was removed" statement. |
| `hook status` | One line per selector with `enforced`, `installed`, and the selector's own `warning`. For `claude`/`cursor`, show the boundary `config_path`; for `path-shim`, show `shim_dir` / `prepend_path` (path-shim's boundary has no `config_path`). |
| `hook install` | The selector, the boundary `config_path`, `changed`, and every `install_warnings` entry. |

Errors and warnings remain on **stderr**; exit categories remain the frozen
`0/2/3/4/5`. The requirement that a human operator can name an entry and its
path within seconds (review § 12) is what the `list` row encodes.

`list` also gains one additive, opt-in flag:

| Flag | Contract |
| --- | --- |
| `list --limit N` | `N` is a positive base-10 integer. Applied **after** all existing filters. When `--limit` is present the result is **re-sorted** (not merely truncated): newest lifecycle-event `timestamp` first (the latest event on the entry, not only the trash-anchor creation time), `entry_id` ascending as the tiebreak, then the first `N` rows. Omitted `--limit` leaves both the result set **and** the baseline ordering unchanged (`entry_id` ascending, as on `37f270e`). `--limit` applies to `--all` and `--orphans` as well. An invalid `N` is `usage_error`. |

### 3.2 `safe-delete empty` — safe reclaim wrapper

`empty` is a thin, explicitly-confirmed wrapper over the **frozen** purge
engine. It MUST reuse the retention evaluator, the ledger lock, the audit
preflight, the eligibility rules, and the `purge_intent` / `purge_complete` /
`purge_failed` events defined in `freeze.md` § Purge policy and § Lifecycle
state machine. It MUST NOT implement a parallel eligibility path, a second
event type, or a shortcut that skips the intent record.

```text
safe-delete empty [--older-than DURATION | --before RFC3339] [--human|--json]
safe-delete empty --confirm TOKEN [--older-than DURATION | --before RFC3339] [--human|--json]
```

| Form | Contract |
| --- | --- |
| `empty` (no `--confirm`) | **Preview only.** Never removes anything, never appends a ledger event, never changes the ledger or payload bytes. Exit `0` on a clean read. It reports `mode: "preview"`, the resolved policy, `candidates`, `decisions`, the wipe-all `warning` **when applicable** (§ below), and a `confirm_token`. |
| `empty --confirm TOKEN` | Executes removal of exactly the candidate set that `TOKEN` commits to. Reports `mode: "execute"` and the same `outcomes`/`partial_failure` semantics as `purge --execute --yes`. Confirm MUST be invoked with the **same threshold flags** (or same absence of flags) as the preview that minted `TOKEN`; otherwise the recomputed candidate set diverges and the token mismatches. |

**Eligibility default.** `empty` means *remove everything currently eligible*.
With no threshold flag the cutoff is the invocation's own UTC clock — the
documented `--before now` semantics — so every `active` entry is eligible. This
is **wipe-all by design**. Unlike `purge`, which preserves the
`--older-than`/`--before` → `SAFE_DELETE_RETENTION_DAYS` → 30d precedence
(§ 4.1), **`empty` deliberately does not apply** `SAFE_DELETE_RETENTION_DAYS` or
the 30-day default: with no threshold flag, `empty`'s policy source is always
the invocation clock (`before_now`). Env/default retention therefore never
narrows an `empty` run.

Because `empty` is wipe-all by default, `safe-delete purge --execute --yes`
remains the command for a retention-policy-scoped removal, and P8 documentation
and skill text MUST say so. `empty` accepts `--older-than` / `--before` so a
user can narrow it, but narrowing is an explicit act, not the default.

**When the wipe-all `warning` is emitted.** `empty` reuses the same rule as
`purge` (`purge.py`: emit only when `policy.cutoff >= policy.as_of`):

- **Emitted** for the no-flag default (`before_now`, cutoff == as_of), for
  `--before now`, and for any `--before` whose RFC3339 cutoff is ≥ the
  invocation clock (future or equal).
- **Not emitted** when the cutoff is strictly in the past — including a past
  `--before RFC3339` and a typical `--older-than Nd` / `--older-than Nh`
  threshold. Under those invocations the warning text would be false (not every
  active entry is eligible), so the field MUST be absent.

When emitted, the string is identical to purge's:

> `cutoff is not in the past: every active entry is eligible (wipe-all semantics); read candidates before extending this invocation with --execute --yes`

(For `empty`, read that as "before extending this invocation with `--confirm
TOKEN`"; the verbatim purge string is kept so agents and tests share one
sentinel.)

**The confirmation token (D1 — option a).** The preview emits `confirm_token`:
the first 16 lowercase hex characters of `SHA-256` over the canonical UTF-8
string

```text
safe-delete/empty/v1\n<root realpath>\n<sorted candidate entry_ids joined by \n>
```

**Why the cutoff is omitted from the recipe.** The default (`before_now`) and
`--older-than` cutoffs are clock-derived: a confirm invocation milliseconds
later resolves a different RFC3339 cutoff than the preview. Binding that cutoff
into the token would make the advertised default / `--older-than` flows fail
closed 100% of the time, leaving only a fixed `--before RFC3339` workable —
exactly the footgun G2 exists to break. Truncating cutoff granularity would
make confirmation flaky rather than correct. So P8 freezes **option (a)**: drop
the cutoff from the token. (Rejected alternative **(b)** — preview echoes its
resolved cutoff and confirm requires `--before <that exact RFC3339>`, rejecting
clock-derived thresholds — keeps the cutoff bound but adds moving parts and
still forces operators off the default / `--older-than` paths.)

`empty --confirm TOKEN` recomputes the token from the current root and the
candidate set produced under the confirm invocation's threshold flags, then
compares. On mismatch the command fails closed with `usage_error`, exit category
`2`, **no** `purge_intent`, and nothing removed. The candidate set already binds
eligibility: an entry added, restored, purged, or aged across an `--older-than`
boundary between preview and confirm changes the recomputed set and still fails
closed. A stale or hand-edited token can never widen the blast radius. Default
and `--older-than` paths therefore work the same as a pinned `--before`: only
the candidate membership matters.

The token is honestly a **staleness check, not a secret**: like the ledger, it
is readable and forgeable by a same-UID process. It is not an authentication
boundary and must not be described as one. It exists because it is strictly
harder to misuse than a memorized `--execute --yes`: there is nothing to
memorize, and the confirmation is meaningless without a preview of the current
state.

**Flags `empty` MUST reject.** `--execute`, `--yes`, and `--dry-run` are not
`empty` flags. Passing any of them is a usage error (exit `2`), not a silent
acceptance. This is deliberate: P8 must not create a second, weaker confirmation
idiom that competes with purge's frozen one. `--confirm` requires a value; a
bare `--confirm` is a usage error.

**Audit and failure behavior is inherited unchanged.** A ledger audit error
(malformed line, duplicate `event_id`, unsupported schema version, impossible
transition, orphan payload, missing payload) fails the whole `empty` closed
before any `purge_intent`, exactly as for `purge`. A per-entry removal failure
appends `purge_failed` with `state: "active"` and `purge_remove_failed`, keeps
the payload, continues other candidates, and returns `partial_failure` / exit
category `5`. Crash recovery of a `purge_pending` entry inherits the frozen
behavior, including that recovery is deliberately not capped by the current
cutoff.

**No new error codes.** `empty` reports the existing frozen vocabulary
(`usage_error`, `partial_failure`, `purge_remove_failed`, `storage_failure`,
`orphan_payload`, `payload_missing`, …). P8 adds no codes and renames none.

### 3.3 `safe-delete setup` — one-shot install + read-only report

```text
safe-delete setup                       # read-only: report selectors + state, mutate nothing
safe-delete setup <claude|cursor|path>  # install the named boundary, then run doctor
```

`setup path` is a **setup-only** spelling of the existing `path-shim` selector;
`path-shim` remains accepted by both `setup` and `hook install`, and the
pre-existing `rm-shim` alias keeps working on `hook install`. `hook install`
spellings are unchanged — P8 does not add `path` as a `hook install` selector.
No further selector spelling is introduced beyond that setup-only alias.

**Sequence, in order:**

1. Platform preflight (the P7 `fcntl` / `O_NOFOLLOW` / `O_DIRECTORY` check). On
   failure, print the one-line `unsupported platform: requires Linux/macOS/WSL
   (fcntl)` message to stderr, exit `2`, and **install nothing**.
2. `hook install <selector>` with the **unchanged** P7 semantics, including its
   flags: `--host`, `--config PATH`, `--project DIR`, `--cli PATH`, and the
   global `--root DIR`.
3. `doctor` (read-only), aggregated.
4. A human summary: what was installed, the boundary `config_path`, every
   `install_warnings` entry, every `doctor` problem, and explicit next steps.

**Opt-in `--init`.** `setup --init` runs the frozen `init` (idempotent) before
step 2. Without `--init`, `setup` **never** creates or initializes a storage
root; if the root is unusable it reports the problem with the exact command to
run (`safe-delete init`). This is the one place where a "one-shot" command
refuses to do more: `init` is a deliberate, auditable act and is never implicit.

**Failure honesty.** If step 2 fails, `setup` exits with the install's exit
category and propagates the install's error `code` unchanged, and it MUST NOT
print a success summary, a green mark, or any wording implying coverage. The
multi-project Cursor case keeps its P7 fail-closed behavior and message; `setup`
only adds the actionable next step:

```text
safe-delete: storage_failure: hook install resolved a different host configuration
than the recorded integration boundary; pass --project or --config for the intended
boundary, or uninstall the recorded integration first
  recorded config: <projA>/.cursor/hooks.json
  resolved config: <projB>/.cursor/hooks.json
  next: safe-delete hook uninstall cursor   # from the recorded project
        safe-delete setup cursor             # from the project you meant to protect
```

For `path`, `setup` prints the exact activation line and re-check command from
the install result's `path_activation` field (the human sentence that tells the
operator to prepend the shim directory; `boundary.prepend_path` is only that
directory path), and states plainly that PATH activation is operator-owned and
that `path_precedence` reflects only the current process.

`setup --json` uses the frozen envelope: `command: "setup"`, `results` carries
one object with `selector`, `preflight`, `install` (the unmodified install
result), `doctor` (the unmodified read-only aggregate), and `next_steps`;
`errors` carries propagated errors with their original codes.

**`setup` MUST NOT** — this list is a gate for P8 ACCEPT:

- initialize a root without `--init`;
- edit shell startup files, or any file other than the host configuration
  `hook install` already owns;
- install, enable, or write a cron/systemd unit;
- retarget, unregister, or "repair" an existing registered boundary;
- treat a successful install as enforcement, or claim a project is protected;
- write anything `doctor` reports but does not itself change.

`setup` is a **sequencer and a translator**, not a second installer.

### 3.4 Agent skill packaging

P8 adds an in-repo, loadable product skill:

```text
skills/safe-delete/SKILL.md
```

- It MUST NOT be placed under `.agents/skills/` or anywhere in the pinned
  `.agent-project-ops/` snapshot (methodology rule 7: business SOP never flows
  back into the methodology).
- It MUST carry valid frontmatter (`name`, `description`) and describe real,
  currently-shipped flags only. No flag may appear in the skill that is not
  accepted by the CLI version it is packaged with.
- It MUST contain the P4 bypass inventory **verbatim** — the same ten entries,
  in the same order and wording, as `hook.py`'s `OUT_OF_COVERAGE_BYPASSES`,
  `docs/project/p4-hook-coverage.md`, and `docs/project/p7-agent-usage.md` § 5.
  Drift between these copies is a P8 defect (§ 5, gate P8-8, § 6.5).
- It MUST contain the purge discipline verbatim as its sentinel sentence:
  `Never append --execute --yes as a default or habit.` and it MUST teach the
  preview → read → confirm sequence (for `empty`) rather than any memorized
  flag pair.
- It MUST contain the verbatim Exception #12 residual line (§ 6.3) and the
  supported-platform statement (`Linux/macOS/WSL`; native Windows is an
  unsupported interpreter and outside the boundary).
- It MUST point readers at `docs/project/p7-agent-usage.md` for the full
  walkthrough rather than duplicating the whole document, so there is one
  narrative source and one canonical flag list.
- It MUST state that `doctor`'s `needs_attention: false` means "nothing
  detected", never "protected".

Packaging is documentation-only in this phase: `skills/safe-delete/SKILL.md`
plus whatever reference files it needs. P8 does not add an installer for the
skill and does not change how Claude/Cursor discover it.

---

## 4. Compatibility notes (must-preserve list)

P8 is compatible only if every item below survives the implementation
unchanged. Each is a P8 acceptance gate in § 5.

### 4.1 Purge fail-closed behavior

- `purge` previews by default; physical removal requires **both** `--execute`
  and `--yes`.
- `--execute` without `--yes` → exit category `2`, `usage_error`, message
  `--execute requires --yes confirmation; no payloads were changed`, no mutation.
- `--dry-run` with `--execute` → exit `2`, `usage_error`.
- `--older-than` / `--before` together → `usage_error`. `--older-than 0d` →
  `usage_error`. `--before` without a timezone → `usage_error`.
- A future `--before` timestamp remains legal and remains wipe-all semantics; it
  retains its warning. P8 does not add a prompt, a second confirmation, or a
  typo guard past `--yes`.
- Threshold precedence stays `--older-than`/`--before` →
  `SAFE_DELETE_RETENTION_DAYS` → 30 days, with `policy.source` reporting the
  winner.
- Recovery of a crash-left `purge_pending` entry stays uncapped by the current
  cutoff.
- `empty` must not weaken any of the above; it reuses them.

### 4.2 `doctor` remains read-only

- `doctor` never writes, creates, repairs, or initializes. P8 adds no exception.
- `doctor --json` retains `read_only: true`, the aggregated sections, and
  `needs_attention` with its existing meaning.
- The verbatim `out_of_coverage` list is carried into `doctor` unchanged, in all
  output modes.
- The verbatim `restore.residual_note` (Exception #12) remains in `doctor --json`
  and must additionally appear in `doctor` human output.

### 4.3 Hook install selectors and boundaries

- Selectors `claude`, `cursor`, `path-shim` (alias `rm-shim`) keep their exact
  meanings, and `claude` stays user-global while `cursor` stays project-local.
- Multi-project Cursor install keeps failing closed on a resolved/recorded
  boundary mismatch; `setup` adds guidance, never a silent retarget.
- `hook install --cli PATH` keeps accepting any executable path and keeps
  warning (not rejecting) on a world-writable or git-checkout-pinned source.
- `hook status`'s `enforced` bit is unchanged: it means "this one
  `(host, config_path)` boundary is proven", never "your project is covered".
- PATH-shim activation remains operator-owned; no shell startup file is edited.

### 4.4 Exception #12 residual disclosure

- `docs/architecture/exceptions.md` is not edited.
- No P8 output, flag, doc, gate, or skill line may state or imply that
  Exception #12 is fixed.
- The residual note must be literally present in human output, not only JSON:
  `doctor` human output always, and `restore` human output always; `list` and
  `show` human output whenever a displayed entry is in a restore-related state
  (`restored`, or a `show` of restore events).
- The sentinel string, matching `doctor.py` / `p7-agent-usage.md` § 3
  (product residual disclosure):
  `Exception #12 — P2-only same-UID staging publication — excluded model / residual risk; not fixed`
  (`evidence/p6/README.md` carries a related but differently-suffixed evidence
  note — `… residual risk; not a product-contract fail.` — and is not the
  product-output sentinel.)

### 4.5 Honesty invariants that P8 must not dilute

- Human output must not present `doctor` as a coverage claim, and must not
  convert a warning into an enforcement statement.
- No P8 text anywhere may teach a purge command as an unconditional default,
  present a green check as safety, or claim Windows-side coverage.
- A successful `setup` is not a coverage claim; the report says so.

### 4.6 Machine contracts unchanged

- JSON envelope keys stay `command`, `ok`, `results`, `errors`.
- Error `code` vocabulary: no renames, no removals, no repurposing. P8 is
  additive only.
- Exit categories stay `0/2/3/4/5` with the frozen mapping.
- Ledger: `schema_version` stays `1`; no new required or optional fields; no new
  `operation` or `state` values; no line is rewritten or reordered. Read-only
  commands still never write.
- Store layout, identity, `original_path` normalization, and the same-filesystem
  boundary are untouched.

---

## 5. Acceptance tests (phase-level, replayable)

All gates run from a **clean checkout of the implementation SHA**, in a
disposable `HOME` with a fresh `SAFE_DELETE_ROOT` outside the checkout. Ages are
controlled by constructing ledger timestamps in a fixture, never by waiting or by
touching the wall clock. Gate ids are stable and each maps to one named commit
slice in § 7.3.

| Gate | What it proves |
| --- | --- |
| **P8-1 — setup one-shot** | `setup claude --init --json` in a disposable `HOME` exits `0`; envelope `ok` is `true`; `results[0].install` is the unmodified install result with `installed`/`enforced`/`changed` as on `37f270e` (there is no `install.ok` key — `ok` is envelope-level only); `doctor` is present and read-only; the report contains no coverage claim. `setup cursor` succeeds from the intended project cwd. |
| **P8-2 — setup fail-closed and guidance** | With a Cursor boundary already registered for project A, `setup cursor` from project B exits `4` with `storage_failure`, prints the recorded **and** resolved config paths plus the uninstall-then-setup next step, and returns no `ok:true`. `setup` on an uninitialized root without `--init` creates nothing and prints the exact `safe-delete init` instruction. Simulated platform-preflight failure exits `2`, prints the one-line message, and installs nothing. |
| **P8-3 — empty preview is inert (two invocations)** | Fixture: one aged and one young `active` entry (ages set via ledger timestamps, not wall-clock waits). **(a) wipe-all / warning path:** `empty --json` (no threshold flags) reports `mode: "preview"`, lists **both** entries as candidates, **carries** the wipe-all `warning` (`cutoff >= as_of`), and carries a `confirm_token`. **(b) selective / no-warning path:** `empty --before 2026-09-21T00:00:00Z --json` (fixed past RFC3339; substitute any fixture-stable past cutoff that includes the aged entry and excludes the young one) reports `mode: "preview"`, lists **only** the aged candidate, **omits** the wipe-all `warning` (cutoff is in the past), and carries a `confirm_token`. Both (a) and (b) leave the ledger file hash and every payload byte identical before and after. |
| **P8-4 — empty confirm executes exactly the previewed set** | Using the selective preview from P8-3(b): `empty --confirm <token> --before 2026-09-21T00:00:00Z` (same pinned `--before` as the preview) removes the aged payload, leaves the young payload untouched, appends `purge_intent` then `purge_complete` for the aged entry, and reports `mode: "execute"`. A replayed `empty --before 2026-09-21T00:00:00Z` then reports nothing eligible. Separately, the default path must also round-trip: `empty --json` → `empty --confirm <token>` (no threshold flags on either side) removes every previewed candidate; this proves D1 option (a) — clock-derived cutoffs are not part of the token. |
| **P8-5 — empty staleness and audit fail-closed** | Prefer the default (no-flag) path so the gate does not depend on a pinned `--before`: a token minted by `empty --json` before an extra `add` is rejected by `empty --confirm <stale>` with `usage_error`, exit `2`, and no mutation. A wrong or malformed token is rejected identically. With an injected audit-corrupt ledger (malformed line / orphan payload), `empty --confirm <token>` fails closed for the whole command with **no** `purge_intent`. `empty --execute` and `empty --yes` are usage errors, exit `2`. A removal failure produces `purge_failed` + `purge_remove_failed`, returns the entry to `active`, and reports `partial_failure` / exit `5`. Optionally repeat the stale-token case under `--older-than 30d` on both preview and confirm to prove the clock-relative path also fail-closes on set drift rather than on cutoff-string drift. |
| **P8-6 — output modes** | Under a PTY, `list`, `doctor`, `show`, `restore`, and a `purge` preview print human text; `list` shows `entry_id` and `original_path`; `doctor` and `restore` contain the verbatim Exception #12 residual line. Under a pipe with neither flag, the same invocations emit the JSON envelope **byte-identical** to `--json`. `--json` on a PTY emits JSON. `--json --human` exits `2`. Audit errors still exit nonzero and are visible in human mode. |
| **P8-7 — no contract drift** | The full pre-existing suite passes unchanged. The error-code vocabulary and exit categories are unchanged (`diff` of the code list). `purge --execute` without `--yes` still exits `2` with its original message; `--older-than 0d` and a timezone-less `--before` still exit `2`. `hook status`/`doctor` still carry the ten `out_of_coverage` entries verbatim. A `hook install` + `doctor` run leaves every root file's size and mtime unchanged except files `hook install` owns. Ledger bytes are unchanged by all read-only commands. |
| **P8-8 — skill packaging** | `skills/safe-delete/SKILL.md` exists with valid frontmatter, contains no flag absent from `safe-delete <cmd> --help`, contains the ten bypass entries verbatim (asserted equal to `OUT_OF_COVERAGE_BYPASSES`), contains the purge-discipline sentinel sentence and the Exception #12 sentinel, and contains no text teaching `--execute --yes` as an unconditional default. |

A gate is only satisfied by an artifact a reviewer can replay without asking the
author: the exact command sequence, the checkout SHA, the resolved root, the
observed exit category, and the before/after filesystem or ledger state. Logs are
excerpts, not narrative. Gate sequences and artifacts are owned by the later
`test:`/`evidence:` commits (§ 6.5), never by this docs-only proposal.

---

## 6. Risks and mitigations

### 6.1 Purge footguns (highest-severity risk in this phase)

| Risk | Mitigation frozen here |
| --- | --- |
| `empty` becomes a friendlier-looking way to delete everything without reading anything. | `empty` previews unless `--confirm TOKEN` is present; there is no flag that both selects and executes; the wipe-all `warning` is present in both preview and confirm **when** `cutoff >= as_of` (same rule as `purge`). |
| The token is mistaken for a security control, or is reused across a changed candidate set. | The token is documented as a staleness check, not a secret; it binds root + sorted candidate `entry_id`s only (no clock-derived cutoff — D1 option a); it is recomputed and compared; a mismatch fails closed with `usage_error` and no `purge_intent`. |
| Documentation or the agent skill teaches `--execute --yes` as muscle memory, producing systematic over-deletion. | P8 docs and the skill MUST teach preview → read → confirm, and the skill carries the verbatim sentinel `Never append --execute --yes as a default or habit.` Gate P8-8 asserts it. |
| `empty`'s default cutoff (invocation clock) is quietly "everything", unlike `purge`'s 30-day default. | Stated explicitly in § 3.2 (env/30d do not apply to `empty`) and in both help text and the skill; the `warning` field is emitted only when `cutoff >= as_of`; P8-3(a) asserts the warning on the no-flag path and P8-3(b) asserts its absence on a past `--before`. |
| `empty` grows its own eligibility logic and forks the purge contract. | § 3.2 requires reuse of the frozen evaluator, lock, preflight, and events; P8-4 asserts the same `purge_intent`/`purge_complete` pair. |
| A future `--before` timestamp remains a legal wipe-all in `purge`. | Unchanged from P7 and explicitly documented; P8 adds no prompt. The safe spelling (`preview first`) is the documented recipe. |

### 6.2 Human output drift breaking machines

The auto-by-TTY rule changes what a human sees while leaving a pipe unchanged,
but an agent that captures a PTY, or a wrapper that trusts human text, can still
be surprised. Mitigations: the non-TTY invariant is a frozen acceptance gate
(P8-6); human output is declared unstable except for the named tokens; the
agent skill and `p7-agent-usage.md` tell agents to always pass `--json`; and the
`--json` envelope is asserted byte-identical.

### 6.3 Exception #12 disclosure in human output

Human output is exactly where a residual risk is easiest to lose. P8 freezes the
verbatim residual line into `doctor` and `restore` human output, and into
`list`/`show` human output whenever restore state is displayed. No P8 gate,
document, or summary may describe #12 as fixed, and `exceptions.md` is not
edited. This mirrors the requirement already stated in
`p7-agent-usage.md` § 3 and `p7-adversarial-review.md` § 8.

### 6.4 `setup` scope creep

`setup` is the natural place for "just also fix my PATH / my hooks.json /
my cron" to creep in. § 3.3's MUST NOT list is a gate. `setup` sequences
`hook install` and `doctor`; it does not become a configuration center, an
auto-repair tool, or a scheduler installer. A reviewer should treat any
auto-repair behavior as grounds for `FREEZE RETURN`.

### 6.5 Skill drift and copy divergence

The P4 bypass inventory now has several verbatim copies. P8 adds one more. Gate
P8-8 asserts equality against `OUT_OF_COVERAGE_BYPASSES`; the existing copies in
`p4-hook-coverage.md` and `p7-agent-usage.md` are asserted in the same test so a
future edit cannot silently soften one of them.

### 6.6 Unchanged residual risks P8 does not address

- **Counterexample C** (installed payload pinned to the git checkout) remains a
  warned limit; P8 adds no vendored payload. Moving the checkout still makes
  every hook fail closed.
- **`/mnt/*` and `\\wsl$\...`** remain unverified/denied respectively; P8
  documents them, it does not fix them.
- **Real Cursor host replay** remains a P7 evidence gap. P8 does not claim it,
  and does not close it.

---

## 7. Out of scope / deferred

### 7.1 Explicitly out of scope (binding non-goals)

GUI / desktop App / tray / dashboard / web viewer; any "App-level
observability"; the Exception #12 fix or any change to its threat model; native
Windows Python runtime and Win32 lock primitives; automatic cron/systemd
installation; native-Windows hook enforcement; ledger compaction; remote or
network trash; encryption; multi-user server behavior; a top-level `status`
command; a vendored self-contained hook payload; any reopening or reinterpretation
of accepted P0–P7 contracts.

### 7.2 Deferred by default: `safe-delete.cmd` Windows→WSL bridge (G5)

The optional Windows-side bridge is **deferred** and is **not** required for P8
ACCEPT. This proposal does not commit to it, and P8 must not be returned on the
grounds that it is missing.

If the disposer wants it in scope, that requires an explicit line in the
`FREEZE ACK` (for example: "include G5"), in which case the following contract
applies: a `safe-delete.cmd` shim that forwards `%*` into WSL via `wsl.exe -e`,
documented as **best-effort and unverified**, never as a supported path; it must
not be described as covering Windows-side deletion (`Remove-Item` and friends
stay out of coverage), it must not change the hook protocol, and it must fail
loudly when WSL or the CLI is unavailable. Absent that explicit line, G5 is
deferred and this section is informational only.

### 7.3 Proposed commit slices (proposal only — not authorized)

Each slice is one commit and one named gate; none is authorized before
`FREEZE ACK`. Ordering matters: output mode first, then the commands, then the
skill.

1. `feat: add human default output and --human flag` — `--human`/auto-TTY
   resolution, human renderers for `list`/`show`/`doctor`/`restore`/`purge`
   preview/`hook status`, the Exception #12 lines in human output, and
   `list --limit`. Gates P8-6 (with P8-7 regression).
2. `feat: add setup one-shot command` — § 3.3, including the preflight gate, the
   `--init` opt-in, the propagated-error path, and the guided multi-project
   Cursor / PATH / WSL messages. Gates P8-1, P8-2.
3. `feat: add empty preview and confirm wrapper` — § 3.2 over the frozen purge
   engine, the token, the rejected flags, and inherited audit/partial-failure
   behavior. Gates P8-3, P8-4, P8-5.
4. `docs: publish safe-delete agent skill` — `skills/safe-delete/SKILL.md` and
   any reference files, with the P8 command surface reflected. Gate P8-8.
5. `test: cover p8 usability contract` — the replayable P8-1 … P8-8 sequences
   and their artifacts, kept separate from implementation commits.

Optional, only if G5 is explicitly ACKed: `feat: add windows-to-wsl
safe-delete.cmd bridge`.

All slices follow the repository branch convention (`feat|fix|docs|evidence/{issue}-{slug}`),
target `origin` only, and are merged only through PRs. Merge is not Phase PASS;
only `@Dylan5237` records `PHASE ACCEPT`.

---

## 8. Explicit ask

This is a proposal, not a self-freeze, and not a Phase Accept.

Disposer `@Dylan5237`, please review [Issue #24](https://github.com/Dylan5237/safe-delete-cli/issues/24)
and this document and reply with exactly one of:

- **`FREEZE ACK`** — the P8 contract above is ready, and the `feat/`, `docs/`,
  and `test/` slices in § 7.3 are authorized for implementation against
  baseline `37f270e`. Add `include G5` on the same line if the optional Windows
  bridge (§ 7.2) should also be in scope.
- **`FREEZE RETURN`** — followed by the required deltas. State which of G1–G5,
  which surface in § 3, or which compatibility item in § 4 must change.

Until that comment exists, no P8 implementation branch may be opened, and no
part of this document may be cited as an approved contract.
