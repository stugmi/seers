"""``SeersMCP``: the library's read-only lookups as MCP tools with structured results."""

import argparse
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
import functools
import inspect
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver import Context, Resolve
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from seers import AsyncClient, __version__
from seers.data import CacheUpdateError, Entry, Kind
from seers.display import Results
from seers.errors import OSRSError
from seers.ge import Item, Price, PriceHistory, Timestep
from seers.hiscores import Activity, Mode, Skill, Stats
from seers.mcp.watchdog import watch_client
from seers.wiki import SearchHit

INSTRUCTIONS = """\
Old School RuneScape data.
- cache_search / cache_get: the game's internal IDs and debug names (items, NPCs, objects,
  animations, interfaces, varps, varbits, ...). Use these for exact IDs in code.
- wiki_search / wiki_page: OSRS Wiki articles for mechanics, quests, drop tables and guides.
- ge_search / ge_price / ge_history: Grand Exchange item IDs and live prices.
- player_lookup / player_stats: official hiscores.
"""

# Failures the model caused and can fix (unknown player, missing ID, bad argument) or that it
# should hear about (upstream down). Anything else is a bug: the SDK logs it and the model only
# learns that the call failed.
_EXPECTED_ERRORS = (OSRSError, CacheUpdateError, KeyError, ValueError, FileNotFoundError)

_F = TypeVar("_F", bound=Callable[..., Any])


def _message(error: Exception) -> str:
    # str(KeyError("x")) is "'x'"; show the message itself.
    return str(error.args[0]) if isinstance(error, KeyError) and error.args else str(error)


def _readable_errors(function: _F) -> _F:
    """Re-raise expected library errors as ``ToolError`` so the model reads the message."""
    if inspect.iscoroutinefunction(function):

        @functools.wraps(function)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await function(*args, **kwargs)
            except _EXPECTED_ERRORS as error:
                raise ToolError(_message(error)) from error

    else:

        @functools.wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return function(*args, **kwargs)
            except _EXPECTED_ERRORS as error:
                raise ToolError(_message(error)) from error

    return wrapper  # type: ignore[return-value]


_TOOLS: list[tuple[Callable[..., Any], ToolAnnotations, bool]] = []


def _tool(title: str, *, online: bool, structured: bool = True) -> Callable[[_F], _F]:
    """Declare a read-only tool. ``online`` marks tools that reach the internet."""

    def declare(function: _F) -> _F:
        annotations = ToolAnnotations(title=title, read_only_hint=True, open_world_hint=online)
        _TOOLS.append((_readable_errors(function), annotations, structured))
        return function

    return declare


def _seers(ctx: Context[AsyncClient]) -> AsyncClient:
    return ctx.request_context.lifespan_context


Seers = Annotated[AsyncClient, Resolve(_seers)]
"""The server's ``AsyncClient``, injected by the SDK and invisible to the model."""

Limit = Annotated[int, Field(ge=1, le=100, strict=True, description="Results per page.")]
WikiLimit = Annotated[int, Field(ge=1, le=50, strict=True, description="Results per page.")]
Offset = Annotated[int, Field(ge=0, strict=True, description="Results to skip, for paging.")]
CacheKind = Annotated[Kind, Field(description="Which name table to use.")]
ItemRef = Annotated[int | str, Field(description="Item ID or exact item name.")]
PlayerName = Annotated[str, Field(min_length=1, max_length=12, description="Hiscores display name.")]


# Game cache (offline, local file reads)


@_tool("Search cache names", online=False)
def cache_search(
    kind: CacheKind,
    query: Annotated[str, Field(description="Words or part of a debug name; spaces match underscores.")],
    seers: Seers,
    limit: Limit = 10,
    offset: Offset = 0,
) -> Results[Entry]:
    """Fuzzy-search the game's internal debug names.

    Kinds: items, npcs, locs (world objects), animations, spotanims, sounds, sprites,
    interfaces (id:component), inventories, varps, varbits, dbrows, dbtables (id:column).
    """
    return seers.data.table(kind).search(query, limit, offset)


@_tool("Get cache entry", online=False)
def cache_get(
    kind: CacheKind,
    id: Annotated[str, Field(description="Exact ID, e.g. 4151, or 149:0 for interfaces.")],
    seers: Seers,
) -> Entry:
    """The debug name for one exact ID, e.g. kind=items, id=4151."""
    return seers.data.table(kind).get(id)


# OSRS Wiki


@_tool("Search the OSRS Wiki", online=True)
async def wiki_search(
    query: Annotated[str, Field(min_length=1)],
    seers: Seers,
    limit: WikiLimit = 10,
    offset: Offset = 0,
) -> Results[SearchHit]:
    """Full-text search of the OSRS Wiki: titles, snippets and matching sections."""
    return await seers.wiki.search(query, limit, offset)


@_tool("Read an OSRS Wiki page", online=True, structured=False)
async def wiki_page(
    title: Annotated[str, Field(min_length=1, description="Page title; redirects are followed.")],
    seers: Seers,
) -> str:
    """An OSRS Wiki article as Markdown, tables included."""
    page = await seers.wiki.page(title)
    return f"# {page.title}\n{page.url}\n\n{page.markdown}"


# Grand Exchange


@_tool("Search Grand Exchange items", online=True)
async def ge_search(
    query: Annotated[str, Field(min_length=1)],
    seers: Seers,
    limit: Limit = 20,
    offset: Offset = 0,
) -> Results[Item]:
    """Tradeable items by name (exact, then prefix, then substring), with IDs and buy limits."""
    return await seers.ge.search(query, limit, offset)


@_tool("Grand Exchange price", online=True)
async def ge_price(item: ItemRef, seers: Seers) -> Price:
    """Latest instant-buy (high) and instant-sell (low) prices for an item."""
    return await seers.ge.price(item)


@_tool("Grand Exchange price history", online=True)
async def ge_history(item: ItemRef, seers: Seers, timestep: Timestep = Timestep.ONE_HOUR) -> PriceHistory:
    """Up to 365 averaged price points for an item at 5m, 1h, 6h or 24h steps."""
    return await seers.ge.history(item, timestep)


# Hiscores
#
# The library's Player keeps every table the player is on, each with all ~120 entries; most are
# unranked (-1). The model gets the table that matters, without the unranked noise.


@dataclass(frozen=True)
class Hiscore:
    """One hiscores table. Skills always listed; activities, bosses and clues only when ranked."""

    player: str
    mode: Mode
    skills: dict[str, Skill]
    activities: dict[str, Activity]

    @classmethod
    def of(cls, stats: Stats) -> "Hiscore":
        ranked = {key: activity for key, activity in stats.activities.items() if activity.ranked}
        return cls(stats.player, stats.mode, stats.skills, ranked)


@dataclass(frozen=True)
class Account(Hiscore):
    """The table for the player's detected account type, with how they left any iron mode."""

    deironed: bool = False
    hardcore_died: bool = False
    deulted: bool = False


@_tool("Look up a player", online=True)
async def player_lookup(name: PlayerName, seers: Seers) -> Account:
    """A player's skills and ranked bosses, clues and activities on their account type's table.

    ``mode`` is the detected account type (main, ironman, hardcore, ultimate).
    """
    player = await seers.hiscores.lookup(name)
    table = Hiscore.of(player.current)
    return Account(
        table.player,
        player.mode,
        table.skills,
        table.activities,
        deironed=player.deironed,
        hardcore_died=player.hardcore_died,
        deulted=player.deulted,
    )


@_tool("Player stats on one hiscores table", online=True)
async def player_stats(name: PlayerName, mode: Mode, seers: Seers) -> Hiscore:
    """One hiscores table for a player, e.g. mode=deadman, mode=seasonal or mode=main."""
    return Hiscore.of(await seers.hiscores.stats(name, mode))


class SeersMCP(MCPServer[AsyncClient]):
    """The seers tools on an ``MCPServer``.

    >>> SeersMCP().run()  # stdio

    Pass ``client`` to share your own ``AsyncClient``; its lifetime stays yours. Otherwise
    the server opens one with the given cache settings and closes it on shutdown.
    """

    def __init__(
        self,
        client: AsyncClient | None = None,
        *,
        cache_path: str | Path | None = None,
        cache_dir: str | Path | None = None,
        auto_update: bool = False,
        max_age: float = 86400,
        log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "WARNING",
    ) -> None:
        @asynccontextmanager
        async def lifespan(_server: MCPServer[AsyncClient]) -> AsyncIterator[AsyncClient]:
            if client is not None:
                yield client
                return
            async with AsyncClient(
                cache_path=cache_path,
                cache_dir=cache_dir,
                auto_update=auto_update,
                max_age=max_age,
            ) as owned:
                yield owned

        super().__init__(
            "seers",
            title="Seers",
            instructions=INSTRUCTIONS,
            version=__version__,
            lifespan=lifespan,
            log_level=log_level,  # INFO would log every upstream HTTP request
        )
        for function, annotations, structured in _TOOLS:
            self.add_tool(
                function,
                title=annotations.title,
                annotations=annotations,
                structured_output=structured,
            )


def main(argv: list[str] | None = None) -> None:
    """``seers-mcp`` / ``python -m seers.mcp``: serve the tools over stdio."""
    watch_client()
    parser = argparse.ArgumentParser(prog="seers-mcp", description="seers MCP server (stdio)")
    parser.add_argument("--cache-path", type=Path, help="Use your own cache.db or directory")
    parser.add_argument("--cache-dir", type=Path, help="Where downloaded snapshots are stored")
    parser.add_argument("--auto-update", action="store_true", help="Refresh the cache when it is read")
    parser.add_argument("--max-age", type=float, default=86400, help="Refresh interval in seconds")
    args = parser.parse_args(argv)
    if args.cache_path is not None and (args.auto_update or args.cache_dir is not None):
        parser.error("--cache-path cannot be combined with --auto-update or --cache-dir")
    SeersMCP(
        cache_path=args.cache_path,
        cache_dir=args.cache_dir,
        auto_update=args.auto_update,
        max_age=args.max_age,
    ).run()
