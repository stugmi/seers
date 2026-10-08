"""Grand Exchange items and prices.

>>> from seers import ge
>>> ge.price("Abyssal whip").high
>>> ge.history(4151, "24h")
>>> ge.search("dragon", limit=10)

Items can be an ID, an exact (case-insensitive) name, or an ``Item``. These
functions use the default client; ``Client().ge`` has the same methods.
"""

from typing import TYPE_CHECKING

from ..display import Results
from .api import GrandExchange, Timestep
from .models import Item, Price, PriceHistory, PricePoint

if TYPE_CHECKING:
    items: list[Item]

__all__ = ["search", "item", "price", "history", "refresh", "items",
           "GrandExchange", "Item", "Price", "PriceHistory", "PricePoint"]


def _ge() -> GrandExchange:
    from ..client import default_client
    return default_client().ge


def search(query: str, limit: int = 20, offset: int = 0) -> Results[Item]:
    """Exact name matches first, then prefixes, then substrings."""
    return _ge().search(query, limit, offset)


def item(item: int | str | Item) -> Item:
    """Look up an item by ID or exact name."""
    return _ge().item(item)


def price(item: int | str | Item) -> Price:
    """Latest instant-buy (high) and instant-sell (low) prices."""
    return _ge().price(item)


def history(item: int | str | Item, timestep: Timestep = "1h") -> PriceHistory:
    """Up to 365 averaged price points at 5m, 1h, 6h or 24h steps."""
    return _ge().history(item, timestep)


def refresh() -> None:
    """Forget the cached item list."""
    _ge().refresh()


def __getattr__(name: str):
    if name == "items":
        return _ge().items
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
