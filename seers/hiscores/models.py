"""Hiscores stats, skills, activities and players."""

from dataclasses import dataclass
from typing import Any

from rich.console import Group
from rich.table import Table
from rich.text import Text

from ..display import RichDisplay, cell, table


# The API does not say which activities are bosses; new bosses stay in ``activities``.
BOSSES = frozenset({
    "Abyssal Sire", "Alchemical Hydra", "Amoxliatl", "Araxxor", "Artio", "Barrows Chests",
    "Brutus", "Bryophyta", "Callisto", "Calvar'ion", "Cerberus", "Chambers of Xeric",
    "Chambers of Xeric: Challenge Mode", "Chaos Elemental", "Chaos Fanatic", "Commander Zilyana",
    "Corporeal Beast", "Crazy Archaeologist", "Dagannoth Prime", "Dagannoth Rex",
    "Dagannoth Supreme", "Deranged Archaeologist", "Doom of Mokhaiotl", "Duke Sucellus",
    "General Graardor", "Giant Mole", "Grotesque Guardians", "Hespori", "Kalphite Queen",
    "King Black Dragon", "Kraken", "Kree'Arra", "K'ril Tsutsaroth", "Lunar Chests", "Mimic",
    "Nex", "Nightmare", "Phosani's Nightmare", "Obor", "Phantom Muspah", "Sarachnis", "Scorpia",
    "Scurrius", "Shellbane Gryphon", "Skotizo", "Sol Heredit", "Spindel", "Tempoross",
    "The Gauntlet", "The Corrupted Gauntlet", "The Hueycoatl", "The Leviathan",
    "The Royal Titans", "The Whisperer", "Theatre of Blood", "Theatre of Blood: Hard Mode",
    "Thermonuclear Smoke Devil", "Tombs of Amascut", "Tombs of Amascut: Expert Mode",
    "TzKal-Zuk", "TzTok-Jad", "Vardorvis", "Venenatis", "Vet'ion", "Vorkath", "Wintertodt",
    "Yama", "Zalcano", "Zulrah",
})


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


def _rank(rank: int) -> Text:
    return cell(rank) if rank > 0 else Text("-", style="dim")


def _activity_table(title: str, activities: list[Activity]) -> Table:
    result = table(title)
    result.add_column("Name")
    result.add_column("Score", justify="right", style="bold green")
    result.add_column("Rank", justify="right", style="dim")
    for activity in activities:
        result.add_row(Text(activity.name), cell(activity.score), _rank(activity.rank))
    return result


@dataclass(frozen=True)
class Stats(RichDisplay):
    """One hiscores table. Unranked entries have rank, xp or score -1.

    ``skills`` and ``activities`` are keyed by snake_case name, e.g.
    ``stats.skills["attack"].level`` or ``stats.bosses["vorkath"].score``.
    """

    player: str
    mode: str
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
        skills = table(f"{self.player} ({self.mode})")
        skills.add_column("Skill")
        skills.add_column("Level", justify="right", style="bold cyan")
        skills.add_column("XP", justify="right", style="bold green")
        skills.add_column("Rank", justify="right", style="dim")
        for skill in self.skills.values():
            skills.add_row(Text(skill.name), cell(skill.level), cell(max(skill.xp, 0)), _rank(skill.rank))
        bosses, clues = self.bosses, self.clues
        ranked = [a for a in self.activities.values() if a.ranked]
        parts: list[Any] = [skills]
        for title, entries in (
            ("Bosses", [a for a in ranked if a.name in BOSSES]),
            ("Clue scrolls", [a for k, a in clues.items() if a.ranked]),
            ("Activities", [a for k, a in self.activities.items()
                            if a.ranked and k not in bosses and k not in clues]),
        ):
            if entries:
                parts.append(_activity_table(title, entries))
        return Group(*parts)


@dataclass(frozen=True)
class Player(RichDisplay):
    """A player's detected account type and the stats of every table they appear on.

    ``skills``, ``bosses`` and friends read from the table for ``mode``.
    """

    name: str
    mode: str
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
        flags = [label for label, flag in (("de-ironed", self.deironed), ("hardcore died", self.hardcore_died),
                                           ("de-ulted", self.deulted)) if flag]
        header = Text(f"{self.name}: {self.mode}", style="bold")
        if flags:
            header.append(f" ({', '.join(flags)})", style="dim")
        return Group(header, self.current)
