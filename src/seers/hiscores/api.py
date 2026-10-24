"""The official Old School hiscores, as ``Hiscores`` (sync) and ``AsyncHiscores``."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from seers._http import Call, get, get_json
from seers.errors import PlayerNotFoundError
from seers.hiscores.models import Mode, Player, Stats
from seers.hiscores.parse import parse_formatted_name, parse_stats
from seers.validation import validate_str

if TYPE_CHECKING:
    from seers.client import AsyncClient, Client

HISCORES_URL = "https://secure.runescape.com/m=hiscore_oldschool"
_VALID_NAME_RE = re.compile(r"[a-zA-Z0-9 _-]{1,12}")


def _validate_name(name: str) -> None:
    validate_str(name, "name")
    if not _VALID_NAME_RE.fullmatch(name):
        raise ValueError("name must be 1..12 letters, digits, spaces, underscores or hyphens")


def _table(name: str, mode: Mode) -> Call[Any]:
    return (yield from get_json(f"{HISCORES_URL}{mode.suffix}/index_lite.json", {"player": name}, player=name))


def _display_name(name: str, payload: Any) -> Call[str]:
    canonical = payload.get("name") if isinstance(payload, dict) else None
    if isinstance(canonical, str) and canonical:
        return canonical
    try:
        response = yield from get(f"{HISCORES_URL}/overall.ws", {"table": 0, "user": name}, player=name)
    except PlayerNotFoundError:
        return name
    return parse_formatted_name(response.text, name)


def _stats(name: str, mode: Mode | str) -> Call[Stats]:
    _validate_name(name)
    try:
        mode = Mode(mode)
    except ValueError:
        raise ValueError("mode must be main, ironman, hardcore, ultimate, deadman or seasonal") from None
    payload = yield from _table(name, mode)
    canonical = payload.get("name") if isinstance(payload, dict) else None
    return parse_stats(payload, canonical if isinstance(canonical, str) and canonical else name, mode)


def _lookup(name: str) -> Call[Player]:
    _validate_name(name)
    main_payload = yield from _table(name, Mode.MAIN)
    display = yield from _display_name(name, main_payload)
    tables: dict[str, Stats] = {"main": parse_stats(main_payload, display, Mode.MAIN)}

    for mode in (Mode.IRONMAN, Mode.HARDCORE, Mode.ULTIMATE):
        try:
            tables[mode.value] = parse_stats((yield from _table(name, mode)), display, mode)
        except PlayerNotFoundError:
            if mode is Mode.IRONMAN:
                break

    if "ironman" not in tables:
        return Player(name=display, mode=Mode.MAIN, stats=tables)

    xp = {mode: s.total_xp for mode, s in tables.items()}
    detected_mode = Mode.IRONMAN
    hardcore_died = False
    deulted = False

    if "hardcore" in tables:
        hardcore_died = xp["hardcore"] != xp["ironman"]
        detected_mode = Mode.IRONMAN if hardcore_died else Mode.HARDCORE
    elif "ultimate" in tables:
        deulted = xp["ultimate"] != xp["ironman"]
        detected_mode = Mode.IRONMAN if deulted else Mode.ULTIMATE

    deironed = xp["main"] != xp["ironman"]
    return Player(
        name=display,
        mode=Mode.MAIN if deironed else detected_mode,
        stats=tables,
        deironed=deironed,
        hardcore_died=hardcore_died,
        deulted=deulted,
    )


class Hiscores:
    """Player lookups on the official Old School hiscores."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def __repr__(self) -> str:
        return "Hiscores()"

    def stats(self, name: str, mode: Mode | str = Mode.MAIN) -> Stats:
        """Fetch one hiscores table without account-type detection."""
        return self._client._run(_stats(name, mode))

    def lookup(self, name: str) -> Player:
        """Look up every relevant table and detect the player's account type."""
        return self._client._run(_lookup(name))


class AsyncHiscores:
    """``Hiscores`` for ``AsyncClient``: the same methods, awaitable."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def __repr__(self) -> str:
        return "AsyncHiscores()"

    async def stats(self, name: str, mode: Mode | str = Mode.MAIN) -> Stats:
        """Fetch one hiscores table without account-type detection."""
        return await self._client._run(_stats(name, mode))

    async def lookup(self, name: str) -> Player:
        """Look up every relevant table and detect the player's account type."""
        return await self._client._run(_lookup(name))
