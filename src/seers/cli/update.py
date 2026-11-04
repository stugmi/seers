"""``seers-update``: download the latest game cache names from OpenRS2.

Run as ``seers-update`` or ``python -m seers.cli.update``.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from rich.box import SIMPLE_HEAD
from rich.console import Console
from rich.table import Table
from rich.text import Text

from seers.data.updater import DEFAULT_SOURCE_URL, CacheStatus, CacheUpdateError, CacheUpdater


def _parse(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)


def _ago(timestamp: str) -> str:
    seconds = max(0, int((datetime.now(timezone.utc) - _parse(timestamp)).total_seconds()))
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return "just now"


def _size(path: Path) -> str:
    size = float(path.stat().st_size)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _delta(change: int) -> Text:
    if change == 0:
        return Text("=", style="dim")
    return Text(f"{change:+,}", style="green" if change > 0 else "red")


def _headline(status: CacheStatus, before: CacheStatus | None, refreshed: bool) -> str:
    if refreshed and before is None:
        return f"[bold green]Downloaded[/] the OSRS name cache: [bold]{status.version}[/]"
    if refreshed and before.version == status.version and before.rows == status.rows:
        return f"[bold green]Re-downloaded[/] [bold]{status.version}[/]: nothing changed"
    if refreshed:
        return f"[bold green]Updated[/] the OSRS name cache: [bold]{before.version}[/] -> [bold]{status.version}[/]"
    return (
        f"[bold green]Up to date[/]: [bold]{status.version}[/], "
        f"updated {_ago(status.updated_at)}; [dim]--force downloads again[/]"
    )


def _report(console: Console, headline: str, status: CacheStatus, before: CacheStatus | None) -> None:
    console.print(headline)
    console.print()

    cache = status.cache
    builds = ", ".join(
        str(build["major"]) if build.get("minor") is None else f"{build['major']}.{build['minor']}"
        for build in cache.get("builds", [])
    )
    details = [
        ("Game build", builds or "unknown"),
        ("Cache taken", f"{_parse(cache['timestamp']):%Y-%m-%d %H:%M} UTC ({_ago(cache['timestamp'])})")
        if cache.get("timestamp") else None,
        ("OpenRS2", f"#{cache['id']}, {', '.join(cache.get('sources', [])) or 'unknown source'}"),
        ("Names", f"{sum(status.rows.values()):,} in {len(status.rows)} tables"),
        ("Snapshot", f"{status.path} ({_size(status.path)})"),
        ("Source", status.source),
    ]
    for line in details:
        if line is not None:
            console.print(f"[cyan]{line[0]:<12}[/]", line[1], highlight=False)
    console.print()

    compare = before is not None
    table = Table(box=SIMPLE_HEAD, pad_edge=False, header_style="bold cyan")
    table.add_column("Table")
    table.add_column("Entries", justify="right")
    if compare:
        table.add_column("Change", justify="right")
    for name, rows in status.rows.items():
        cells: list[str | Text] = [name, f"{rows:,}"]
        if compare:
            cells.append(_delta(rows - before.rows.get(name, 0)))
        table.add_row(*cells)
    console.print(table)


def _check(console: Console, updater: CacheUpdater) -> None:
    """Compare the local snapshot with upstream without changing anything."""
    status = updater.status()
    if status is None:
        console.print(
            f"[bold yellow]No downloaded snapshot[/] in {updater.cache_dir}; "
            "the bundled cache is in use. [dim]Run seers-update to download one.[/]"
        )
        return
    if updater.has_update():
        headline = (
            f"[bold yellow]Update available[/]: you have [bold]{status.version}[/], "
            "upstream has a newer cache. [dim]Run seers-update.[/]"
        )
    else:
        headline = (
            f"[bold green]Up to date[/] with upstream: [bold]{status.version}[/], "
            f"last synced {_ago(status.updated_at)}"
        )
    _report(console, headline, status, None)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Update the game cache names from OpenRS2")
    parser.add_argument("--cache-dir", type=Path, help="Where to store cache.db")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--cache-id", type=int, help="Pin an OpenRS2 cache ID")
    parser.add_argument("--max-age", type=float, default=86400, help="Skip if newer (seconds)")
    parser.add_argument("--force", action="store_true", help="Download even if fresh")
    parser.add_argument("--check", action="store_true", help="Only report the current snapshot and whether upstream has a newer one")
    args = parser.parse_args(argv)
    if args.check and args.force:
        parser.error("--check cannot be combined with --force")

    try:
        updater = CacheUpdater(args.cache_dir, source_url=args.source_url, cache_id=args.cache_id)
        if args.check:
            _check(Console(), updater)
            return
        try:
            before = updater.status()
        except CacheUpdateError:
            before = None  # unreadable old snapshot: --force still replaces it
        updater.update(force=args.force, max_age=args.max_age)
        status = updater.status()
        if status is None:
            raise CacheUpdateError(f"No snapshot in {updater.cache_dir}")
    except (CacheUpdateError, ValueError) as error:
        Console(stderr=True).print(f"Update failed: {error}", style="bold red", markup=False)
        raise SystemExit(1) from error

    refreshed = before is None or before.updated_at != status.updated_at
    _report(Console(), _headline(status, before, refreshed), status, before if refreshed else None)


if __name__ == "__main__":
    main()
