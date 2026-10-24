"""Rich rendering of Wiki article HTML."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import os
import re
from urllib.parse import quote

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from markdownify import markdownify
from rich import box
from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

WIKI_URL = "https://oldschool.runescape.wiki"

_CLUTTER_SELECTOR = (
    "script, style, img, .mw-editsection, #toc, .toc, .navbox, "
    ".metadata, .noprint, .mw-empty-elt, sup.reference"
)
_HEADING_RE = re.compile(r"^h([1-6])$")


def page_url(title: str) -> str:
    return f"{WIKI_URL}/w/" + quote(title.replace(" ", "_"), safe="")


def clean_article(html: str) -> Tag:
    """Parse HTML and strip Wiki navigation, scripts, styles, images and edit chrome."""
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one(".mw-parser-output") or soup
    for comment in article.find_all(string=lambda node: isinstance(node, Comment)):
        comment.extract()
    for image in article.select("img"):
        cell = image.find_parent(["th", "td"])
        if cell is not None and not cell.get_text(strip=True):
            cell["data-osrs-icon-only"] = "1"
    for element in article.select(_CLUTTER_SELECTOR):
        element.decompose()
    return article


def _to_markdown(html: str) -> str:
    return markdownify(
        html,
        heading_style="ATX",
        strip=["a"],
        table_infer_header=True,
    ).strip()


def page_markdown(html: str) -> str:
    """Convert article HTML to clean Markdown."""
    return _to_markdown(str(clean_article(html)))


@dataclass(eq=False, slots=True)
class _Cell:
    markdown: str
    plain: str
    header: bool
    html: str
    icon_only: bool


def _span(cell: Tag, attribute: str) -> int:
    try:
        return max(1, int(cell.get(attribute, 1)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1


def _flatten_nested_table(copy: BeautifulSoup, nested: Tag) -> Tag:
    rows = _table_rows(nested)
    labels, body = _table_parts(rows)
    replacement = copy.new_tag("div")

    caption = nested.find("caption", recursive=False)
    if isinstance(caption, Tag):
        caption_tag = copy.new_tag("p")
        caption_tag.string = caption.get_text(" ", strip=True)
        replacement.append(caption_tag)

    for row in body:
        seen: set[int] = set()
        for value in row:
            if value is None or id(value) in seen:
                continue
            seen.add(id(value))
            entry = copy.new_tag("div")
            names = list(
                dict.fromkeys(
                    labels[idx]
                    for idx, current in enumerate(row)
                    if current is value and labels[idx]
                )
            )
            if names:
                label = copy.new_tag("strong")
                label.string = " / ".join(names) + ": "
                entry.append(label)
            fragment = BeautifulSoup(value.html, "html.parser")
            for child in list(fragment.contents):
                entry.append(child.extract())
            replacement.append(entry)

    if not body:
        replacement.string = " / ".join(label for label in labels if label)
    return replacement


def _parse_cell(cell: Tag) -> _Cell:
    copy = BeautifulSoup(str(cell), "html.parser")
    top_nested = [t for t in copy.find_all("table") if t.find_parent("table") is None]
    for nested in top_nested:
        nested.replace_with(_flatten_nested_table(copy, nested))

    content = copy.find(cell.name)
    html = content.decode_contents() if isinstance(content, Tag) else ""
    plain = content.get_text(" ", strip=True) if isinstance(content, Tag) else ""
    icon_only = bool(
        _span(cell, "colspan") == 1
        and (
            cell.get("data-osrs-icon-only")
            or (cell.find("img") is not None and not cell.get_text(strip=True))
        )
    )
    return _Cell(_to_markdown(html), plain, cell.name == "th", html, icon_only)


def _table_rows(table: Tag) -> list[list[_Cell | None]]:
    rows: list[list[_Cell | None]] = []
    source_rows = [row for row in table.find_all("tr") if row.find_parent("table") is table]

    for row_index, tr in enumerate(source_rows):
        while len(rows) <= row_index:
            rows.append([])
        column = 0
        for tag in tr.find_all(["th", "td"], recursive=False):
            while column < len(rows[row_index]) and rows[row_index][column] is not None:
                column += 1
            value = _parse_cell(tag)
            colspan = _span(tag, "colspan")
            group_remaining = 1
            for following in source_rows[row_index + 1 :]:
                if following.parent is not tr.parent:
                    break
                group_remaining += 1
            rowspan = (
                group_remaining
                if str(tag.get("rowspan")) == "0"
                else min(_span(tag, "rowspan"), group_remaining)
            )
            for target_row in range(row_index, row_index + rowspan):
                while len(rows) <= target_row:
                    rows.append([])
                needed = column + colspan - len(rows[target_row])
                if needed > 0:
                    rows[target_row].extend([None] * needed)
                for target_column in range(column, column + colspan):
                    rows[target_row][target_column] = value
            column += colspan

    col_count = max((len(row) for row in rows), default=0)
    for row in rows:
        row.extend([None] * (col_count - len(row)))

    keep_columns = [
        col
        for col in range(col_count)
        if (cells := [row[col] for row in rows if row[col] is not None])
        and any(c.plain for c in cells)
        and not (
            any(c.icon_only for c in cells)
            and not any(c.plain for c in cells if not c.header)
        )
    ]
    return [
        [row[col] for col in keep_columns]
        for row in rows
        if any(cell and cell.plain for cell in row)
    ]


def _table_parts(rows: list[list[_Cell | None]]) -> tuple[list[str], list[list[_Cell | None]]]:
    col_count = len(rows[0]) if rows else 0
    headers: list[list[_Cell | None]] = []
    for row in rows:
        cells = [cell for cell in row if cell is not None]
        if not cells or not all(cell.header for cell in cells):
            break
        headers.append(row)

    labels: list[str] = []
    for col in range(col_count):
        parts: list[str] = []
        previous: _Cell | None = None
        for row in headers:
            cell = row[col]
            if cell is not None and cell is not previous and cell.plain:
                parts.append(cell.plain)
            previous = cell
        labels.append(" / ".join(parts))
    return labels, rows[len(headers) :]


def _render_compact_rows(labels: list[str], rows: list[list[_Cell | None]], width: int) -> Group:
    panels: list[RenderableType] = []
    for row in rows:
        entries: list[tuple[str, str]] = []
        seen: set[int] = set()
        for index, cell in enumerate(row):
            if cell is None or id(cell) in seen or not cell.plain:
                continue
            seen.add(id(cell))
            names = list(
                dict.fromkeys(
                    labels[col]
                    for col, value in enumerate(row)
                    if value is cell and labels[col]
                )
            )
            label = " / ".join(names) or f"Column {index + 1}"
            entries.append((label, cell.markdown))
        if not entries:
            continue

        if width < 32:
            content: RenderableType = Group(
                *(Group(Text(label, style="bold cyan"), Markdown(value)) for label, value in entries)
            )
        else:
            grid = Table.grid(padding=(0, 1), expand=True)
            grid.add_column(style="bold cyan", width=min(24, max(8, width // 3)))
            grid.add_column(ratio=1, overflow="fold")
            for label, value in entries:
                grid.add_row(Text(label), Markdown(value))
            content = grid
        panels.append(Panel(content, border_style="dim cyan", padding=(0, 1)))
    return Group(*panels)


def _render_table(table: Tag, width: int, *, facts: bool = False) -> Group:
    rows = _table_rows(table)
    labels, body = _table_parts(rows)
    caption = table.find("caption", recursive=False)
    renderables: list[RenderableType] = (
        [Markdown(_to_markdown(str(caption)))] if caption else []
    )
    if not rows:
        return Group(*renderables)

    if facts:
        for row in rows[: len(rows) - len(body)]:
            seen: set[int] = set()
            for cell in row:
                if cell and id(cell) not in seen:
                    seen.add(id(cell))
                    renderables.append(Markdown(cell.markdown))
        for row in body:
            unique = list(dict.fromkeys(cell for cell in row if cell and cell.plain))
            if len(unique) == 2 and width >= 32:
                facts_grid = Table.grid(padding=(0, 1), expand=True)
                facts_grid.add_column(style="bold cyan", width=min(24, max(8, width // 3)))
                facts_grid.add_column(ratio=1, overflow="fold")
                facts_grid.add_row(Markdown(unique[0].markdown), Markdown(unique[1].markdown))
                renderables.append(facts_grid)
            else:
                renderables.append(Group(*(Markdown(cell.markdown) for cell in unique)))
        return Group(*renderables)

    col_count = len(labels)
    minimums = [
        min(
            24,
            max(
                8,
                max(
                    (
                        len(word)
                        for value in [label, *(r[idx].plain for r in body if r[idx] is not None)]
                        for word in value.split()
                    ),
                    default=1,
                ),
            ),
        )
        for idx, label in enumerate(labels)
    ]

    if sum(minimums) + 3 * col_count + 1 > width:
        if body:
            renderables.append(_render_compact_rows(labels, body, width))
        else:
            renderables.extend(Text(label, style="bold cyan") for label in labels if label)
    else:
        grid = Table(
            box=box.ROUNDED,
            border_style="cyan",
            header_style="bold cyan",
            show_header=any(labels),
            padding=(0, 1),
            expand=True,
        )
        for label, minimum in zip(labels, minimums):
            grid.add_column(Text(label), min_width=minimum, ratio=minimum, overflow="fold")
        for row in body:
            seen_cells: set[int] = set()
            values: list[RenderableType] = []
            for cell in row:
                if cell is None or id(cell) in seen_cells:
                    values.append("")
                else:
                    seen_cells.add(id(cell))
                    values.append(Markdown(cell.markdown))
            grid.add_row(*values)
        renderables.append(grid)
    return Group(*renderables)


def _render_body(article: Tag, width: int, *, facts: bool = False) -> list[RenderableType]:
    rendered: list[RenderableType] = []
    pending: list[str] = []
    overview = not facts

    def flush() -> None:
        nonlocal overview
        text = _to_markdown("".join(pending))
        pending.clear()
        if text:
            prose: RenderableType = Markdown(text)
            if overview:
                prose = Panel(prose, title="Overview", border_style="cyan")
            rendered.extend((prose, Text("")))
            overview = False

    def visit(node: Tag | NavigableString) -> None:
        nonlocal overview
        if isinstance(node, Tag) and node.name == "table":
            flush()
            overview = False
            rendered.extend((_render_table(node, width, facts=facts), Text("")))
        elif isinstance(node, Tag) and (match := _HEADING_RE.fullmatch(node.name or "")):
            flush()
            overview = False
            level = int(match.group(1))
            indent = "  " * max(0, level - 2)
            title = Text(f"{indent}{node.get_text(' ', strip=True)}", style="bold cyan")
            heading: RenderableType = (
                Panel(title, border_style="cyan", padding=(0, 1))
                if level <= 2
                else Group(title, Rule(style="dim cyan"))
            )
            rendered.extend((heading, Text("")))
        elif isinstance(node, Tag) and node.find(["table", "h1", "h2", "h3", "h4", "h5", "h6"]):
            for child in node.children:
                if isinstance(child, (Tag, NavigableString)):
                    visit(child)
        else:
            pending.append(escape(str(node)) if isinstance(node, NavigableString) else str(node))

    for child in article.children:
        if isinstance(child, (Tag, NavigableString)):
            visit(child)
    flush()
    return rendered


def pager_styles(console: Console) -> bool:
    """Return True only when the configured pager supports ANSI escape sequences."""
    command = os.environ.get("MANPAGER") or os.environ.get("PAGER", "")
    return console.is_terminal and bool(
        re.search(r"\bless(?:\.exe)?\b", command)
        and (
            re.search(r"-[A-Za-z]*[Rr]", command)
            or re.search(r"[Rr]", os.environ.get("LESS", ""))
        )
    )


def render_page(html: str, title: str, width: int) -> Group:
    """Lay out an article for ``width`` columns: title banner, quick facts, then body."""
    article = clean_article(html)
    header = Panel(
        Group(Text(title, style="bold cyan"), Text(page_url(title), style="dim")),
        border_style="cyan",
        padding=(1, 2),
    )
    rendered: list[RenderableType] = [header, Text("")]

    infoboxes = [
        element
        for element in article.select(".infobox")
        if not any(
            "infobox" in (parent.get("class") or [])
            for parent in element.parents
            if isinstance(parent, Tag)
        )
    ]
    inner_width = max(1, width - 4)
    for infobox in infoboxes:
        infobox.extract()
        facts = (
            _render_table(infobox, inner_width, facts=True)
            if infobox.name == "table"
            else Group(*_render_body(infobox, inner_width, facts=True))
        )
        rendered.extend((Panel(facts, title="Quick facts", border_style="cyan"), Text("")))

    rendered.extend(_render_body(article, width))
    return Group(*rendered)
