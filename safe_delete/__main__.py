"""Module entry point: platform preflight, then the CLI.

The preflight deliberately runs *before* ``safe_delete.cli`` is imported, because
``safe_delete.storage`` imports ``fcntl`` at module import time.
"""

from __future__ import annotations

from collections.abc import Sequence

from .platform_check import preflight


def main(argv: Sequence[str] | None = None) -> int:
    blocked = preflight(argv)
    if blocked is not None:
        return blocked
    from .cli import main as cli_main  # imported only once the platform is proven

    return cli_main(list(argv) if argv is not None else None)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
