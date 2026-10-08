"""Rank Agility courses by marks of grace and XP: python examples/agility_marks.py."""

import re

from rich import box
from rich.bar import Bar
from rich.console import Console
from rich.table import Table
from rich.text import Text

from seers import wiki

# Score = marks/h + XP/h / XP_PER_MARK, so one mark is worth 20k XP/h.
XP_PER_MARK = 20_000
CURRENCIES = {"Agility Arena Store": "Brimhaven vouchers", "Worm Tongue's Wares": "termites"}
AMYLASE = ("Colossal", "Brimhaven")  # Marks come from selling amylase packs, not course drops.
MEDALS = {1: "bold #ffd700", 2: "bold #c0c0c0", 3: "bold #cd7f32"}


def numbers(text: str) -> list[float]:
    return [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def key(name: str, level: str) -> tuple[int, str]:
    # The two pages name courses differently ("Basic Shayzien Agility Course" vs
    # "Shayzien Basic Course"), but level plus first distinctive word is unique.
    word = next(w for w in name.lower().split() if w not in ("basic", "advanced"))
    return int(level), word


def courses() -> list[dict]:
    xp = {}
    for row in wiki.page("Agility").table("Experience per hour")[1:]:
        level, _, name, category, rate, *_ = row
        if "Colossal" in name:  # One page title covers both courses.
            name = f"{name} ({'Advanced' if category == 'Advanced Course' else 'Basic'})"
        xp[key(name, level)] = (name, numbers(rate)[0])

    result = []
    # Rows with fewer cells are diary-boosted variants of the row above; keep base rates.
    for name, level, marks in (r for r in wiki.page("Mark of Grace").table("Marks/h")[1:] if len(r) == 3):
        course, rate = xp[key(name, level)]
        low, high = (numbers(marks) * 2)[:2]
        mid = (low + high) / 2
        result.append(
            {"name": course, "level": int(level), "low": low, "high": high,
             "xp": rate, "score": mid + rate / XP_PER_MARK}
        )
    return sorted(result, key=lambda c: c["score"], reverse=True)


def amylase() -> tuple[float, list[tuple[str, float]]]:
    """Return Grace's buy-back price and each currency shop's pack price."""
    rows = {r[0]: r for r in wiki.page("Amylase pack").table("Price bought at")[1:]}
    grace = numbers(rows["Grace's Graceful Clothing"][5])[0]
    return grace, [(shop, numbers(rows[shop][4])[0]) for shop in CURRENCIES]


def best_by_level(ranked: list[dict]) -> list[tuple[int, int, str]]:
    bands: list[tuple[int, int, str]] = []
    for level in range(1, 100):
        best = next(c["name"] for c in ranked if c["level"] <= level)
        if bands and bands[-1][2] == best:
            bands[-1] = (bands[-1][0], level, best)
        else:
            bands.append((level, level, best))
    return bands


def main() -> None:
    console = Console()
    with console.status("Reading the OSRS Wiki…"):
        ranked = courses()
        grace, shops = amylase()

    max_marks = max(c["high"] for c in ranked)
    max_xp = max(c["xp"] for c in ranked)
    table = Table(
        title="\nAgility courses ranked by marks of grace, then XP\n",
        title_style="bold green",
        title_justify="left",
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="bright_black",
        row_styles=["", "on #1a1a1a"],
    )
    table.add_column("#", justify="right")
    table.add_column("Course")
    table.add_column("Lvl", justify="right", style="cyan")
    table.add_column("Marks/hr", justify="right", style="bold green")
    table.add_column("", width=12)
    table.add_column("XP/hr", justify="right", style="bold blue")
    table.add_column("", width=12)
    table.add_column("Score", justify="right")
    for rank, c in enumerate(ranked, 1):
        name = Text(c["name"], style=MEDALS.get(rank, ""))
        if c["name"].startswith(AMYLASE):
            name.append(" ◆", style="magenta")
        marks = f"{c['low']:g}–{c['high']:g}" if c["high"] != c["low"] else f"{c['low']:g}"
        table.add_row(
            Text(str(rank), style=MEDALS.get(rank, "dim")),
            name,
            str(c["level"]),
            marks,
            Bar(max_marks, 0, (c["low"] + c["high"]) / 2, color="green", bgcolor="#2a2a2a"),
            f"{c['xp'] / 1000:g}k",
            Bar(max_xp, 0, c["xp"], color="blue", bgcolor="#2a2a2a"),
            Text(f"{c['score']:.2f}", style=MEDALS.get(rank, "bold")),
        )
    # Everything below shares the main table's width instead of the terminal's.
    width = min(console.width, console.measure(table).maximum)
    console.print(table, width=width)

    def section(title: str) -> Table:
        return Table(title=title, title_style="bold green", title_justify="left",
                     box=box.SIMPLE_HEAD, header_style="bold cyan")

    packs = section(f"[magenta]◆[/] Amylase packs sold to Grace for {grace:g} marks")
    packs.add_column("Shop")
    packs.add_column("Pack price", justify="right")
    packs.add_column("Per mark", justify="right", style="bold green")
    for shop, price in shops:
        packs.add_row(shop, f"{price:g} {CURRENCIES[shop]}", f"{price / grace:g}")

    bands = section("Best course by Agility level")
    bands.add_column("Agility", justify="right", style="cyan")
    bands.add_column("Course")
    for low, high, name in best_by_level(ranked):
        bands.add_row(f"{low}–{high}", name)

    # Side by side when they fit, stacked otherwise.
    unbounded = console.options.update_width(10_000)
    side = Table.grid(padding=(0, 2))
    side.add_row(packs, bands)
    if console.measure(side, options=unbounded).maximum <= width:
        console.print(side, width=width)
    else:
        console.print(packs, bands, width=width)

    console.print()
    for note in (
        f"Score = marks/hr + XP/hr ÷ [bold]{XP_PER_MARK:,}[/]. Base rates, no achievement diaries.",
        "[magenta]◆[/] Marks come from buying amylase packs and selling them to Grace.",
        "Mark rates are [bold]80% lower[/] at 20+ levels above a course's requirement (except Canifis).",
        "XP/hr is the wiki's perfect-lap maximum; expect slightly less.",
    ):
        console.print(f"  • {note}", width=width)


if __name__ == "__main__":
    main()
