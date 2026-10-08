"""``seers-data``: download the latest game definitions from OpenRS2."""

import argparse
from pathlib import Path

from .updater import DEFAULT_SOURCE_URL, DataUpdater, DataUpdateError


def main(argv: list[str] | None = None) -> int:
    """Rich standalone updater for ``seers-data`` and ``python -m seers.data.fetch.cli``."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    parser = argparse.ArgumentParser(description="Update OSRS internal-name data from OpenRS2")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--cache-id", type=int, help="Pin an OpenRS2 cache ID")
    parser.add_argument("--max-age", type=float, default=86400, help="Fresh-cache lifetime in seconds")
    parser.add_argument("--force", action="store_true")
    arguments = parser.parse_args(argv)
    console = Console()
    try:
        updater = DataUpdater(arguments.cache_dir, source_url=arguments.source_url, cache_id=arguments.cache_id)
        updater.update(force=arguments.force, max_age=arguments.max_age)
        status = updater.status()
    except (DataUpdateError, ValueError) as error:
        console.print(Text(str(error), style="bold red"))
        return 1
    summary = Text()
    for label, key in (("Source", "source"), ("Version", "version"), ("Updated (UTC)", "updated_at"), ("Snapshot", "path")):
        summary.append(f"{label}: ", style="bold cyan")
        summary.append(f"{status[key]}\n")
    console.print(Panel(summary, title="OSRS data snapshot", border_style="cyan"))
    table = Table("Mapping", "Records", title="Complete name mappings")
    for filename, rows in status["rows"].items():
        table.add_row(filename, f"{rows:,}")
    console.print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
