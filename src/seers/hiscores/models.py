"""Hiscores stats, skills, activities and players."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from seers._compat import StrEnum
from seers.display import RichDisplay, format_cell, make_table

# The official API does not distinguish bosses from other activities.
BOSSES: frozenset[str] = frozenset(
    {
        "Abyssal Sire",
        "Alchemical Hydra",
        "Amoxliatl",
        "Araxxor",
        "Artio",
        "Barrows Chests",
        "Brutus",
        "Bryophyta",
        "Callisto",
        "Calvar'ion",
        "Cerberus",
        "Chambers of Xeric",
        "Chambers of Xeric: Challenge Mode",
        "Chaos Elemental",
        "Chaos Fanatic",
        "Commander Zilyana",
        "Corporeal Beast",
        "Crazy Archaeologist",
        "Dagannoth Prime",
        "Dagannoth Rex",
        "Dagannoth Supreme",
        "Deranged Archaeologist",
        "Doom of Mokhaiotl",
        "Duke Sucellus",
        "General Graardor",
        "Giant Mole",
        "Grotesque Guardians",
        "Hespori",
        "Kalphite Queen",
        "King Black Dragon",
        "Kraken",
        "Kree'Arra",
        "K'ril Tsutsaroth",
        "Lunar Chests",
        "Mimic",
        "Nex",
        "Nightmare",
        "Obor",
        "Phantom Muspah",
        "Phosani's Nightmare",
        "Sarachnis",
        "Scorpia",
        "Scurrius",
        "Shellbane Gryphon",
        "Skotizo",
        "Sol Heredit",
        "Spindel",
        "Tempoross",
        "The Corrupted Gauntlet",
        "The Gauntlet",
        "The Hueycoatl",
        "The Leviathan",
        "The Royal Titans",
        "The Whisperer",
        "Theatre of Blood",
        "Theatre of Blood: Hard Mode",
        "Thermonuclear Smoke Devil",
        "Tombs of Amascut",
        "Tombs of Amascut: Expert Mode",
        "TzKal-Zuk",
        "TzTok-Jad",
        "Vardorvis",
        "Venenatis",
        "Vet'ion",
        "Vorkath",
        "Wintertodt",
        "Yama",
        "Zalcano",
        "Zulrah",
    }
)


class Mode(StrEnum):
    MAIN = ("main", "")
    IRONMAN = ("ironman", "_ironman")
    HARDCORE = ("hardcore", "_hardcore_ironman")
    ULTIMATE = ("ultimate", "_ultimate")
    DEADMAN = ("deadman", "_deadman")
    SEASONAL = ("seasonal", "_seasonal")

    suffix: str

    def __new__(cls, value: str, suffix: str = "") -> Mode:
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.suffix = suffix
        return obj


@dataclass(frozen=True)
class Skill:
    name: str
    rank: int
    level: int
    xp: int

    @property
    def ranked(self) -> bool:
        return self.rank > 0


@dataclass(frozen=True)
class Activity:
    name: str
    rank: int
    score: int

    @property
    def ranked(self) -> bool:
        return self.rank > 0


def _format_rank(rank: int) -> Text:
    return format_cell(rank) if rank > 0 else Text("-", style="dim")


def _activity_table(title: str, activities: list[Activity]) -> Table:
    result = make_table(title)
    result.add_column("Name")
    result.add_column("Score", justify="right", style="bold green")
    result.add_column("Rank", justify="right", style="dim")
    for activity in activities:
        result.add_row(Text(activity.name), format_cell(activity.score), _format_rank(activity.rank))
    return result


@dataclass(frozen=True)
class Stats(RichDisplay):
    """One hiscores table. Unranked entries have rank, xp or score ``-1``.

    ``skills`` and ``activities`` are keyed by snake_case name, e.g.
    ``stats.skills["attack"].level`` or ``stats.bosses["vorkath"].score``.
    """

    player: str
    mode: Mode
    skills: dict[str, Skill]
    activities: dict[str, Activity]

    @property
    def overall(self) -> Skill:
        return self.skills["overall"]

    @property
    def total_level(self) -> int:
        return self.overall.level

    @property
    def total_xp(self) -> int:
        return self.overall.xp

    @property
    def bosses(self) -> dict[str, Activity]:
        return {k: a for k, a in self.activities.items() if a.name in BOSSES}

    @property
    def clues(self) -> dict[str, Activity]:
        return {k: a for k, a in self.activities.items() if k.startswith("clue_scrolls")}

    def __rich__(self) -> Group:
        skills_table = make_table(f"{self.player} ({self.mode})")
        skills_table.add_column("Skill")
        skills_table.add_column("Level", justify="right", style="bold cyan")
        skills_table.add_column("XP", justify="right", style="bold green")
        skills_table.add_column("Rank", justify="right", style="dim")
        for skill in self.skills.values():
            skills_table.add_row(
                Text(skill.name),
                format_cell(skill.level),
                format_cell(max(skill.xp, 0)),
                _format_rank(skill.rank),
            )

        bosses = self.bosses
        clues = self.clues
        ranked = [a for a in self.activities.values() if a.ranked]
        parts: list[RenderableType] = [skills_table]

        sections = (
            ("Bosses", [a for a in ranked if a.name in BOSSES]),
            ("Clue scrolls", [a for a in clues.values() if a.ranked]),
            (
                "Activities",
                [a for k, a in self.activities.items() if a.ranked and k not in bosses and k not in clues],
            ),
        )
        for title, entries in sections:
            if entries:
                parts.append(_activity_table(title, entries))
        return Group(*parts)


@dataclass(frozen=True)
class Player(RichDisplay):
    """A player's detected account type and stats across every table they appear on."""

    name: str
    mode: Mode
    stats: dict[str, Stats]
    deironed: bool = False
    hardcore_died: bool = False
    deulted: bool = False

    @property
    def current(self) -> Stats:
        return self.stats[self.mode]

    @property
    def skills(self) -> dict[str, Skill]:
        return self.current.skills

    @property
    def activities(self) -> dict[str, Activity]:
        return self.current.activities

    @property
    def bosses(self) -> dict[str, Activity]:
        return self.current.bosses

    @property
    def clues(self) -> dict[str, Activity]:
        return self.current.clues

    @property
    def total_level(self) -> int:
        return self.current.total_level

    def __rich__(self) -> Group:
        flags = [
            label
            for label, active in (
                ("de-ironed", self.deironed),
                ("hardcore died", self.hardcore_died),
                ("de-ulted", self.deulted),
            )
            if active
        ]
        header = Text(f"{self.name}: {self.mode}", style="bold")
        if flags:
            header.append(f" ({', '.join(flags)})", style="dim")
        return Group(header, self.current)
