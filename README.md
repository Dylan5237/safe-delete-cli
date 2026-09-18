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
layer imports `fcntl` at import time, so on a native Windows interpreter every
subcommand — including `version` — fails with
`ModuleNotFoundError: No module named 'fcntl'`. That message means the wrong
interpreter was used; run inside WSL with a POSIX `python3`.

For WSL/Windows path forms (`/home/...`, `/mnt/c/...`, `\\wsl$\...`) and what is
actually covered, see [`docs/project/p7-agent-usage.md`](docs/project/p7-agent-usage.md).

## Purge

`safe-delete purge` previews eligible entries by default. Set
`SAFE_DELETE_RETENTION_DAYS` to a positive decimal integer, or use one of the
per-invocation overrides `--older-than Nd`/`--older-than Nh` (for example
`30d` or `720h`) and `--before RFC3339`. Physical removal requires both
`--execute` and `--yes`. Preview first and read `policy.source`, `policy.cutoff`,
and `candidates` before adding the confirmation flags.

`--before` accepts a future timestamp, and a future cutoff makes every active
entry eligible — that is wipe-all semantics, not a typo guard. See
[`docs/project/p7-agent-usage.md`](docs/project/p7-agent-usage.md) for the
three-step purge discipline.

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
  install restrictions and known limits.
- [`docs/project/p4-hook-coverage.md`](docs/project/p4-hook-coverage.md) — hook
  coverage replay map.
