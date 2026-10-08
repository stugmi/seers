"""Parsing of the official hiscores JSON and HTML."""

from html.parser import HTMLParser
import re
from typing import Any

from ..errors import OSRSError
from .models import Activity, Skill, Stats


def key(name: str) -> str:
    """``"K'ril Tsutsaroth"`` -> ``"kril_tsutsaroth"``, ``"Clue Scrolls (all)"`` -> ``"clue_scrolls_all"``."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower().replace("'", "")).strip("_")


def _int(record: dict[str, Any], field: str) -> int:
    value = record.get(field)
    if value is None:
        return -1
    if isinstance(value, bool) or not isinstance(value, int):
        raise OSRSError(f"Invalid hiscores {field}: expected an integer")
    return value


def _records(value: Any, category: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(
        not isinstance(record, dict) or not isinstance(record.get("name"), str) for record in value
    ):
        raise OSRSError(f"Invalid hiscores {category}: expected named JSON records")
    return value


def parse_stats(payload: Any, player: str, mode: str) -> Stats:
    """Parse ``index_lite.json`` by name, never by unstable numeric IDs."""
    if not isinstance(payload, dict):
        raise OSRSError("Invalid hiscores JSON: expected an object")
    skills = {
        key(r["name"]): Skill(r["name"], _int(r, "rank"), _int(r, "level"), _int(r, "xp"))
        for r in _records(payload.get("skills"), "skills")
    }
    if "overall" not in skills:
        raise OSRSError("Invalid hiscores skills: missing Overall")
    activities = {
        key(r["name"]): Activity(r["name"], _int(r, "rank"), _int(r, "score"))
        for r in _records(payload.get("activities"), "activities")
    }
    return Stats(player, mode, skills, activities)


class _HighlightedRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_row = False
        self.rows: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            classes = set((dict(attrs).get("class") or "").split())
            self.in_row = {"personal-hiscores__row", "personal-hiscores__row--type-highlight"} <= classes
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.in_row:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self.in_row:
            self.rows.append("".join(self.parts))
            self.in_row = False


def parse_formatted_name(html: str, player: str) -> str:
    """Read the original capitalization and separators, else return ``player``."""
    parser = _HighlightedRowParser()
    parser.feed(html)
    parser.close()
    pattern = r"[ _\- ]".join(re.escape(part) for part in re.split(r"[ _-]", player))
    for row in parser.rows:
        match = re.search(pattern, row, re.IGNORECASE)
        if match:
            return match.group(0).replace(" ", " ")
    return player
