"""Old School RuneScape data: Wiki, Grand Exchange, hiscores and game definitions.

>>> from seers import wiki, ge, hiscores, data
>>> wiki.page("Abyssal whip")
>>> ge.price("Abyssal whip").high
>>> hiscores.lookup("Lynx Titan").skills["attack"].level
>>> data.items.get(4151)

The ``wiki``, ``ge``, ``hiscores`` and ``data`` modules share one default
``Client``. Create your own ``Client`` for custom HTTP or data settings.
"""

from . import data, ge, hiscores, wiki
from .client import Client, configure, default_client
from .data import DataUpdateError, DataUpdater, Definition, DefinitionFile, Definitions
from .display import Results
from .errors import OSRSError, PlayerNotFoundError
from .ge import GrandExchange, Item, Price, PriceHistory, PricePoint
from .hiscores import Activity, Hiscores, Player, Skill, Stats
from .version import __version__
from .wiki import PageInfo, SearchHit, Wiki, WikiPage

__all__ = [
    "wiki", "ge", "hiscores", "data",
    "Client", "configure", "default_client",
    "Wiki", "WikiPage", "PageInfo", "SearchHit",
    "GrandExchange", "Item", "Price", "PriceHistory", "PricePoint",
    "Hiscores", "Player", "Stats", "Skill", "Activity",
    "Definitions", "DefinitionFile", "Definition", "DataUpdater", "DataUpdateError",
    "OSRSError", "PlayerNotFoundError", "Results", "__version__",
]
