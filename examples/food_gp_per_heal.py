"""Cheapest GP per heal single-bite foods healing 20-22: examples/food_gp_per_heal.py [-n N | --all]."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from rich import box
from rich.bar import Bar
from rich.console import Console
from rich.table import Table
from rich.text import Text

from seers import wiki

MIN_HEAL, MAX_HEAL, DEFAULT_LIMIT = 20, 100, 25
MEDALS = {1: "bold #ffd700", 2: "bold #c0c0c0", 3: "bold #cd7f32"}
# Only plain numbers are single-eat foods. "2 × 4" (four bites), "12 + 9" (two stages),
# ranges, "Random" and percentages all need several eats or have no fixed heal, so they are skipped.


@dataclass(frozen=True, slots=True)
class Food:
    name: str
    heals: int
    price: int
    gp_per_heal: float
    members: bool


def single_eat(heal: str) -> bool:
    return heal.isdigit() and MIN_HEAL <= int(heal) <= MAX_HEAL


def foods(limit: int | None = DEFAULT_LIMIT) -> list[Food]:
    """Return qualifying foods, cheapest first; ``limit=None`` keeps them all."""
    result: list[Food] = []
    for _, name, heal, _, _, gp_per_heal, price, members in wiki.page("Food/All food").table("GP per heal")[1:]:
        if not single_eat(heal) or gp_per_heal == "N/A":
            continue  # N/A means the wiki has no Grand Exchange price for it.
        result.append(
            Food(
                name=name,
                heals=int(heal),
                price=int(price.replace(",", "")),
                gp_per_heal=float(gp_per_heal.replace(",", "")),
                members=members == "1",
            )
        )
    return sorted(result, key=lambda f: (f.gp_per_heal, f.name))[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-n", "--limit", type=int, default=DEFAULT_LIMIT, metavar="N",
                       help=f"number of foods to show (default {DEFAULT_LIMIT})")
    group.add_argument("--all", action="store_true", help="show every qualifying food")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    console = Console()
    with console.status("Reading the OSRS Wiki…"):
        ranked = foods(None if args.all else args.limit)

    worst = max(f.gp_per_heal for f in ranked)
    heading = "All" if args.all else "Top"
    table = Table(
        title=f"\n{heading} {len(ranked)} single-eat foods healing {MIN_HEAL}-{MAX_HEAL} by GP per heal, cheapest first\n",
        title_style="bold green",
        title_justify="left",
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="bright_black",
        row_styles=["", "on #1a1a1a"],
    )
    table.add_column("#", justify="right")
    table.add_column("Food")
    table.add_column("Heals", justify="right", style="cyan")
    table.add_column("GE price", justify="right")
    table.add_column("GP/heal", justify="right", style="bold green")
    table.add_column("", width=12)
    for rank, f in enumerate(ranked, 1):
        name = Text(f.name, style=MEDALS.get(rank, ""))
        if f.members:
            name.append(" ◆", style="magenta")
        table.add_row(
            Text(str(rank), style=MEDALS.get(rank, "dim")),
            name,
            str(f.heals),
            f"{f.price:,}",
            f"{f.gp_per_heal:,.2f}",
            Bar(worst, 0, f.gp_per_heal, color="green", bgcolor="#2a2a2a"),
        )
    width = min(console.width, console.measure(table).maximum)
    console.print(table, width=width)

    console.print()
    for note in (
        "[magenta]◆[/] Members only.",
        "Prices and GP/heal come from the wiki's All food table; foods without a GE price are skipped.",
        "Foods that take several bites or stages (pies, pizzas, 12 + 9 …) are excluded.",
    ):
        console.print(f"  • {note}", width=width)


if __name__ == "__main__":
    main()
