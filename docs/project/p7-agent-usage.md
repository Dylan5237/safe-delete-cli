# P7 agent usage guide — current behavior

Status: **docs-only proposal material, pre-freeze.** This document describes what
the CLI does **today** on `main @ bf9d21e`. It does not announce a `doctor`
subcommand, new flags, or any install fix; those are freeze-gated proposals
tracked in the P7 Freeze Issue. See `docs/project/p7-adversarial-review.md` for
the review this guide implements, and `docs/project/p7-install-notes.md` for the
install counterexamples.

Every command and output excerpt below was run against a temporary
`SAFE_DELETE_ROOT` on `bf9d21e`. Entry ids shown as
`550e8400-e29b-41d4-a716-446655440000` are placeholders, not evidence from any
real machine.

## 1. Setup

```bash
export SAFE_DELETE_ROOT="$(mktemp -d)"
./safe-delete init --json
```

```json
{"command":"init","ok":true,"results":[{"root":"/tmp/tmp.XXXXXXXXXX","ledger_path":"/tmp/tmp.XXXXXXXXXX/ledger.jsonl","lock_path":"/tmp/tmp.XXXXXXXXXX/locks/ledger.lock","trash_path":"/tmp/tmp.XXXXXXXXXX/trash","objects_path":"/tmp/tmp.XXXXXXXXXX/trash/objects"}],"errors":[]}
```

`init` is idempotent. Run it once per root before `add`/`list`/`show`/`restore`/`purge`.

## 2. Canonical storage root

The one canonical default is:

```
$SAFE_DELETE_ROOT          (if set)
  → $XDG_DATA_HOME/safe-delete
    → $HOME/.local/share/safe-delete
```

Written out in full, the default is `~/.local/share/safe-delete`
(`docs/architecture/freeze.md` § Storage layout records the same chain).
Resolution precedence, in order:

1. `--root DIR` (per-invocation)
2. `SAFE_DELETE_ROOT`
3. `$XDG_DATA_HOME/safe-delete`
4. `$HOME/.local/share/safe-delete`

The final path component is exactly `safe-delete`. A directory whose name is the
canonical name plus a suffix — for example a `-store` variant — is **not** this
product's path. Two different roots are two independent ledgers: entries `add`ed
under one root are invisible to `list` under another. When the count looks wrong,
compare the resolved `root` in `--json` output before concluding data was lost.

`--root` and `SAFE_DELETE_ROOT` are realpath-resolved, so aliases to an existing
root stay consistent. A differently-named directory is a different ledger.

## 3. Core commands (`--json`)

### add

```bash
./safe-delete add /path/to/file --json
```

```json
{"command":"add","ok":true,"results":[{"entry_id":"550e8400-e29b-41d4-a716-446655440000","path":"/path/to/file","original_path":"/path/to/file","trashed_path":"$ROOT/trash/objects/550e8400-e29b-41d4-a716-446655440000/payload","kind":"file","state":"active","project":"/current/project","session_id":null,"reason":null,"agent":null,"tool":"safe-delete-cli","extensions":null}],"errors":[]}
```

Optional metadata flags: `--reason`, `--project`, `--session-id`, `--agent`,
`--tool`, `--extensions`. `--dry-run` previews the move without changing
anything. Agents should set `--agent` and `--reason` so the ledger can attribute
the deletion later.

### list

```bash
./safe-delete list --json
./safe-delete list --all --json        # include non-active lifecycle states
./safe-delete list --orphans --json    # reconcile payloads with no ledger entry
./safe-delete list --project /p --original /p/file --json
```

```json
{"command":"list","ok":true,"results":[{"entry_id":"550e8400-e29b-41d4-a716-446655440000","state":"active","original_path":"/path/to/file","trashed_path":"$ROOT/trash/objects/550e8400-e29b-41d4-a716-446655440000/payload","kind":"file","timestamp":"2026-09-18T08:18:04.068671Z","project":"/current/project","session_id":null,"reason":null,"agent":null,"tool":"safe-delete-cli","extensions":null}],"errors":[]}
```

### show

`show` requires the entry id positionally — there is no "show everything" form.

```bash
./safe-delete show 550e8400-e29b-41d4-a716-446655440000 --json
```

Returns `state`, the `creation` record, and the full ordered `events` list for
that entry. This is the command to read before deciding to restore or purge.

### restore

```bash
./safe-delete restore 550e8400-e29b-41d4-a716-446655440000 --json
```

```json
{"command":"restore","ok":true,"results":[{"entry_id":"550e8400-e29b-41d4-a716-446655440000","state":"restored","original_path":"/path/to/file","restore_path":"/path/to/file","kind":"file"}],"errors":[]}
```

`--to DEST` restores elsewhere; `--create-parents` creates missing parents.

Two behaviors agents rely on:

- **Destination occupied is a refusal, not an overwrite.** If something already
  exists at the restore destination the command fails closed with exit **3** and
  error code `destination_exists`; the existing file is left untouched.
- Restoring an entry that is already `restored` succeeds with exit 0 and reports
  `already_restored`; it is not an error.

> **Exception #12 — P2-only same-UID staging publication — excluded model / residual risk; not fixed.**
> Restore-related evidence in this repository carries the same note. P7 does not
> change the Exception #12 threat model; hardening is a later-phase candidate
> (registered in the P7 Freeze Issue, not implemented).

## 4. purge — three-step discipline

`purge` **previews by default**. Nothing is physically removed unless both
`--execute` and `--yes` are present.

**Step 1 — preview.**

```bash
./safe-delete purge --json
```

```json
{"command":"purge","ok":true,"results":[{"mode":"dry_run","dry_run":true,"policy":{"source":"default","as_of":"2026-09-18T08:18:07.310662Z","cutoff":"2026-08-19T08:18:07.310662Z","cutoff_utc":"2026-08-19T08:18:07.310662Z","threshold_days":30,"threshold_duration":"30d","threshold_seconds":2592000},"candidates":[],"decisions":[{"entry_id":"550e8400-e29b-41d4-a716-446655440000","state":"active","decision":"excluded","reason":"too_young","age_anchor":"2026-09-18T08:18:07.129649Z"}],"outcomes":[]}],"errors":[]}
```

**Step 2 — read the policy before deciding.** The preview is only meaningful if
you read it:

- `policy.source` — where the threshold came from: `default` (30 days),
  `environment` (`SAFE_DELETE_RETENTION_DAYS`), or `older_than`/`before` (the
  per-invocation flag). A value that differs from what you expected means the
  environment differs from what you assumed — cron and an interactive shell are
  different environments.
- `policy.cutoff` — everything with an age anchor at or before this instant is
  eligible. `cutoff_utc` is the same value; read one of them, not both.
- `candidates` — exactly what a matching `--execute --yes` run would remove.
  If `candidates` is not what you expect, stop.
- `decisions[].reason` — why each entry was kept (`too_young`, etc.).
- `mode` — `dry_run` for a preview, `execute` for a real run.

**Step 3 — execute only after step 2,** and only when the candidate list is what
you intended:

```bash
./safe-delete purge --execute --yes --json
```

**Never append `--execute --yes` as a default or habit.** The confirmation flags
are a deliberate human/agent decision gate, not a login flag. Rules the CLI
enforces today:

| Invocation | Result |
| --- | --- |
| `purge --json` | exit 0, `"mode":"dry_run"` |
| `purge --execute --json` | exit 2, `usage_error`: `--execute requires --yes confirmation; no payloads were changed` |
| `purge --dry-run --execute --json` | exit 2, `usage_error`: `--dry-run and --execute are mutually exclusive` |
| `purge --older-than 0d --json` | exit 2, `usage_error`: `--older-than must be a positive integer followed by d or h` |
| `purge --before now --json` | exit 2, `usage_error`: `--before must be an RFC3339 timestamp with a timezone` |

Threshold precedence: `--older-than`/`--before` → `SAFE_DELETE_RETENTION_DAYS`
→ 30 days. `--before` requires an RFC3339 timestamp **with** a timezone; the
retention anchor is UTC, so use `Z`. `2026-09-01T00:00:00Z` is valid;
`2026-09-01` and `now` are not.

### Wipe-all warning

There is no `purge --all` and no `--before now` sugar today. The safe spelling
for "purge everything eligible right now" is:

```bash
./safe-delete purge --before "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --json   # preview first
./safe-delete purge --before "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --execute --yes --json
```

**`--before` accepts a future timestamp, and a future cutoff makes every active
entry immediately eligible.** A command such as
`--before 2099-01-01T00:00:00Z --execute --yes` is legal and physically removes
**all** active entries. That is wipe-all semantics, not a typo guard — there is
no prompt or second confirmation past `--yes`. The safest form of this is
**first** running the same invocation without `--execute --yes` and confirming
that `candidates` matches your intent. The `--before now` rejection message is
not an invitation to substitute a future date.

One boundary of the `--before "$(date -u +%Y-%m-%dT%H:%M:%SZ)"` spelling, so
nobody mistakes it for breakage: `date` emits whole seconds, so an entry whose
age anchor falls in the *current* second is still `too_young` relative to that
truncated cutoff and is **not** among the candidates. Entries added at least a
second earlier are all candidates. If the preview returns fewer candidates than
you expected, read `decisions[].reason` and re-run rather than reaching for a
future timestamp.

### Crash recovery is not capped by the cutoff

A run interrupted between intent and completion leaves `purge_pending` entries
that recovery will finish on the next `purge`. Recovery deliberately does **not**
re-check the current policy cutoff (`retention.py` records this explicitly), so a
strict `--older-than 30d` does not scope it. Do not assume a narrow window
protects entries that a previous run already selected.

## 5. Bypass inventory — out of coverage

This is the verbatim `out_of_coverage` list reported by `hook status --json` and
the P4 replay map (`docs/project/p4-hook-coverage.md`). It is the complete
statement of what the product does **not** intercept. Do not soften it to "most
deletions are caught".

1. Python/Go/Node filesystem APIs
2. `find -delete`
3. `git clean`
4. `busybox rm`
5. absolute `/bin/rm`, `/bin/unlink`, or `/bin/rmdir`
6. another unconfigured agent/tool
7. a container or namespace without the hook
8. a privileged or human process
9. PATH reordering
10. disabled or uninstalled integration

Additionally: **Windows-side PowerShell** (`Remove-Item` and friends) is outside
the boundary by construction — this product does not run on native Windows at
all (see § 6). Nothing on the Windows side of a WSL split is covered.

The supported boundary is exactly: a registered PreToolUse integration
(`claude`, `cursor`) plus the PATH shim, and only for the `(host, config_path)`
boundary that is actually registered. Treat everything else as unprotected.

## 6. Platform and path forms

**Supported:** Linux, macOS, and WSL. **Not supported:** native Windows Python.

The storage layer imports `fcntl` at module import time and uses
`O_NOFOLLOW`/`O_DIRECTORY`. On a native Windows interpreter **every** subcommand,
including `version`, raises `ModuleNotFoundError: No module named 'fcntl'`. That
message means the wrong interpreter was used, not that the product is broken —
run it inside WSL (or Linux/macOS) with a POSIX Python.

| Path form | Status |
| --- | --- |
| `/home/<user>/project` (WSL-native) | Supported. This is the expected working shape. |
| `/mnt/c/...` (DrvFs) | **Unverified configuration.** DrvFs is a different filesystem from the WSL home root, so `add` of a `/mnt/c` path into a home-based root is rejected with `cross_device`. Putting the root itself under `/mnt/*` is untested: `fcntl` locking semantics on 9P/DrvFs have no evidence behind them. Do not treat a green `hook status` on such a root as proven enforcement. |
| `\\wsl$\...` | **Denied.** The hook protocol requires an absolute, normalized POSIX `cwd`; a Windows-side path form is fail-closed denied — in practice every `rm` inside Cursor is refused. |

Hook requests need a POSIX `cwd`, and the installed adapter is a
`#!/usr/bin/env python3` payload with POSIX absolute paths — a native Windows
Cursor cannot execute it. The only supported shape for "Cursor on Windows,
project in WSL" is **Cursor's terminal/agent shell running inside WSL**. To
check, run `uname` and `which python3` in the Cursor terminal; a Linux kernel and
a POSIX `python3` mean you are in the supported case. Symmetric bridge recipes
such as invoking the CLI from Windows into WSL are unverified and must not be
documented as supported.

The ledger lives inside the WSL home. Windows-side tools generally cannot see
it; the observability promise is "run `list`/`show` inside WSL".

## 7. Hook status and boundary reading

`hook status` exists today. There is **no** top-level `status` command and **no**
`doctor` command in this version — `./safe-delete --help` lists
`{init,add,list,show,restore,purge,hook,version}` only.

```bash
./safe-delete hook status --json          # all selectors
./safe-delete hook status claude --json   # one selector
```

`hook status` (no selector) prints one entry per selector
(`claude`, `cursor`, `path-shim`), each with:

- `enforced` — the honest bit. Only a proven boundary is `true`.
- `installed` / `registered` — configuration was written; not proof of coverage.
- `registry_valid`, `adapter_runnable`, `cli_path` — whether the registered
  payload still resolves and the pinned CLI still exists.
- `storage.usable` — the root is writable. **Writable is not safe.**
- `out_of_coverage` — the list from § 5, carried verbatim.
- `warning` — the boundary-specific honesty line (for example "integration is
  installed but enforcement is not proven at this boundary").

`enforced: true` only ever means "this one `(host, config_path)` boundary is
proven". It never means "your current project is covered" — Cursor installs are
**per project**, so each project must be installed explicitly (§ 8). If
`storage.usable` is `false` with `reason_code: storage_unavailable`, run
`init` first.

### PATH shim activation is operator-owned

Installing `path-shim` writes shim executables but **does not modify your shell
startup files**. The install result carries a hint such as
`path_activation: "prepend <dir> to PATH"`. Activation is your responsibility:

```bash
export PATH="$XDG_DATA_HOME/safe-delete/bin:$PATH"
```

Subsequent shells, other tools, and other agents may reorder PATH, and
`path_precedence` in `hook status` only reflects the **current process**
environment. After changing PATH, re-check with `hook status` — and put the
export somewhere durable if you need it in new shells.

Install-time trust notes: `hook install --cli PATH` accepts any executable path
and pins it into the registry, including a world-writable script. Prefer the
repository's own `./safe-delete`, and never point `--cli` at a path another user
can write. Tightening this is a P7 proposal item, not current behavior.

## 8. Installing hooks — per-project reality

`claude` registers user-global (`~/.claude/settings.json` by default); `cursor`
registers **project-local** (`<project>/.cursor/hooks.json`), resolved from the
current working directory. Install from the project you mean to protect:

```bash
cd /path/to/project
/path/to/safe-delete/safe-delete hook install cursor --json
```

Because the registry keys Cursor by selector, a second project does not silently
get covered — see `docs/project/p7-install-notes.md` (counterexample B) for the
exact failure and the uninstall-then-install workaround. `uninstall` clears only
the registered boundary; it does not clean up other projects' config files.

## 9. What this document does not claim

- No `doctor` command, no top-level `status`, no `purge --all`/`--before now`
  sugar, no install self-lock fix, no platform preflight. All are P7 Freeze
  Issue proposals.
- No GUI, tray, dashboard, or web viewer exists or is planned for this phase.
- No scheduler installation: cron/systemd setup is operator-owned.
- No claim about native Windows, about `/mnt/*` roots, or about a real Cursor
  host replay — the Cursor integration is verified at the protocol layer; a real
  Cursor session replay is a P7 evidence gap.
