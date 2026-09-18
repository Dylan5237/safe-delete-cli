# P7 install notes — known limits and workarounds

Status: **post-freeze implementation record, branch `fix/22-install-doctor`
(Issue #22, FREEZE ACK recorded 2026-09-18), not a Phase PASS.**

This document previously described three counterexamples as *known limits with
workarounds, not fixes*, reproduced on `main @ bf9d21e`. Two of them are now
fixed by the frozen option and one remains a documented limit. Each section
below states its current status; `docs/project/p7-adversarial-review.md` § 10
remains the pre-freeze review artifact and should be read with this status
overlay.

| Counterexample | Pre-freeze status | Now |
| --- | --- | --- |
| A — default-path install self-locks | not fixed | **fixed** (allow the package's own `hooks/`/`bin/` under the storage root) |
| B — multi-project Cursor install is a silent no-op | not fixed | **fixed** (fail closed on a resolved/recorded boundary mismatch) |
| C — installed payload hardcoded to the checkout | not fixed | **still limited**; the install now warns, the pinning itself is unchanged |

Output excerpts below were produced with a disposable `HOME` and
`SAFE_DELETE_ROOT`; home paths are redacted as `$HOME` or `<dir>`.

## A — default-path install self-locks (`path_forbidden`) — fixed

On a machine with no `SAFE_DELETE_ROOT` and no `XDG_DATA_HOME`, the package root
and the default storage root are the **same** directory
(`$HOME/.local/share/safe-delete`). The guard used to treat that whole root as
reserved, including the package's own `hooks/` and `bin/` directories, so a
stock machine failed closed:

```console
$ env -i HOME="$HOME" PATH="$PATH" ./safe-delete hook install claude --json
{"command":"hook install","ok":false,"results":[],"errors":[{"code":"path_forbidden","message":"hook management path is inside safe-delete storage: $HOME/.local/share/safe-delete","path":"$HOME/.local/share/safe-delete","storage_path":"$HOME/.local/share/safe-delete"}]}
$ echo $?
2
```

The contract (`docs/architecture/freeze.md` § Installation and package
boundaries) places the payload under `$XDG_DATA_HOME/safe-delete/hooks/` and the
PATH shim under `$XDG_DATA_HOME/safe-delete/bin/`, which is exactly what the
guard rejected — the contract and the guard disagreed.

**Fix.** `_reject_storage_namespace` now reserves only the *runtime* namespaces:
`trash/` (and therefore `trash/objects`), `ledger.jsonl`, and `locks/`. The
storage root itself is no longer reserved, so the package's own `hooks/` and
`bin/` may share it. The same default-path invocation now succeeds:

```console
$ env -i HOME="$HOME" PATH="$PATH" ./safe-delete hook install claude --json
{"command":"hook install","ok":true,"results":[{"selector":"claude",...,"enabled":true,"installed":true,"boundary":{"config_path":"$HOME/.claude/settings.json","registered":true},"changed":true,...}],"errors":[]}
$ echo $?
0
```

**What is still forbidden under the default paths.** Writing into the runtime
namespaces fails closed with `path_forbidden` exactly as before, even though the
package root is now allowed:

```console
$ ./safe-delete hook install claude --config "$HOME/.local/share/safe-delete/ledger.jsonl" --json
{"command":"hook install","ok":false,"results":[],"errors":[{"code":"path_forbidden",...,"storage_path":"$HOME/.local/share/safe-delete/ledger.jsonl"}]}
```

Installing still never moves, rewrites, or deletes trash objects or ledger
lines. Tests `test_default_paths_hook_install_succeeds` and
`test_runtime_namespaces_stay_forbidden_when_defaults_collapse` cover both
directions; they use a true default path (both `SAFE_DELETE_ROOT` and
`XDG_DATA_HOME` unset, disposable `HOME`) rather than splitting the two roots.

**Note.** A successful install is not proof of enforcement. With no layout
initialized the same status reads `installed: true`, `enforced: false`,
`storage.usable: false`. Run `init`, then re-check with `hook status` or
`doctor`.

## B — multi-project Cursor install is a silent no-op — fixed

Cursor installs are project-local: the config path resolves from the current
working directory. The registry keys Cursor by selector alone, so the **first**
install used to win and later projects were silently ignored:

```console
# project A
$ cd <projA> && /path/to/safe-delete hook install cursor --json
  ... "boundary":{"config_path":"<projA>/.cursor/hooks.json","registered":true}, "changed":true

# project B, a different project
$ cd <projB> && /path/to/safe-delete hook install cursor --json
{"command":"hook install","ok":true,"results":[{"selector":"cursor",...,"boundary":{"config_path":"<projA>/.cursor/hooks.json","registered":true},...,"changed":false,"config_created":false}],"errors":[]}
$ echo $?
0

$ ls <projB>/.cursor
ls: cannot access '<projB>/.cursor': No such file or directory
```

Exit 0 with `ok:true, changed:false`, project A's path in the output, and no hook
in project B.

**Fix.** When neither `--config` nor `--project` is given, install compares the
cwd-resolved `config_path` against the recorded boundary. A mismatch fails
closed instead of adopting the recorded boundary:

```console
$ cd <projB> && /path/to/safe-delete hook install cursor --json
{"command":"hook install","ok":false,"results":[],"errors":[{"code":"storage_failure","message":"hook install resolved a different host configuration than the recorded integration boundary; pass --project or --config for the intended boundary, or uninstall the recorded integration first","selector":"cursor","recorded_config_path":"<projA>/.cursor/hooks.json","resolved_config_path":"<projB>/.cursor/hooks.json"}]}
$ echo $?
4
```

Project B's config is not created, the registry is unchanged, and no
`ok:true`/`changed:false` result is returned for an unprotected project.

**Retargeting is explicit, and explicit flags are still checked.** Passing
`--project`/`--config` for the other project while a different boundary is
registered continues to fail closed (the message and exit code now agree with
the cwd case) rather than retargeting silently:

```console
$ cd <projB> && /path/to/safe-delete hook install cursor --project <projB> --json
{"command":"hook install","ok":false,"results":[],"errors":[{"code":"storage_failure","message":"hook configuration does not match the recorded integration boundary","selector":"cursor"}]}
$ echo $?
4
```

**Retarget procedure.** Uninstall the registered boundary, then install from the
new project's cwd or with explicit flags:

```bash
cd <projA> && /path/to/safe-delete hook uninstall cursor --json   # clears the registration
cd <projB> && /path/to/safe-delete hook install cursor --json     # now targets projB
```

Verified: after that sequence project B gets `changed:true` and its own
`.cursor/hooks.json`.

**Uninstall scope is still narrow.** `uninstall` only clears the **registered**
`config_path`; it does not visit other projects. It rewrites that one file to
`{"hooks":{"preToolUse":[]}}` rather than deleting it, and it leaves
`.cursor/hooks.json` files belonging to other projects untouched. Other
projects' entries can therefore survive an uninstall while pointing at a payload
that no longer exists — always inspect each project's config after a retarget.

**Keying by `(selector, config_path)` remains a future option.** The frozen fix
chose fail-closed; the registry is still keyed by selector, so only one Cursor
boundary can be registered at a time.

## C — the installed payload is hardcoded to the checkout — still limited

The installed adapter embeds the absolute path of the checkout that ran the
install:

```console
$ head -6 "$HOME/.local/share/safe-delete/hooks/v1/pretooluse"
#!/usr/bin/env python3
# safe-delete-hook-owner: safe-delete/protocol-v1
import sys
sys.path.insert(0, "<repo-checkout>")
from safe_delete.hook import main as _safe_delete_hook_main
raise SystemExit(_safe_delete_hook_main(['--adapter', 'pretooluse']))
```

The registry entry pins `cli_path` to the same checkout
(`<repo-checkout>/safe-delete`). There is still no vendored, self-contained
payload.

**Impact (unchanged).** Moving or deleting the checkout after install leaves
every installed hook unable to import `safe_delete`. Deletions then fail closed —
the safe direction — but the user sees only refusals with no obvious cause.

**What changed: the install no longer stays silent.** Install walks up from both
the payload source and the registered CLI looking for a Git checkout marker
(`.git`, file or directory, so worktrees are included) and returns one warning
per distinct checkout:

```json
"install_warnings": ["payload or CLI source is a git checkout: <repo-checkout>; this boundary pins that path, so moving or deleting the checkout makes every installed hook fail closed"]
```

`doctor` reports the same fact as a problem row
(`payload source is a git checkout: <repo-checkout>; moving or deleting the
checkout makes every installed hook fail closed`) and sets
`needs_attention: true`. This is a warning plus a read-only check, not a fix:
the pinning itself is unchanged, and there is still no vendored payload.

**Workaround today.** Decide the final location of this repository **before**
the first install, and do not move or delete it afterwards. If it must move,
uninstall, reinstall from the new location, and re-check with `hook status` or
`doctor`.

## Path-shim activation is not automatic

`hook install path-shim` writes shim executables but never edits shell startup
files. It returns a hint only, and the hint now names the directory, the
re-check command, and `doctor`:

```json
"path_activation": "prepend <shim-dir> to PATH, then re-check with `safe-delete hook status path-shim` or `safe-delete doctor`"
```

Activation is the operator's job. Use the exact directory from the install hint
(`hook status` reports it as `boundary.shim_dir` / `boundary.prepend_path`, by
default `$XDG_DATA_HOME/safe-delete/bin`):

```bash
export PATH="<shim-dir-from-install-hint>:$PATH"
```

After editing PATH, re-check with `hook status` or `doctor`: `path_precedence`
reflects only **the current process** environment, and later shells, tools, or
other agents may reorder PATH. There is no guarantee that a prepend made now
still holds in a future shell.

## `--cli` still accepts any executable, but a loose one is now reported

`hook install --cli PATH` validates that the path is executable and then pins it
into the registry. A world-writable script is still accepted — the frozen item
was "reject **or** hard-warn", and the hard-warn option was taken:

```json
"install_warnings": ["registered CLI is world-writable: <path>; another user could replace the command this boundary runs"]
```

`doctor` reports the same condition with the same wording, as a problem row that
sets `needs_attention: true` (only while at least one boundary is installed).
Post-install routing deliberately keeps using the registered CLI (which
correctly blocks `SAFE_DELETE_CLI` shadowing), so a bad `--cli` chosen at install
time is still pinned faithfully. Prefer the repository's own `./safe-delete`;
rejecting the install outright remains a future option.

## `doctor` — read-only aggregation

`safe-delete doctor --json` exists now. It is **read-only**: it never writes,
creates, or repairs, and it does not initialize a storage root. It aggregates:

- `platform_preflight` — `required`/`passed`/`missing_primitives`;
- `storage` — the resolved root and whether it is currently usable;
- `boundaries` — the same per-selector `hook status` entries, each carrying its
  own `out_of_coverage` list verbatim;
- `artifacts` — the captured payload source of every *installed* package
  artifact, with `payload_source_exists` and `git_checkout`;
- `problems` also covers an installed boundary whose package file is gone or no
  longer importable (a stale registry entry from a moved checkout, or an adapter
  deleted after install): `installed hook payload is missing or not runnable at
  boundary <selector>: <path>; every hook decision at this boundary fails
  closed`;
- `cli` — the resolved CLI paths and which of them are world-writable;
- `out_of_coverage` — the § 5 inventory, carried verbatim;
- `scope` — `enforced applies only to a registered (host, config_path)
  boundary`;
- `problems` / `needs_attention` — only what was detected in the inspected
  surfaces;
- `restore.residual_note` — the Exception #12 residual note, unchanged.

**What `doctor` must never be read as claiming.** `needs_attention: false` means
only that no problem was detected in the surfaces above. It is not a statement
that the current project is protected, that a usable storage root makes deletion
safe, that Exception #12 is fixed, or that anything outside the bypass inventory
in § 5 is covered. The bypass entries are reported as *data* precisely because
they are the statement of what is **not** covered.

## Cursor schema — protocol verified, real host not replayed

The Cursor integration writes:

```json
{"hooks":{"preToolUse":[{"command":"<adapter-path>"}]}}
```

This is verified at the **protocol layer** only. The P6 evidence is synthesized
protocol payloads plus Claude-style configuration; there is no recorded replay
from a real Cursor session. A real Cursor host replay (project in WSL,
PreToolUse trigger captured as an artifact) is a **P7 evidence gap**. Until that
exists, do not describe the Cursor install as verified end-to-end.
