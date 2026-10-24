"""Parsing of official hiscores JSON and HTML."""

from __future__ import annotations

from html.parser import HTMLParser
import re
from typing import Any

from seers.errors import OSRSError
from seers.hiscores.models import Activity, Mode, Skill, Stats

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_NAME_SPLIT_RE = re.compile(r"[ _-]")


def normalize_key(name: str) -> str:
    """Convert a display name to snake_case (e.g. ``"K'ril Tsutsaroth"`` -> ``"kril_tsutsaroth"``)."""
    return _NON_ALNUM_RE.sub("_", name.lower().replace("'", "")).strip("_")


def _parse_int(record: dict[str, Any], field: str) -> int:
    value = record.get(field)
    if value is None:
        return -1
    if isinstance(value, bool) or not isinstance(value, int):
        raise OSRSError(f"Invalid hiscores {field}: expected an integer")
    return value


def _validate_records(value: Any, category: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(
        not isinstance(record, dict) or not isinstance(record.get("name"), str)
        for record in value
    ):
        raise OSRSError(f"Invalid hiscores {category}: expected named JSON records")
    return value


def parse_stats(payload: Any, player: str, mode: Mode | str) -> Stats:
    """Parse ``index_lite.json`` records by name."""
    if not isinstance(payload, dict):
        raise OSRSError("Invalid hiscores JSON: expected an object")

    mode_enum = mode if isinstance(mode, Mode) else Mode(mode)

    skills = {
        normalize_key(r["name"]): Skill(
            name=r["name"],
            rank=_parse_int(r, "rank"),
            level=_parse_int(r, "level"),
            xp=_parse_int(r, "xp"),
        )
        for r in _validate_records(payload.get("skills"), "skills")
    }
    if "overall" not in skills:
        raise OSRSError("Invalid hiscores skills: missing Overall")

    activities = {
        normalize_key(r["name"]): Activity(
            name=r["name"],
            rank=_parse_int(r, "rank"),
            score=_parse_int(r, "score"),
        )
        for r in _validate_records(payload.get("activities"), "activities")
    }
    return Stats(player=player, mode=mode_enum, skills=skills, activities=activities)


class _HighlightedRowParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_row = False
        self.rows: list[str] = []
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            classes = set((dict(attrs).get("class") or "").split())
            self.in_row = {
                "personal-hiscores__row",
                "personal-hiscores__row--type-highlight",
            } <= classes
            self._parts.clear()

    def handle_data(self, data: str) -> None:
        if self.in_row:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self.in_row:
            self.rows.append("".join(self._parts))
            self.in_row = False


def parse_formatted_name(html: str, player: str) -> str:
    """Extract the canonical capitalization and separators from the HTML table, or return ``player``."""
    parser = _HighlightedRowParser()
    parser.feed(html)
    parser.close()
    pattern = r"[ _\-\xa0]".join(re.escape(part) for part in _NAME_SPLIT_RE.split(player))
    for row in parser.rows:
        if match := re.search(pattern, row, re.IGNORECASE):
            return match.group(0).replace("\xa0", " ")
    return player
