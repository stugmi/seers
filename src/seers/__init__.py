"""Old School RuneScape data: Wiki, Grand Exchange, hiscores and game cache names.

>>> from seers import wiki, ge, hiscores, data
>>> wiki.page("Abyssal whip")
>>> ge.price("Abyssal whip").high
>>> hiscores.lookup("Lynx Titan").skills["attack"].level
>>> data.items.get(4151)

The ``wiki``, ``ge``, ``hiscores`` and ``data`` modules share one default
``Client``. Create your own ``Client`` for custom HTTP or cache settings, or an
``AsyncClient`` to ``await`` the same calls under asyncio or trio.
"""

from importlib.metadata import version

__version__ = version("seers")

from seers import data, ge, hiscores, wiki
from seers.client import REPOSITORY, USER_AGENT, AsyncClient, Client, configure, default_client
from seers.data import Cache, CacheStatus, CacheUpdateError, CacheUpdater, Entry, Kind
from seers.display import Results
from seers.errors import OSRSError, PlayerNotFoundError
from seers.ge import (
    AsyncGrandExchange,
    GrandExchange,
    Item,
    Price,
    PriceHistory,
    PricePoint,
    Timestep,
)
from seers.hiscores import Activity, AsyncHiscores, Hiscores, Mode, Player, Skill, Stats
from seers.wiki import AsyncWiki, PageInfo, SearchHit, Wiki, WikiPage

__all__ = [
    "__version__",
    "REPOSITORY",
    "USER_AGENT",
    "wiki",
    "ge",
    "hiscores",
    "data",
    "Client",
    "AsyncClient",
    "configure",
    "default_client",
    "Wiki",
    "AsyncWiki",
    "WikiPage",
    "PageInfo",
    "SearchHit",
    "GrandExchange",
    "AsyncGrandExchange",
    "Item",
    "Price",
    "PriceHistory",
    "PricePoint",
    "Timestep",
    "Hiscores",
    "AsyncHiscores",
    "Player",
    "Stats",
    "Skill",
    "Activity",
    "Mode",
    "Cache",
    "CacheStatus",
    "CacheUpdater",
    "CacheUpdateError",
    "Entry",
    "Kind",
    "OSRSError",
    "PlayerNotFoundError",
    "Results",
]
