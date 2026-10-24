"""MediaWiki API for oldschool.runescape.wiki, as ``Wiki`` (sync) and ``AsyncWiki``."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from bs4 import BeautifulSoup

from seers._compat import fromisoformat
from seers._http import Call, get_json
from seers.display import Results
from seers.errors import OSRSError
from seers.validation import validate_int, validate_str
from seers.wiki.models import WIKI_URL, PageInfo, SearchHit, WikiPage

if TYPE_CHECKING:
    from seers.client import AsyncClient, Client


def _strip_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text()


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    return fromisoformat(value) if value else None


def _query(params: dict[str, Any]) -> Call[dict[str, Any]]:
    payload = yield from get_json(f"{WIKI_URL}/api.php", {"format": "json", "formatversion": 2, **params})
    if not isinstance(payload, dict):
        raise OSRSError("Invalid MediaWiki response: expected a JSON object")

    error = payload.get("error")
    if error is not None:
        if isinstance(error, dict):
            code = error.get("code", "unknown")
            detail = error.get("info") or error.get("text") or "Unknown API error"
            raise OSRSError(f"MediaWiki API error ({code}): {detail}")
        raise OSRSError(f"MediaWiki API error: {error}")

    if payload.get("errors"):
        raise OSRSError(f"MediaWiki API errors: {payload['errors']}")
    return payload


def _search(query: str, limit: int, offset: int) -> Call[Results[SearchHit]]:
    validate_str(query, "query")
    validate_int(limit, "limit", max_value=50)
    validate_int(offset, "offset", min_value=0)

    payload = yield from _query(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "sroffset": offset,
            "srprop": "snippet|sectiontitle",
        }
    )
    found = payload.get("query", {})
    hits = [
        SearchHit(
            title=hit["title"],
            snippet=_strip_html(hit.get("snippet", "")),
            section=hit.get("sectiontitle", ""),
        )
        for hit in found.get("search", [])
    ]
    total = found.get("searchinfo", {}).get("totalhits", len(hits))
    return Results(hits, total, query)


def _page(title: str) -> Call[WikiPage]:
    validate_str(title, "title")
    payload = yield from _query({"action": "parse", "page": title, "prop": "text|revid", "redirects": 1})
    parsed = payload.get("parse")
    if not isinstance(parsed, dict) or not isinstance(parsed.get("text"), str):
        raise OSRSError(f"Wiki page content not found: {title}")
    return WikiPage(
        title=parsed.get("title", title),
        html=parsed["text"],
        page_id=parsed.get("pageid", 0),
        revision_id=parsed.get("revid", 0),
    )


def _info(titles: tuple[str, ...]) -> Call[list[PageInfo]]:
    if not titles:
        raise ValueError("info() requires at least one title")
    for title in titles:
        validate_str(title, "title")

    payload = yield from _query({"action": "query", "prop": "info", "titles": "|".join(titles)})
    query_data = payload.get("query", {})

    by_title: dict[str, PageInfo] = {}
    for page in query_data.get("pages", []):
        canonical_title = page.get("title", "")
        exists = not page.get("missing", False) and not page.get("invalid", False)
        by_title[canonical_title] = PageInfo(
            title=canonical_title,
            exists=exists,
            page_id=page.get("pageid", 0),
            revision_id=page.get("lastrevid", 0),
            length=page.get("length", 0),
            touched=_parse_iso_timestamp(page.get("touched")),
            redirect=bool(page.get("redirect", False)),
        )

    normalized = {entry["from"]: entry["to"] for entry in query_data.get("normalized", [])}
    return [
        by_title.get(normalized.get(title, title)) or PageInfo(title=title, exists=False)
        for title in titles
    ]


class Wiki:
    """Search and read oldschool.runescape.wiki."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def __repr__(self) -> str:
        return "Wiki()"

    def search(self, query: str, limit: int = 10, offset: int = 0) -> Results[SearchHit]:
        """Full-text search; ``limit`` is 1..50."""
        return self._client._run(_search(query, limit, offset))

    def page(self, title: str) -> WikiPage:
        """Fetch a page by title, following redirects."""
        return self._client._run(_page(title))

    def info(self, *titles: str) -> list[PageInfo]:
        """Fetch metadata for one or more titles in request order without content."""
        return self._client._run(_info(titles))


class AsyncWiki:
    """``Wiki`` for ``AsyncClient``: the same methods, awaitable."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def __repr__(self) -> str:
        return "AsyncWiki()"

    async def search(self, query: str, limit: int = 10, offset: int = 0) -> Results[SearchHit]:
        """Full-text search; ``limit`` is 1..50."""
        return await self._client._run(_search(query, limit, offset))

    async def page(self, title: str) -> WikiPage:
        """Fetch a page by title, following redirects."""
        return await self._client._run(_page(title))

    async def info(self, *titles: str) -> list[PageInfo]:
        """Fetch metadata for one or more titles in request order without content."""
        return await self._client._run(_info(titles))
