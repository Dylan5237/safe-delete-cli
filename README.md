# safe-delete-cli

`safe-delete` is a small, local Python CLI for moving files, directories, and
symlinks into a unified trash root with an append-only JSONL ledger. It uses
only the Python standard library; there are no runtime dependencies.

The executable is `./safe-delete`. Machine-readable invocations use `--json`.

## Storage root

The canonical default storage root is `~/.local/share/safe-delete`. Resolution
precedence, first match wins:

1. `--root DIR` (per invocation)
2. `$SAFE_DELETE_ROOT`
3. `$XDG_DATA_HOME/safe-delete`
4. `$HOME/.local/share/safe-delete`

The final path component is exactly `safe-delete`. A directory named with any
suffix added to that — a `-store` variant, for example — is **not** this
product's path. Different roots are different ledgers: entries added under one
root do not appear in `list` under another. `list --json` echoes the resolved
`root`; compare it before assuming data was lost.

`--root DIR` selects a test or project root.

## Platform

Linux, macOS, and WSL are supported. Native Windows Python is not: the storage
layer imports `fcntl` at import time, so the entry point preflights the platform
before that import and fails with one line on stderr instead of an import
traceback:

```console
$ python ./safe-delete version
unsupported platform: requires Linux/macOS/WSL (fcntl)
$ echo $?
2
```

That message means the wrong interpreter was used; run inside WSL with a POSIX
`python3`. It is a diagnosis, not a portability or coverage claim — nothing on
the native Windows side is covered. `safe-delete doctor --json` reports the same
facts as data under `platform_preflight`.

For WSL/Windows path forms (`/home/...`, `/mnt/c/...`, `\\wsl$\...`) and what is
actually covered, see [`docs/project/p7-agent-usage.md`](docs/project/p7-agent-usage.md).

## Purge

`safe-delete purge` previews eligible entries by default. Set
`SAFE_DELETE_RETENTION_DAYS` to a positive decimal integer, or use one of the
per-invocation overrides `--older-than Nd`/`--older-than Nh` (for example
`30d` or `720h`) and `--before RFC3339`. Physical removal requires both
`--execute` and `--yes`. Preview first and read `policy.source`, `policy.cutoff`,
and `candidates` before adding the confirmation flags.

`--before` also accepts the exact literal `now`, which resolves to the
invocation's own UTC clock — the "everything eligible right now" spelling. It is
sugar only: it never implies `--execute --yes`, and a report whose cutoff is not
in the past carries an explicit wipe-all `warning`. `--before` accepts a future
timestamp too, and a future cutoff likewise makes every active entry eligible —
that is wipe-all semantics, not a typo guard. See
[`docs/project/p7-agent-usage.md`](docs/project/p7-agent-usage.md) for the
three-step purge discipline.

## Doctor

`safe-delete doctor --json` is a read-only aggregate: platform preflight,
resolved storage root and usability, the same per-selector `hook status` entries
(each carrying its own `out_of_coverage` verbatim), the payload source of every
installed artifact, and the resolved CLI paths with a world-writable flag. It
never writes, creates, or repairs. `needs_attention: false` means "no problem
detected in the inspected surfaces" — it is not a coverage claim and not a
statement that deletion is safe.

## Hook install

`safe-delete hook install <claude|cursor|path-shim>` writes package-owned
payloads under the resolved data root and registers the selected boundary. On a
stock machine — no `SAFE_DELETE_ROOT`, no `XDG_DATA_HOME` — the package root and
the storage root are the same directory; that is supported, and only the runtime
namespaces (`trash/`, `ledger.jsonl`, `locks/`) are refused. Installing from a
second Cursor project without `--project`/`--config` fails closed rather than
silently reporting success against the first project. Counterexample C — the
payload is pinned to the checkout that installed it — is **not** fixed, but
install and `doctor` both warn about it. See
[`docs/project/p7-install-notes.md`](docs/project/p7-install-notes.md).

## Scheduled purge

Cron and systemd run with an environment that differs from your interactive
shell, so the root and the retention source can silently differ. Pin both
explicitly, and remember that `./safe-delete` is a launcher shipped alongside
the `safe_delete/` package: it must run from a stable checkout (or from any
stable path where `safe-delete` and `safe_delete/` sit together). A lone copy of
the script — for example `/usr/bin/safe-delete` by itself — will fail to import
`safe_delete`. Put the repository at its final stable location **before**
configuring the timer, since hooks installed from a moving checkout also pin
that path.

```cron
0 2 * * * SAFE_DELETE_ROOT=/home/you/.local/share/safe-delete /opt/safe-delete-cli/safe-delete purge --execute --yes --json
```

Installing the cron/systemd timer is the operator's responsibility; the CLI
does not install a scheduler.

## More

- [`docs/project/p7-agent-usage.md`](docs/project/p7-agent-usage.md) — agent
  usage, `--json` examples, purge discipline, and the bypass inventory.
- [`docs/project/p7-install-notes.md`](docs/project/p7-install-notes.md) — hook
  install fixes, remaining limits, and the read-only `doctor` surface.
- [`docs/project/p4-hook-coverage.md`](docs/project/p4-hook-coverage.md) — hook
  coverage replay map.
