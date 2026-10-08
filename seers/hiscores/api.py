"""Client for the official Old School hiscores."""

import re
from typing import TYPE_CHECKING, Any, Literal

from ..errors import PlayerNotFoundError
from ..validation import string
from .models import Player, Stats
from .parse import parse_formatted_name, parse_stats

if TYPE_CHECKING:
    from ..client import Client


HISCORES_URL = "https://secure.runescape.com/m=hiscore_oldschool"
Mode = Literal["main", "ironman", "hardcore", "ultimate", "deadman", "seasonal"]
MODE_SUFFIXES = {
    "main": "",
    "ironman": "_ironman",
    "hardcore": "_hardcore_ironman",
    "ultimate": "_ultimate",
    "deadman": "_deadman",
    "seasonal": "_seasonal",
}
class Hiscores:
    """Player lookups on the official Old School hiscores."""

    def __init__(self, client: "Client") -> None:
        self._client = client

    def __repr__(self) -> str:
        return "Hiscores()"

    @staticmethod
    def _check_name(name: str) -> None:
        string(name, "name")
        if len(name) > 12 or not re.fullmatch(r"[a-zA-Z0-9 _-]+", name):
            raise ValueError("name must be 1..12 letters, digits, spaces, underscores or hyphens")

    def _payload(self, name: str, mode: str) -> Any:
        url = f"{HISCORES_URL}{MODE_SUFFIXES[mode]}/index_lite.json"
        return self._client.get_json(url, {"player": name}, player=name)

    def stats(self, name: str, mode: Mode = "main") -> Stats:
        """One hiscores table, without account-type detection."""
        self._check_name(name)
        if mode not in MODE_SUFFIXES:
            raise ValueError("mode must be main, ironman, hardcore, ultimate, deadman or seasonal")
        payload = self._payload(name, mode)
        canonical = payload.get("name") if isinstance(payload, dict) else None
        return parse_stats(payload, canonical if isinstance(canonical, str) and canonical else name, mode)

    def _display_name(self, name: str, payload: Any) -> str:
        canonical = payload.get("name") if isinstance(payload, dict) else None
        if isinstance(canonical, str) and canonical:
            return canonical
        try:
            response = self._client.get(f"{HISCORES_URL}/overall.ws", {"table": 0, "user": name}, player=name)
        except PlayerNotFoundError:
            return name
        return parse_formatted_name(response.text, name)

    def lookup(self, name: str) -> Player:
        """Look up every relevant table and detect the account type.

        A missing ironman table means the account was never an ironman; a
        missing hardcore or ultimate table is skipped. Outages still raise.
        """
        self._check_name(name)
        main = self._payload(name, "main")
        display = self._display_name(name, main)
        stats = {"main": parse_stats(main, display, "main")}
        for mode in ("ironman", "hardcore", "ultimate"):
            try:
                stats[mode] = parse_stats(self._payload(name, mode), display, mode)
            except PlayerNotFoundError:
                if mode == "ironman":
                    break

        if "ironman" not in stats:
            return Player(display, "main", stats)
        xp = {mode: s.total_xp for mode, s in stats.items()}
        mode, hardcore_died, deulted = "ironman", False, False
        if "hardcore" in stats:
            hardcore_died = xp["hardcore"] != xp["ironman"]
            mode = "ironman" if hardcore_died else "hardcore"
        elif "ultimate" in stats:
            deulted = xp["ultimate"] != xp["ironman"]
            mode = "ironman" if deulted else "ultimate"
        deironed = xp["main"] != xp["ironman"]
        return Player(display, "main" if deironed else mode, stats, deironed, hardcore_died, deulted)
