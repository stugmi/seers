"""The Old School RuneScape Wiki.

>>> from seers import wiki
>>> wiki.page("Abyssal whip").table("Combat stats")
>>> wiki.search("dragon scimitar", limit=5)

These functions use the default client; ``Client().wiki`` exposes the same methods and
``AsyncClient().wiki`` awaitable versions of them.
"""

from seers import client as _client
from seers.display import Results
from seers.wiki.api import AsyncWiki, Wiki
from seers.wiki.models import PageInfo, SearchHit, WikiPage

__all__ = [
    "AsyncWiki",
    "PageInfo",
    "SearchHit",
    "Wiki",
    "WikiPage",
    "info",
    "page",
    "search",
]


def page(title: str) -> WikiPage:
    """Fetch a page by title, following redirects."""
    return _client.default_client().wiki.page(title)


def search(query: str, limit: int = 10, offset: int = 0) -> Results[SearchHit]:
    """Full-text search; ``limit`` is 1..50."""
    return _client.default_client().wiki.search(query, limit, offset)


def info(*titles: str) -> list[PageInfo]:
    """Metadata for one or more titles, without fetching content."""
    return _client.default_client().wiki.info(*titles)
