"""MediaWiki API client for oldschool.runescape.wiki."""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from bs4 import BeautifulSoup

from ..display import Results
from ..errors import OSRSError
from ..validation import integer, string
from .models import WIKI_URL, PageInfo, SearchHit, WikiPage

if TYPE_CHECKING:
    from ..client import Client


def _text(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text()


class Wiki:
    """Search and read oldschool.runescape.wiki."""

    def __init__(self, client: "Client") -> None:
        self._client = client

    def __repr__(self) -> str:
        return "Wiki()"

    def _api(self, params: dict[str, Any]) -> dict[str, Any]:
        result = self._client.get_json(f"{WIKI_URL}/api.php", {"format": "json", "formatversion": 2, **params})
        if not isinstance(result, dict):
            raise OSRSError("Invalid MediaWiki response: expected a JSON object")
        error = result.get("error")
        if error is not None:
            if isinstance(error, dict):
                detail = error.get("info", error.get("text", "Unknown API error"))
                raise OSRSError(f"MediaWiki API error ({error.get('code', 'unknown')}): {detail}")
            raise OSRSError(f"MediaWiki API error: {error}")
        if result.get("errors"):
            raise OSRSError(f"MediaWiki API errors: {result['errors']}")
        return result

    def search(self, query: str, limit: int = 10, offset: int = 0) -> Results[SearchHit]:
        """Full-text search; ``limit`` is 1-50."""
        string(query, "query")
        integer(limit, "limit", maximum=50)
        integer(offset, "offset", minimum=0)
        found = self._api({
            "action": "query", "list": "search", "srsearch": query,
            "srlimit": limit, "sroffset": offset, "srprop": "snippet|sectiontitle",
        }).get("query", {})
        hits = [
            SearchHit(hit["title"], _text(hit.get("snippet", "")), hit.get("sectiontitle", ""))
            for hit in found.get("search", [])
        ]
        return Results(hits, found.get("searchinfo", {}).get("totalhits", len(hits)), query)

    def page(self, title: str) -> WikiPage:
        """Fetch a page by title, following redirects (``"Marks of grace"`` works)."""
        string(title, "title")
        parsed = self._api({"action": "parse", "page": title, "prop": "text|revid", "redirects": 1}).get("parse")
        if not isinstance(parsed, dict) or not isinstance(parsed.get("text"), str):
            raise OSRSError(f"Wiki page content not found: {title}")
        return WikiPage(parsed.get("title", title), parsed["text"], parsed.get("pageid", 0), parsed.get("revid", 0))

    def info(self, *titles: str) -> list[PageInfo]:
        """Metadata for one or more titles, in request order, without fetching content."""
        if not titles:
            raise ValueError("info() needs at least one title")
        for title in titles:
            string(title, "title")
        pages = self._api({"action": "query", "prop": "info", "titles": "|".join(titles)}).get("query", {})
        by_title = {}
        for page in pages.get("pages", []):
            touched = page.get("touched")
            by_title[page.get("title")] = PageInfo(
                page.get("title", ""), not page.get("missing", False) and not page.get("invalid", False),
                page.get("pageid", 0), page.get("lastrevid", 0), page.get("length", 0),
                datetime.fromisoformat(touched.replace("Z", "+00:00")) if touched else None,
                bool(page.get("redirect", False)),
            )
        # MediaWiki normalizes titles ("abyssal_whip" -> "Abyssal whip"); map them back.
        renamed = {entry["from"]: entry["to"] for entry in pages.get("normalized", [])}
        return [by_title.get(renamed.get(title, title)) or PageInfo(title, False) for title in titles]
