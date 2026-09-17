# P6 full-path evidence capture

This directory contains the replay scripts and redacted captures for Phase 6.
The hook blocker is resolved: P4 is tested at landed product SHA
`2710abb4e10d1ac473f007e94f00001d267a77ea` (`origin/main`). The captures were
run from the clean evidence checkout at replay/harness SHA
`f5b0fd601dcbe7bb5ae28b7e79f1c8a6d7ccb25f`.

The product SHA and evidence SHA are deliberately separate. The evidence PR
may receive later matrix/artifact commits; those commits are not product code
under test. The captured logs record both values, while `$CHECKOUT` and
`$TESTROOT` replace private absolute paths.

## Replay

Run from a clean checkout. `00_env.sh` creates disposable HOME/XDG package and
config directories, a workspace, and a `SAFE_DELETE_ROOT`; it never selects the
real user hook/config directories unless a caller explicitly overrides the
variables.

```bash
bash evidence/p6/scripts/00_env.sh
bash evidence/p6/scripts/01_cli_trash_restore.sh
bash evidence/p6/scripts/02_cli_metadata.sh
bash evidence/p6/scripts/03_cli_purge.sh
bash evidence/p6/scripts/04_hooks_pretooluse.sh
bash evidence/p6/scripts/05_hooks_path_shim.sh
bash evidence/p6/scripts/06_hooks_lifecycle_failclosed.sh
bash evidence/p6/scripts/07_hooks_bypass_inventory.sh
bash evidence/p6/scripts/08_full_path_composite.sh
```

For a stable disposable location, provide an explicit temporary directory to
each script invocation:

```bash
TESTROOT="$(mktemp -d /tmp/safe-delete-p6.XXXXXX)" \
  bash evidence/p6/scripts/08_full_path_composite.sh
```

The scripts require a clean checkout, install only into their temporary XDG
roots, use instrumented CLI wrappers and raw-command sentinels, fail on unmet
assertions, and print UTC start/end times. The PreToolUse script submits real
protocol-v1 requests to the installed adapter. The PATH script resolves and
executes the installed package-owned `rm`, `unlink`, and `rmdir` shims with the
shim directory first on PATH. The composite script walks hook → add →
trash/ledger → list/show → collision-safe restore → controlled purge.

## Independent frozen-gate captures

The matrix maps every P1–P5 acceptance check to a command and artifact. In
addition to scripts 01–03, the artifacts include the targeted P2/P3/P5
unittest recipes, the P4 focused fail-closed/probe suite, and the final full
suite. The full suite at the same product/replay SHAs ran 94 tests and returned
exit 0.

The timer row verifies the exact documented invocation
`0 2 * * * /usr/bin/safe-delete purge --execute --yes --json`; it does not
install cron/systemd because scheduler installation is operator-owned by the
freeze.

## Evidence status and limits

All matrix rows have an actual command, observed result, UTC interval, and
stable redacted artifact. This is an `EVIDENCE READY` proposal for disposer
review, not `PHASE ACCEPT`; merge of the evidence PR is not Phase PASS.

Restore-related evidence carries the required note:

> **Exception #12 — P2-only same-UID staging publication — excluded model / residual risk; not a product-contract fail.**

The hook evidence proves only the configured PreToolUse and PATH-shim client
boundaries. The bypass inventory is intentionally reported as out of coverage;
it does not claim interception of language filesystem APIs, `find -delete`,
`git clean`, absolute deletion binaries, unconfigured agents, no-hook
namespaces, privileged/human processes, PATH reordering, or disabled/uninstalled
integrations.

See [`matrix.md`](matrix.md), [`hooks.md`](hooks.md), and
[`artifacts/README.md`](artifacts/README.md) for the row-level records and
redaction rules.
