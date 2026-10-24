"""Grand Exchange items and prices.

>>> from seers import ge
>>> ge.price("Abyssal whip").high
>>> ge.history(4151, "24h")
>>> ge.search("dragon", limit=10)

Items can be an ID, an exact (case-insensitive) name, or an ``Item``. These functions
use the default client; ``Client().ge`` exposes the same methods and ``AsyncClient().ge``
awaitable versions of them.
"""

from typing import TYPE_CHECKING, Any

from seers import client as _client
from seers.display import Results
from seers.ge.api import AsyncGrandExchange, GrandExchange
from seers.ge.models import Item, Price, PriceHistory, PricePoint, Timestep

if TYPE_CHECKING:
    items: list[Item]

__all__ = [
    "AsyncGrandExchange",
    "GrandExchange",
    "Item",
    "Price",
    "PriceHistory",
    "PricePoint",
    "Timestep",
    "history",
    "item",
    "items",
    "price",
    "refresh",
    "search",
]


def search(query: str, limit: int = 20, offset: int = 0) -> Results[Item]:
    return _client.default_client().ge.search(query, limit, offset)


def item(item: int | str | Item) -> Item:
    """Look up an item by ID or exact name."""
    return _client.default_client().ge.item(item)


def price(item: int | str | Item) -> Price:
    """Latest instant-buy (high) and instant-sell (low) prices."""
    return _client.default_client().ge.price(item)


def history(item: int | str | Item, timestep: Timestep | str = Timestep.ONE_HOUR) -> PriceHistory:
    """Up to 365 averaged price points at 5m, 1h, 6h or 24h steps."""
    return _client.default_client().ge.history(item, timestep)


def refresh() -> None:
    """Forget the cached item list."""
    _client.default_client().ge.refresh()


def __getattr__(name: str) -> Any:
    if name == "items":
        return _client.default_client().ge.items
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
