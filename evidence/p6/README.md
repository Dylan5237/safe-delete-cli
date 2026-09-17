# P6 full-path evidence scaffold

This directory is a replay scaffold for Phase 6. **This PR is scaffolding only:**
it is not `EVIDENCE READY`, it is not a Phase PASS proposal, and merge of this
PR is not Phase Accept. No captured result in this directory may be read as a
green gate until the named disposer reviews replay output and records the
required decision on Issue #8.

The scripts intentionally cover only routes landed on `main` at the base under
test (`0fa84844ce01f7df4fd68e94a607dd711f53369f`). P4 hook, PreToolUse, and
PATH-shim work remains blocked on [PR #18](https://github.com/Dylan5237/safe-delete-cli/pull/18),
tip `3c052912d3bc7fae84a9258ccae40c56ed32ff40`. No P4 implementation is copied
into this branch, and no hook script is run here.

## Use from a clean checkout

Run each route in a clean checkout of the branch/commit being examined. Every
script creates or uses a disposable `TESTROOT` and sets `SAFE_DELETE_ROOT`
under that test area unless the caller explicitly supplies both variables.
The scripts leave the disposable root available for inspection; remove that
explicit test directory after review if desired.

```bash
bash evidence/p6/scripts/00_env.sh
bash evidence/p6/scripts/01_cli_trash_restore.sh
bash evidence/p6/scripts/02_cli_metadata.sh
bash evidence/p6/scripts/03_cli_purge.sh
```

To make the test location stable for one replay, provide an explicit temporary
directory. Do not point it at a product or home-data root:

```bash
TESTROOT="$(mktemp -d /tmp/safe-delete-p6.XXXXXX)" \
  bash evidence/p6/scripts/01_cli_trash_restore.sh
```

Each script prints the resolved checkout, test root, SHA, UTC context, and JSON
command output. If output is captured for a later evidence pass, redact local
paths and unrelated environment details before placing it under
`evidence/p6/artifacts/`. The current artifact directory contains no captured
logs; `PENDING_CAPTURE` is intentional.

`03_cli_purge.sh` uses two explicit, product-supported controls: a short
`--older-than 1h` dry-run, followed by an explicit future `--before` cutoff for
the controlled execute boundary. The fresh active fixture is therefore made
eligible by the invocation's cutoff, while a restored fixture remains
excluded. This is a deterministic scaffold smoke path, not proof of the
default 30-day retention boundary, crash recovery, partial failure, or timer
behavior; those remain pending capture in the matrix.

## Evidence handoff boundary

- `matrix.md` is the acceptance-to-proof scaffold using the frozen nine
  columns. Rows without an actual capture are marked `PENDING_CAPTURE`.
- `hooks.md` records every hook-related row as `BLOCKED_PENDING_P4` with a
  `pending` result until PR #18 lands and is separately reviewed.
- Restore rows carry accepted Exception #12 as a coverage note. The scaffold
  does not claim same-UID staging isolation.
- The eventual disposer handoff, if and when all proof is captured, is a
  separate decision on Issue #8. This branch must not post `EVIDENCE READY`,
  `PHASE ACCEPT`, or claim Phase PASS.
