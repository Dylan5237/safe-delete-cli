# safe-delete-cli

`safe-delete` is a small, local Python CLI for moving files, directories, and
symlinks into a unified trash root with an append-only JSONL ledger. Phase 2
uses only the Python standard library; it has no runtime dependencies.

The executable is `./safe-delete`. Storage defaults to
`$SAFE_DELETE_ROOT`, then `$XDG_DATA_HOME/safe-delete`, then
`$HOME/.local/share/safe-delete`; pass `--root DIR` to select a test or
project root. Machine-readable invocations use `--json`.

`safe-delete purge` previews eligible entries by default. Set
`SAFE_DELETE_RETENTION_DAYS` to a positive decimal integer, or use one of the
per-invocation overrides `--older-than Nd`/`--older-than Nh` (for example
`30d` or `720h`) and `--before RFC3339`. Physical removal requires both
`--execute` and `--yes`:

```cron
0 2 * * * /usr/bin/safe-delete purge --execute --yes --json
```

Installing the cron/systemd timer is the operator's responsibility; the CLI
does not install a scheduler.
