"""Wiki pages, page metadata and search hits."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from urllib.parse import quote

from bs4 import BeautifulSoup, Tag
from rich.console import Console, ConsoleOptions, RenderResult
from rich.constrain import Constrain

from seers.display import RichDisplay
from seers.validation import validate_int
from seers.wiki.render import (
    WIKI_URL,
    clean_article,
    page_markdown,
    page_url,
    pager_styles,
    render_page,
)

__all__ = ["WIKI_URL", "PageInfo", "SearchHit", "WikiPage", "page_url"]


@dataclass(frozen=True)
class SearchHit:
    title: str
    snippet: str
    section: str = ""

    @property
    def url(self) -> str:
        anchor = f"#{quote(self.section.replace(' ', '_'))}" if self.section else ""
        return page_url(self.title) + anchor


@dataclass(frozen=True)
class PageInfo:
    """Page metadata without article content. ``exists`` is False for missing titles."""

    title: str
    exists: bool
    page_id: int = 0
    revision_id: int = 0
    length: int = 0
    touched: datetime | None = None
    redirect: bool = False

    @property
    def url(self) -> str:
        return page_url(self.title)


@dataclass(frozen=True)
class WikiPage(RichDisplay):
    """A parsed Wiki article with HTML, Markdown, plain text, tables and Rich view."""

    title: str
    html: str = field(repr=False)
    page_id: int = 0
    revision_id: int = 0

    @property
    def url(self) -> str:
        return page_url(self.title)

    @cached_property
    def soup(self) -> Tag:
        """Article body cleaned of navigation, scripts and edit links."""
        return clean_article(self.html)

    @property
    def markdown(self) -> str:
        return page_markdown(self.html)

    @property
    def text(self) -> str:
        return self.soup.get_text("\n", strip=True)

    @cached_property
    def tables(self) -> list[list[list[str]]]:
        """Every table as rows of cell text (footnotes stripped)."""
        soup = BeautifulSoup(self.html, "html.parser")
        for footnote in soup.select("sup"):
            footnote.decompose()
        return [
            [
                [cell.get_text(" ", strip=True) for cell in row.select("th, td")]
                for row in table_tag.select("tr")
            ]
            for table_tag in soup.select("table")
        ]

    def table(self, containing: str) -> list[list[str]]:
        """Return the first table whose text contains ``containing``."""
        for rows in self.tables:
            if any(containing in " ".join(row) for row in rows):
                return rows
        raise KeyError(f"No table containing {containing!r} on {self.title}")

    def show(
        self,
        *,
        pager: bool = False,
        width: int = 100,
        console: Console | None = None,
    ) -> None:
        """Print the formatted page to a Rich console, optionally through a pager."""
        validate_int(width, "width")
        output = console or Console()
        effective_width = min(width, output.width)
        renderable = Constrain(render_page(self.html, self.title, effective_width), effective_width)
        if pager:
            with output.pager(styles=pager_styles(output)):
                output.print(renderable)
        else:
            output.print(renderable)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        width = min(100, options.max_width)
        yield Constrain(render_page(self.html, self.title, width), width)
