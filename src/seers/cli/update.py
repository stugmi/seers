"""``seers-update``: download the latest game cache names from OpenRS2.

Run as ``seers-update`` or ``python -m seers.cli.update``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from seers.data.updater import DEFAULT_SOURCE_URL, CacheUpdateError, CacheUpdater


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Update the game cache names from OpenRS2")
    parser.add_argument("--cache-dir", type=Path, help="Where to store cache.db")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--cache-id", type=int, help="Pin an OpenRS2 cache ID")
    parser.add_argument("--max-age", type=float, default=86400, help="Skip if newer (seconds)")
    parser.add_argument("--force", action="store_true", help="Download even if fresh")
    args = parser.parse_args(argv)

    try:
        updater = CacheUpdater(args.cache_dir, source_url=args.source_url, cache_id=args.cache_id)
        updater.update(force=args.force, max_age=args.max_age)
        status = updater.status()
        if status is None:
            raise CacheUpdateError(f"No snapshot in {updater.cache_dir}")
    except (CacheUpdateError, ValueError) as error:
        Console(stderr=True).print(f"Update failed: {error}", style="bold red", markup=False)
        raise SystemExit(1) from error

    summary = Text()
    for label, value in (
        ("Source", status.source),
        ("Version", status.version),
        ("Updated (UTC)", status.updated_at),
        ("Snapshot", str(status.path)),
    ):
        summary.append(f"{label}: ", style="bold cyan")
        summary.append(f"{value}\n")

    console = Console()
    console.print(Panel(summary, title="OSRS cache snapshot", border_style="cyan"))
    table = Table("Table", "Entries", title="Name tables")
    for name, rows in status.rows.items():
        table.add_row(name, f"{rows:,}")
    console.print(table)


if __name__ == "__main__":
    main()
