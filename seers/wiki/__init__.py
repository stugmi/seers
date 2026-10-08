"""The Old School RuneScape Wiki.

>>> from seers import wiki
>>> wiki.page("Abyssal whip").table("Combat stats")
>>> wiki.search("dragon scimitar", limit=5)

These functions use the default client; ``Client().wiki`` has the same methods.
"""

from ..display import Results
from .api import Wiki
from .models import PageInfo, SearchHit, WikiPage

__all__ = ["page", "search", "info", "Wiki", "WikiPage", "PageInfo", "SearchHit"]


def _wiki() -> Wiki:
    from ..client import default_client
    return default_client().wiki


def page(title: str) -> WikiPage:
    """Fetch a page by title, following redirects."""
    return _wiki().page(title)


def search(query: str, limit: int = 10, offset: int = 0) -> Results[SearchHit]:
    """Full-text search; ``limit`` is 1-50."""
    return _wiki().search(query, limit, offset)


def info(*titles: str) -> list[PageInfo]:
    """Metadata for one or more titles, without fetching content."""
    return _wiki().info(*titles)
