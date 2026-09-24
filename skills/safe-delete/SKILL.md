---
name: safe-delete
description: >
  Use the safe-delete CLI instead of raw deletion. Move files and directories
  into a recoverable trash (add/list/show/restore), reclaim space with a
  preview-then-confirm flow (empty) or a retention-scoped purge, install and
  verify the Claude/Cursor/PATH hook boundary (setup, hook), and read doctor
  without mistaking it for a coverage claim. Use when an agent is about to run
  rm/rmdir/unlink, "clean up" a workspace, or delete build output; when asked
  what was deleted or how to get it back; and when installing or checking the
  deletion boundary for Claude Code or Cursor.
---

# safe-delete — agent skill

`safe-delete` moves a path into a per-root trash with a ledger instead of
unlinking it. Everything is reversible through `restore` until a purge removes
the payload. This skill lists real, currently shipped flags only; run
`safe-delete <command> --help` to confirm on the version you have, and read
[docs/project/p7-agent-usage.md](../../docs/project/p7-agent-usage.md) for the
full walkthrough, worked examples, and the canonical flag list.

## Platform

Supported: **Linux, macOS, and WSL** (`fcntl`, `O_NOFOLLOW`, `O_DIRECTORY`).
Native Windows Python is **not supported** — it is an unsupported interpreter
and is outside the boundary, by construction. On a native Windows interpreter
the CLI prints one line and exits `2`:

```text
unsupported platform: requires Linux/macOS/WSL (fcntl)
```

Nothing on the Windows side of a WSL split is covered by this product.

WSL DrvFs (`/mnt/<drive>`) is a different filesystem from the WSL home root.
`add` of a `/mnt/<drive>` path into a home root fails with `cross_device`
(exit 2). Do not copy. Do not `rm`. Never invent `--root` under `/mnt` for a
cross-device source. A same-drive root is the supported shape only when its
final component is `safe-delete` and the source has the same `st_dev`. Read
`errors[].code` (`cross_device` versus success). On that root:

```text
DrvFs/9p root: same-filesystem rename uses renameat (flags 0) after lstat because renameat2(RENAME_NOREPLACE) is not supported. Atomic rename, not a copy. Check/rename race remains. Not an Exception #12 change.
```

That residual is not Exception #12. `doctor` `needs_attention: false` is not a
`RENAME_NOREPLACE` claim and is not set solely because the root is 9p.
`enforced: true` is only the registered hook boundary. `\\wsl$\...` remains
denied.

## Rules for agents

- **Always pass `--json`.** Machine output is the stable interface; human
  output is presentation only and may change in any commit. With neither
  `--human` nor `--json` the CLI prints JSON whenever stdout is not a TTY, but
  do not rely on the default — be explicit.
- **Never delete with `rm`, `unlink`, or `rmdir` yourself** when this CLI is
  available. Use `safe-delete add`.
- Exit categories: `0` success, `2` usage error, `3` not found, `4` fail-closed
  state/ledger problem, `5` partial failure. Read `errors[].code` — never
  parse the message text.
- **`doctor`'s `needs_attention: false` means only "nothing was detected in the
  surfaces it inspects". It never means "protected", and it is not a coverage
  or enforcement claim for any boundary.**
- A registered boundary is only ever one `(host, config_path)` pair.
  `enforced: true` means that one pair is proven, never that a project is safe.

## Commands (shipped surface)

Global flags on every command: `--root DIR`, `--json`, `--human`.

| Command | Purpose |
| --- | --- |
| `init` | Create the storage root and its empty ledger. Idempotent. |
| `add PATHS...` | Move each path into the trash. `--dry-run`, `--reason`, `--project`, `--session-id`, `--agent`, `--tool`, `--extensions`. |
| `list` | List entries. `--all`, `--orphans`, `--project`, `--original`, `--limit N`. |
| `show ENTRY_ID` | One entry with its ordered lifecycle events. |
| `restore ENTRY_ID` | Move a payload back. `--to PATH`, `--create-parents`. |
| `purge` | Retention-scoped removal of payloads. Preview by default; `--older-than`, `--before`, `--execute`, `--yes`, `--dry-run`. |
| `empty` | Remove everything currently eligible, with an explicit confirmation token. `--older-than`, `--before`, `--confirm TOKEN`. |
| `setup [claude\|cursor\|path\|workbuddy]` | One-shot: platform preflight, `hook install`, read-only `doctor`, next steps. `--init` opts in to creating the storage root; `--host`, `--config`, `--project`, `--cli`. |
| `hook install\|status\|disable\|uninstall [selector]` | Manage the boundaries. `--host`, `--config`, `--project`, and `--cli` on `install`. |
| `doctor` | Read-only aggregate report. Writes, creates, repairs, and configures nothing. |
| `version` | Version and contract/schema versions. |

Selectors: `claude` (user-global), `cursor` (project-local), `workbuddy`
(user-global WorkBuddy desktop; settings under `~/.workbuddy` or `$WORKBUDDY_CONFIG_DIR`), `path-shim`
(alias `rm-shim`). `setup path` is a setup-only spelling of `path-shim`.
There is no user-facing `codebuddy` selector.

## Deleting a file or directory

```bash
safe-delete add --json --reason "build cleanup" -- ./dist
```

Read the result: `entry_id`, `state`, `original_path`, `trashed_path`. Keep the
`entry_id` — it is what `restore` and `show` take. If a path no longer exists,
`add` reports `source_not_found` and changes nothing; if it is already inside
the storage root, it is refused with `path_forbidden`.

Recover with:

```bash
safe-delete restore --json <ENTRY_ID>
```

## Reclaiming space

### `empty` — preview, read, confirm

`safe-delete empty` **removes nothing** without `--confirm TOKEN`, and the
token only exists after a preview of the current candidate set.

```bash
# 1. Preview. Nothing is removed, no ledger event is appended.
safe-delete empty --json

# 2. Read the report. `candidates` is exactly what a confirm will remove.
#    With no threshold flag the cutoff is this invocation's own clock, so
#    every active entry is a candidate and the report carries the wipe-all
#    warning. Narrow it deliberately with --before <past RFC3339> or
#    --older-than <Nd|Nh> if that is not what you want.

# 3. Confirm the same candidate set, with the same threshold flags.
safe-delete empty --confirm <confirm_token> --json
```

`confirm_token` binds the storage root and the sorted candidate `entry_id`
set; it is a **staleness check, not a secret**, and it is not an authentication
boundary. If the candidate set changed between preview and confirm (an `add`,
a `restore`, age crossing an `--older-than` bound), the token no longer
matches, the command fails closed with `usage_error`, exit `2`, no
`purge_intent`, and nothing removed. `--execute`, `--yes`, and `--dry-run` are
not `empty` flags: passing one is a usage error (exit `2`), and a bare
`--confirm` with no value is one too.

### `purge` — retention-scoped removal

`purge` previews by default; physical removal requires **both** `--execute`
and `--yes`. Its threshold precedence is `--older-than`/`--before` →
`SAFE_DELETE_RETENTION_DAYS` → 30 days, and the report's `policy.source` names
the winner. Unlike `empty`, the 30-day default applies, so `purge` is the
command for a policy-scoped cleanup.

```bash
safe-delete purge --json                      # preview: mode dry_run
safe-delete purge --execute --yes --json      # only after reading the preview
```

> Never append --execute --yes as a default or habit.

The confirmation flags are a deliberate decision gate, not a login flag. A
preview that lists candidates you did not expect is a stop signal. Removal
failures are reported per entry (`purge_failed` / `purge_remove_failed`), the
entry stays `active`, and the command returns `partial_failure` (exit `5`).

## Installing and checking a boundary

```bash
safe-delete setup --json                  # read-only: state + selectors
safe-delete setup claude --init --json    # install Claude's boundary, then doctor
safe-delete setup workbuddy --init --json # install WorkBuddy PreToolUse boundary
safe-delete setup path --json             # PATH shim; activation is operator-owned
safe-delete hook status --json            # per-selector installed/enforced/warning
safe-delete doctor --json                 # read-only aggregate report
```

- **`setup` never initializes storage without `--init`.** Without it, an
  unusable root is reported with the exact `safe-delete init` command to run.
- `setup` never edits shell startup files, installs cron/systemd units,
  retargets a registered boundary, or claims coverage. PATH activation stays
  operator-owned: prepend the shim directory yourself.
- Cursor is project-local. A second project for an already-registered Cursor
  boundary fails closed (`storage_failure`, exit `4`) and points at
  `hook uninstall cursor` from the recorded project, then `setup cursor` from
  the intended one. It never silently retargets.
- A successful install is **not** enforcement. Check `enforced` per
  `(host, config_path)` boundary; a boundary with a doctor problem fails
  closed, and a `warning` on a selector is not softened into a safety claim.

## Out of coverage — bypass inventory

This is the verbatim `out_of_coverage` list reported by `hook status --json`
and `doctor --json`. It is the complete statement of what this product does
**not** intercept. Do not soften it.

1. Python/Go/Node filesystem APIs
2. find -delete
3. git clean
4. busybox rm
5. absolute /bin/rm, /bin/unlink, or /bin/rmdir
6. another unconfigured agent/tool
7. a container or namespace without the hook
8. a privileged or human process
9. PATH reordering
10. disabled or uninstalled integration

## Residual risk

> Exception #12 — P2-only same-UID staging publication — excluded model / residual risk; not fixed

It is not fixed, and no output, flag, or document may claim otherwise. Nothing
here is an authentication or same-UID isolation boundary: the ledger, the trash
payloads, and the `empty` confirmation token are readable and forgeable by any
process running as the same user.

## See also

- [docs/project/p7-agent-usage.md](../../docs/project/p7-agent-usage.md) — the
  full agent walkthrough (setup, storage root, every command with JSON
  examples, threshold semantics, crash recovery).
- [docs/project/p4-hook-coverage.md](../../docs/project/p4-hook-coverage.md) —
  the replay map for the bypass inventory above.
- [docs/architecture/freeze.md](../../docs/architecture/freeze.md) — the frozen
  storage, ledger, identity, restore, and purge contracts.
- [docs/architecture/exceptions.md](../../docs/architecture/exceptions.md) —
  Exception #12, the excluded model behind the residual line above.
