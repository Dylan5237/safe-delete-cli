# P7 install notes — known limits and workarounds

Status: **docs-only, pre-freeze.** Everything here is a **known limit with a
workaround**, not a fix. All three counterexamples reproduce on
`main @ bf9d21e` and none of them are addressed by this slice. Fixes are
freeze-gated proposal items in the P7 Freeze Issue; see
`docs/project/p7-adversarial-review.md` § 10 (must-fix 1, 2, 3).

Output excerpts below were produced with a disposable `HOME` and
`SAFE_DELETE_ROOT`; home paths are redacted as `$HOME` or `<dir>`.

## A — default-path install self-locks (`path_forbidden`)

On a machine with no `SAFE_DELETE_ROOT` and no `XDG_DATA_HOME`, the package root
and the default storage root are the **same** directory
(`$HOME/.local/share/safe-delete`). Install refuses to write anything inside the
storage namespace, including the package's own `hooks/` and `bin/` directories,
so a stock machine fails closed:

```console
$ env -i HOME="$HOME" PATH="$PATH" ./safe-delete hook install claude --json
{"command":"hook install","ok":false,"results":[],"errors":[{"code":"path_forbidden","message":"hook management path is inside safe-delete storage: $HOME/.local/share/safe-delete","path":"$HOME/.local/share/safe-delete","storage_path":"$HOME/.local/share/safe-delete"}]}
$ echo $?
2
```

**Impact.** "One-shot install" does not work on a default machine. The tests
never caught it because every hook test points `XDG_DATA_HOME` and
`SAFE_DELETE_ROOT` at *different* directories. The contract
(`docs/architecture/freeze.md` § Installation and package boundaries) places the
payload under `$XDG_DATA_HOME/safe-delete/hooks/`, which is exactly what the
guard rejects — the contract and the guard disagree; one of them has to change.

**Workaround today.** Separate the two roots before installing — either:

```bash
export SAFE_DELETE_ROOT="$HOME/safe-delete-root"   # storage away from the package
./safe-delete hook install claude --json
```

or keep them distinct via `XDG_DATA_HOME` so the package root and the storage
root are different directories. Do this **before** the first install; a failed
install writes nothing.

**Not fixed here.** The fix (allow `hooks/`/`bin/` to be colocated with the
storage root, or move the package root out of the storage namespace) changes
`_reject_storage_namespace` and needs `FREEZE ACK`.

## B — multi-project Cursor install is a silent no-op

Cursor installs are project-local: the config path resolves from the current
working directory. The registry, however, keys Cursor by selector alone, so the
**first** install wins and later projects are silently ignored.

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

**Impact.** Exit 0 with `ok:true, changed:false`, and the config path in the
output is still project A's. Project B has no hook at all, and `hook status`
stays green because it only reports the registered boundary. The user believes
the new project is protected; it is not. Even if a hook were present, `enforced`
would only ever mean "this one `(host, config_path)` boundary is proven" — never
"your current project is covered".

**Attempting an explicit retarget also fails closed.** Passing `--project` or
`--config` for the *other* project while a different boundary is registered is
rejected rather than retargeted:

```console
$ cd <projB> && /path/to/safe-delete hook install cursor --project <projB> --json
{"command":"hook install","ok":false,"results":[],"errors":[{"code":"storage_failure","message":"hook configuration does not match the recorded integration boundary","selector":"cursor"}]}
$ echo $?
4
```

The flags exist (`hook install --help` lists `--project` and `--config`), but
they do not switch projects once a boundary is registered.

**Workaround today.** Uninstall the registered boundary, then install from the
new project's cwd:

```bash
cd <projA> && /path/to/safe-delete hook uninstall cursor --json   # clears the registration
cd <projB> && /path/to/safe-delete hook install cursor --json     # now targets projB
```

Verified: after that sequence project B gets `changed:true` and its own
`.cursor/hooks.json`.

**Uninstall scope is narrow.** `uninstall` only clears the **registered**
`config_path`; it does not visit other projects. It rewrites that one file to
`{"hooks":{"preToolUse":[]}}` rather than deleting it, and it leaves
`.cursor/hooks.json` files belonging to other projects untouched. Other
projects' entries can therefore survive an uninstall while pointing at a payload
that no longer exists — always inspect each project's config after a retarget.

**Not fixed here.** Either fail-closed on a config mismatch at install time or
key the registry by `(selector, config_path)`; both are proposal items.

## C — the installed payload is hardcoded to the checkout

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
(`<repo-checkout>/safe-delete`). There is no vendored, self-contained payload.

**Impact.** Moving or deleting the checkout after install leaves every
installed hook unable to import `safe_delete`. Deletions then fail closed —
which is the safe direction, but the user sees only refusals with no obvious
cause. `hook status` can report `adapter_runnable:false` / a stale `cli_path`,
but the install itself prints no "this is a development checkout, do not treat
it as a production install" warning.

**Workaround today.** Decide the final location of this repository **before**
the first install, and do not move or delete it afterwards. If it must move,
uninstall, reinstall from the new location, and re-check with `hook status`.

**Not fixed here.** A vendored single-file payload and a
"payload source is a git checkout" warning are future freeze items.

## Path-shim activation is not automatic

`hook install path-shim` writes shim executables but never edits shell startup
files. It returns a hint only:

```json
"path_activation": "prepend <shim-dir> to PATH"
```

Activation is the operator's job. Use the exact directory from the install hint
(`hook status` reports it as `boundary.shim_dir` / `boundary.prepend_path`, by
default `$XDG_DATA_HOME/safe-delete/bin`):

```bash
export PATH="<shim-dir-from-install-hint>:$PATH"
```

After editing PATH, re-check with `hook status`: `path_precedence` reflects only
**the current process** environment, and later shells, tools, or other agents may
reorder PATH. There is no guarantee that a prepend made now still holds in a
future shell.

## `--cli` accepts any executable

`hook install --cli PATH` validates that the path is executable and then pins it
into the registry. A world-writable script is accepted. Post-install routing
deliberately keeps using the registered CLI (which correctly blocks
`SAFE_DELETE_CLI` shadowing), so a bad `--cli` chosen at install time is pinned
faithfully. Prefer the repository's own `./safe-delete`, and never point `--cli`
at a path another user can write. Refusing or warning on a world-writable `--cli`
is a proposal item, not current behavior.

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
