# safe-delete-cli

`safe-delete` is a small, local Python CLI for moving files, directories, and
symlinks into a unified trash root with an append-only JSONL ledger. Phase 2
uses only the Python standard library; it has no runtime dependencies.

The executable is `./safe-delete`. Storage defaults to
`$SAFE_DELETE_ROOT`, then `$XDG_DATA_HOME/safe-delete`, then
`$HOME/.local/share/safe-delete`; pass `--root DIR` to select a test or
project root. Machine-readable invocations use `--json`.

