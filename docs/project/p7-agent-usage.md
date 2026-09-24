# P7 agent usage guide — current behavior

Status: **post-freeze implementation record, branch `fix/22-install-doctor`
(Issue #22, FREEZE ACK recorded 2026-09-18), not a Phase PASS.**

The sections below were originally written pre-freeze against `main @ bf9d21e`
as proposal material. They now describe the implemented behavior on this branch:
the `doctor` subcommand, the platform preflight, the `--before now` purge sugar,
and the two install fixes (A and B) are implemented here. Counterexample C
(payload pinned to the checkout) is **not** fixed — it is now *warned about*, at
install time and by `doctor`. See `docs/project/p7-adversarial-review.md` for the
review this guide implements, and `docs/project/p7-install-notes.md` for the
install counterexamples and their status.

Every command and output excerpt below was run against a temporary
`SAFE_DELETE_ROOT` in this worktree, or on `bf9d21e` where a section is marked as
pre-freeze evidence. Entry ids shown as
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
| `purge --before now --json` | exit 0, `"mode":"dry_run"`, `"policy":{"source":"before_now",...}` |
| `purge --before now --execute --json` | exit 2, `usage_error`: `--execute requires --yes confirmation; no payloads were changed` |
| `purge --before NOW --json` | exit 2, `usage_error`: `--before must be an RFC3339 timestamp with a timezone` |

Threshold precedence: `--older-than`/`--before` → `SAFE_DELETE_RETENTION_DAYS`
→ 30 days. `--before` accepts an RFC3339 timestamp **with** a timezone — the
retention anchor is UTC, so use `Z` — or the exact literal `now`.
`2026-09-01T00:00:00Z` and `now` are valid; `2026-09-01`, `NOW`, and `now ` are
not.

### Wipe-all warning

`--before now` is sugar for "everything eligible right now". It resolves to the
invocation's own UTC clock (reported as `policy.as_of` / `policy.cutoff`), and
it **never** implies `--execute --yes`:

```bash
./safe-delete purge --before now --json                       # preview, always
./safe-delete purge --before now --execute --yes --json       # only after reading the preview
```

Whenever the resolved cutoff is not in the past — `--before now` always, and any
future RFC3339 instant — the report carries an explicit warning, so a wipe-all
preview is never silent:

```console
$ ./safe-delete purge --before now --json
{"command":"purge","ok":true,"results":[{"mode":"dry_run","dry_run":true,"policy":{"source":"before_now","as_of":"2026-09-18T09:06:42.205843Z","cutoff":"2026-09-18T09:06:42.205843Z","cutoff_utc":"2026-09-18T09:06:42.205843Z","threshold_days":null,"threshold_duration":null},"candidates":["bf5daada-c1e4-49a8-8553-3d513844b2e8"],"decisions":[…],"outcomes":[],"warning":"cutoff is not in the past: every active entry is eligible (wipe-all semantics); read candidates before extending this invocation with --execute --yes"}],"errors":[]}
```

(Output above is abridged only at `decisions`; every other key is verbatim.)

**`--before` accepts a future timestamp, and a future cutoff makes every active
entry immediately eligible.** A command such as
`--before 2099-01-01T00:00:00Z --execute --yes` is legal and physically removes
**all** active entries. That is wipe-all semantics, not a typo guard — there is
no prompt or second confirmation past `--yes`. The safest form of this is
**first** running the same invocation without `--execute --yes` and confirming
that `candidates` matches your intent.

An equivalent spelling is `--before "$(date -u +%Y-%m-%dT%H:%M:%SZ)"`. One
boundary of it, so nobody mistakes it for breakage: `date` emits whole seconds,
so an entry whose age anchor falls in the *current* second is still `too_young`
relative to that truncated cutoff and is **not** among the candidates. Entries
added at least a second earlier are all candidates. `--before now` does not have
that truncation gap, because the cutoff is the invocation clock itself rather
than a whole-second rendering of it.

### Crash recovery is not capped by the cutoff

A run interrupted between intent and completion leaves `purge_pending` entries
that recovery will finish on the next `purge`. Recovery deliberately does **not**
re-check the current policy cutoff (`retention.py` records this explicitly), so a
strict `--older-than 30d` does not scope it. Do not assume a narrow window
protects entries that a previous run already selected.

## 5. Bypass inventory — out of coverage

This is the verbatim `out_of_coverage` list reported by `hook status --json`,
carried unchanged into `doctor --json`, and used by the P4 replay map
(`docs/project/p4-hook-coverage.md`). It is the complete statement of what the
product does **not** intercept. Do not soften it to "most deletions are
caught".

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
`O_NOFOLLOW`/`O_DIRECTORY`. On a native Windows interpreter the entry point now
preflights the platform **before** that import and fails with one line instead of
a traceback:

```console
$ python ./safe-delete version
unsupported platform: requires Linux/macOS/WSL (fcntl)
$ echo $?
2
```

The message is written to stderr, nothing is written to stdout, and no storage
is created. `doctor --json` reports the same facts as data
(`platform_preflight.required`, `.passed`, `.missing_primitives`). This is a
diagnosis, not an enforcement or portability claim: it means the wrong
interpreter was used, not that the product is broken — and not that any
Windows-side deletion is covered. Run it inside WSL (or Linux/macOS) with a
POSIX Python.

| Path form | Status |
| --- | --- |
| `/home/<user>/project` (WSL-native) | Supported, unchanged. This is the expected working shape for a source and root on the WSL home filesystem. |
| `/mnt/<drive>/...` source, root on a different `st_dev` | `cross_device`, exit 2. This is the usual case when the root is the WSL home filesystem. Do not copy. Do not `rm`. Do not point `--root` at `/mnt` to bypass that unless the root's final component is `safe-delete` **and** the source is on that same drive. |
| same-drive root `.../safe-delete` | Supported with this residual: `DrvFs/9p root: same-filesystem rename uses renameat (flags 0) after lstat because renameat2(RENAME_NOREPLACE) is not supported. Atomic rename, not a copy. Check/rename race remains. Not an Exception #12 change.` `doctor` / `hook status` `enforced: true` is only the registered hook boundary. It is not proof of `RENAME_NOREPLACE` and not proof of Windows-side locking. |
| `\\wsl$\...` | **Denied.** The hook protocol requires an absolute, normalized POSIX `cwd`; a Windows-side path form is fail-closed denied — in practice every `rm` inside Cursor is refused. |

Hook requests need a POSIX `cwd`, and the installed adapter is a
`#!/usr/bin/env python3` payload with POSIX absolute paths — a native Windows
Cursor cannot execute it. The only supported shape for "Cursor on Windows,
project in WSL" is **Cursor's terminal/agent shell running inside WSL**. To
check, run `uname` and `which python3` in the Cursor terminal; a Linux kernel and
a POSIX `python3` mean you are in the supported case. Symmetric bridge recipes
such as invoking the CLI from Windows into WSL are unverified and must not be
documented as supported.

The default ledger lives inside the WSL home. A same-drive root whose final
component is `safe-delete` may live on `/mnt/<drive>` and serves only paths
with that same `st_dev`. Windows-side tools generally cannot see a home
ledger; the observability promise is "run `list`/`show` inside WSL".

## 7. Hook status and boundary reading

`hook status` exists, and so does `doctor`. There is still **no** top-level
`status` command — `./safe-delete --help` lists
`{init,add,list,show,restore,purge,hook,doctor,version}`.

```bash
./safe-delete hook status --json          # all selectors
./safe-delete hook status claude --json   # one selector
./safe-delete doctor --json               # read-only aggregate of the above
```

`doctor` is **read-only**: it never writes, creates, or repairs, and it does not
initialize a storage root. It aggregates the platform preflight, the resolved
storage root and its usability, the same per-selector `hook status` entries
(each carrying its own `out_of_coverage` verbatim), the captured payload source
of every *installed* artifact, and the resolved CLI paths with a world-writable
flag. `needs_attention` is true only when one of those inspected surfaces has a
problem; `false` means "nothing detected", never "your project is protected" and
never "deletion is safe". A 9p root does not by itself set `needs_attention`.
When the root's `f_type` is 9p, `storage.filesystem` is `v9fs`,
`storage.noreplace` is `emulated`, and `storage.noreplace_residual` is the
verbatim DrvFs check/rename sentence above. Other roots use
`storage.noreplace` `native` and `storage.noreplace_residual` null. `doctor`
stays read-only: the probe is `fstatfs` only. Human `doctor` prints that
residual sentence when `noreplace` is `emulated`. `enforced: true` is not
proof of `RENAME_NOREPLACE`.

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
startup files**. The install result carries a hint naming the exact directory
and the commands to re-check:

```json
"path_activation": "prepend <shim-dir> to PATH, then re-check with `safe-delete hook status path-shim` or `safe-delete doctor`"
```

Activation is your responsibility:

```bash
export PATH="$XDG_DATA_HOME/safe-delete/bin:$PATH"
```

Subsequent shells, other tools, and other agents may reorder PATH, and
`path_precedence` in `hook status` only reflects the **current process**
environment. After changing PATH, re-check with `hook status` or `doctor` — and
put the export somewhere durable if you need it in new shells.

Install-time trust notes: `hook install --cli PATH` accepts any executable path
and pins it into the registry, including a world-writable script. It now
**warns** in `install_warnings` when the registered CLI is world-writable
(`registered CLI is world-writable: <path>; another user could replace the
command this boundary runs`), and `doctor` reports the same condition as a
problem. It does not reject the install. Prefer the repository's own
`./safe-delete`, and never point `--cli` at a path another user can write.

Install also warns when the payload source or the CLI resolves inside a Git
checkout (`payload or CLI source is a git checkout: <checkout>; this boundary
pins that path, so moving or deleting the checkout makes every installed hook
fail closed`). That is counterexample C in `docs/project/p7-install-notes.md` —
flagged, not fixed.

The `path_activation` hint now names the directory and the re-check commands:

```json
"path_activation": "prepend <shim-dir> to PATH, then re-check with `safe-delete hook status path-shim` or `safe-delete doctor`"
```

## 8. Installing hooks — per-project reality

`claude` registers user-global (`~/.claude/settings.json` by default); `cursor`
registers **project-local** (`<project>/.cursor/hooks.json`), resolved from the
current working directory. Install from the project you mean to protect:

```bash
cd /path/to/project
/path/to/safe-delete/safe-delete hook install cursor --json
```

Because the registry keys Cursor by selector, only one Cursor boundary can be
registered at a time. Installing from a second project without `--project` or
`--config` now **fails closed** instead of silently reporting `changed: false`
against the first project:

```console
$ cd <projB> && /path/to/safe-delete hook install cursor --json
{"command":"hook install","ok":false,"results":[],"errors":[{"code":"storage_failure","message":"hook install resolved a different host configuration than the recorded integration boundary; pass --project or --config for the intended boundary, or uninstall the recorded integration first","selector":"cursor","recorded_config_path":"<projA>/.cursor/hooks.json","resolved_config_path":"<projB>/.cursor/hooks.json"}]}
$ echo $?
4
```

No `ok:true` result is ever returned for a project that was left unprotected.
Retarget with uninstall-then-install; `--project`/`--config` for a *different*
boundary while one is registered fails with
`hook configuration does not match the recorded integration boundary` (exit 4),
so the two paths agree. See `docs/project/p7-install-notes.md` (counterexample
B, now marked fixed) for the full before/after. `uninstall` clears only the
registered boundary; it does not clean up other projects' config files.

Remember the scope limit: `enforced: true` means **this one
`(host, config_path)` boundary is proven**. It never means "your current project
is covered".

## 9. What this document does not claim

- No top-level `status` command (only `hook status`, which `doctor` also
  reports) and no `purge --all`. `--before now` is sugar, not `--all`: it still
  previews by default and still requires `--execute --yes` to remove anything.
- No claim that install fixes A and B make a project protected. Counterexample
  C (the payload is pinned to the checkout) is **not** fixed — it is warned
  about at install time and reported by `doctor`. There is still no vendored,
  self-contained payload.
- No claim that `doctor`'s `needs_attention: false` means anything beyond "no
  problem was detected in the inspected surfaces". It is not a coverage claim,
  not a statement that Exception #12 is fixed, and not a statement that a
  usable storage root makes deletion safe.
- No GUI, tray, dashboard, or web viewer exists or is planned for this phase.
- No scheduler installation: cron/systemd setup is operator-owned.
- No claim about native Windows enforcement, about `/mnt/*` roots, or about a
  real Cursor host replay. The platform preflight only *diagnoses* a missing
  `fcntl`; it does not add Windows coverage. The Cursor integration is verified
  at the protocol layer; a real Cursor session replay is a P7 evidence gap.
