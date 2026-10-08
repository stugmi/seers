"""Rich rendering of Wiki article HTML, used by ``WikiPage``'s Rich view."""

from dataclasses import dataclass
from html import escape
import os
import re
from urllib.parse import quote

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from markdownify import markdownify
from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text


_CLUTTER = (
    "script, style, img, .mw-editsection, #toc, .toc, .navbox, "
    ".metadata, .noprint, .mw-empty-elt, sup.reference"
)
_HEADINGS = re.compile(r"^h[1-6]$")


def clean_article(html: str) -> Tag:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one(".mw-parser-output") or soup
    for comment in article.find_all(string=lambda node: isinstance(node, Comment)):
        comment.extract()
    for image in article.select("img"):
        cell = image.find_parent(["th", "td"])
        if cell is not None and not cell.get_text(strip=True):
            cell["data-osrs-icon-only"] = "1"
    for element in article.select(_CLUTTER):
        element.decompose()
    return article


def _markdown(html: str) -> str:
    return markdownify(html, heading_style="ATX", strip=["a"], table_infer_header=True).strip()


def page_markdown(html: str) -> str:
    """Convert article HTML to Markdown, retaining prose, lists and references.

    Navigation, images, edit links and inline citation markers are omitted.
    The terminal viewer separately renders HTML tables so spans and multiline
    cells are not constrained by Markdown's table syntax.
    """
    return _markdown(str(clean_article(html)))


@dataclass(eq=False)
class _Cell:
    markdown: str
    plain: str
    header: bool
    html: str
    icon_only: bool


def _span(cell: Tag, attribute: str) -> int:
    try:
        return max(1, int(cell.get(attribute, 1)))
    except (TypeError, ValueError):
        return 1


def _cell(cell: Tag) -> _Cell:
    # Nested tables belong to this cell, not to the surrounding table's rows.
    # Convert them to labeled lines rather than leaking Markdown pipe syntax.
    copy = BeautifulSoup(str(cell), "html.parser")
    for nested in [table for table in copy.find_all("table") if table.find_parent("table") is None]:
        rows = _table_rows(nested)
        labels, body = _table_parts(rows)
        replacement = copy.new_tag("div")
        caption = nested.find("caption", recursive=False)
        if caption:
            caption_copy = copy.new_tag("p")
            caption_copy.string = caption.get_text(" ", strip=True)
            replacement.append(caption_copy)
        for row in body:
            seen = set()
            for value in row:
                if value is None or id(value) in seen:
                    continue
                seen.add(id(value))
                entry = copy.new_tag("div")
                names = list(dict.fromkeys(labels[index] for index, cell in enumerate(row)
                                           if cell is value and labels[index]))
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
        nested.replace_with(replacement)
    content = copy.find(cell.name)
    html = content.decode_contents()
    icon_only = bool(
        _span(cell, "colspan") == 1
        and (cell.get("data-osrs-icon-only") or
             (cell.find("img") is not None and not cell.get_text(strip=True)))
    )
    return _Cell(_markdown(html), content.get_text(" ", strip=True), cell.name == "th", html, icon_only)


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
            value = _cell(tag)
            colspan = _span(tag, "colspan")
            group_remaining = 1
            for following in source_rows[row_index + 1:]:
                if following.parent is not tr.parent:
                    break
                group_remaining += 1
            rowspan = (group_remaining if str(tag.get("rowspan")) == "0"
                       else min(_span(tag, "rowspan"), group_remaining))
            for target_row in range(row_index, row_index + rowspan):
                while len(rows) <= target_row:
                    rows.append([])
                needed = column + colspan - len(rows[target_row])
                rows[target_row].extend([None] * max(0, needed))
                for target_column in range(column, column + colspan):
                    rows[target_row][target_column] = value
            column += colspan
    count = max((len(row) for row in rows), default=0)
    for row in rows:
        row.extend([None] * (count - len(row)))
    # Icon-only columns must not steal space from meaningful data.
    keep = []
    for index in range(count):
        cells = [row[index] for row in rows if row[index] is not None]
        if (any(cell.plain for cell in cells)
                and not (any(cell.icon_only for cell in cells)
                         and not any(cell.plain for cell in cells if not cell.header))):
            keep.append(index)
    return [[row[index] for index in keep] for row in rows if any(cell and cell.plain for cell in row)]


def _table_parts(rows: list[list[_Cell | None]]) -> tuple[list[str], list[list[_Cell | None]]]:
    count = len(rows[0]) if rows else 0
    headers = []
    for row in rows:
        cells = [cell for cell in row if cell is not None]
        if not cells or not all(cell.header for cell in cells):
            break
        headers.append(row)
    labels = []
    for column in range(count):
        parts = []
        previous = None
        for row in headers:
            cell = row[column]
            if cell is not None and cell is not previous and cell.plain:
                parts.append(cell.plain)
            previous = cell
        labels.append(" / ".join(parts))
    return labels, rows[len(headers):]


def _compact_rows(labels: list[str], rows: list[list[_Cell | None]], width: int) -> Group:
    rendered = []
    for row in rows:
        entries = []
        seen = set()
        for index, cell in enumerate(row):
            if cell is None or id(cell) in seen or not cell.plain:
                continue
            seen.add(id(cell))
            names = list(dict.fromkeys(labels[column] for column, value in enumerate(row)
                                       if value is cell and labels[column]))
            label = " / ".join(names) or f"Column {index + 1}"
            entries.append((label, cell.markdown))
        if not entries:
            continue
        if width < 32:
            content = Group(*(Group(Text(label, style="bold cyan"), Markdown(value))
                              for label, value in entries))
        else:
            content = Table.grid(padding=(0, 1), expand=True)
            content.add_column(style="bold cyan", width=min(24, max(8, width // 3)))
            content.add_column(ratio=1, overflow="fold")
            for label, value in entries:
                content.add_row(Text(label), Markdown(value))
        rendered.append(Panel(content, border_style="dim cyan", padding=(0, 1)))
    return Group(*rendered)


def _render_table(table: Tag, width: int, *, facts: bool = False) -> Group:
    rows = _table_rows(table)
    labels, body = _table_parts(rows)
    caption = table.find("caption", recursive=False)
    renderables = [Markdown(_markdown(str(caption)))] if caption else []
    if not rows:
        return Group(*renderables)
    if facts:
        # Infobox title/header rows are content too, even without data rows.
        for row in rows[:len(rows) - len(body)]:
            seen = set()
            for cell in row:
                if cell and id(cell) not in seen:
                    seen.add(id(cell))
                    renderables.append(Markdown(cell.markdown))
        for row in body:
            unique = list(dict.fromkeys(cell for cell in row if cell and cell.plain))
            if len(unique) == 2 and width >= 32:
                facts_table = Table.grid(padding=(0, 1), expand=True)
                facts_table.add_column(style="bold cyan", width=min(24, max(8, width // 3)))
                facts_table.add_column(ratio=1, overflow="fold")
                facts_table.add_row(Markdown(unique[0].markdown), Markdown(unique[1].markdown))
                renderables.append(facts_table)
            else:
                renderables.append(Group(*(Markdown(cell.markdown) for cell in unique)))
        return Group(*renderables)
    count = len(labels)
    # Allow sensible wrapping, but switch to labeled records before many narrow
    # columns make a wide Wiki table illegible. All values and headers survive.
    minimums = []
    for index, label in enumerate(labels):
        values = [label] + [row[index].plain for row in body if row[index] is not None]
        longest = max((len(word) for value in values for word in value.split()), default=1)
        minimums.append(min(24, max(8, longest)))
    if sum(minimums) + 3 * count + 1 > width:
        if body:
            renderables.append(_compact_rows(labels, body, width))
        else:
            renderables.extend(Text(label, style="bold cyan") for label in labels if label)
    else:
        grid = Table(box=box.ROUNDED, border_style="cyan", header_style="bold cyan",
                     show_header=any(labels), padding=(0, 1), expand=True)
        for label, minimum in zip(labels, minimums):
            grid.add_column(Text(label), min_width=minimum, ratio=minimum, overflow="fold")
        for row in body:
            seen = set()
            values = []
            for cell in row:
                if cell is None or id(cell) in seen:
                    values.append("")
                else:
                    seen.add(id(cell))
                    values.append(Markdown(cell.markdown))
            grid.add_row(*values)
        renderables.append(grid)
    return Group(*renderables)


def _body(article: Tag, width: int, *, facts: bool = False) -> list:
    rendered = []
    pending = []
    overview = not facts

    def flush() -> None:
        nonlocal overview
        text = _markdown("".join(pending))
        pending.clear()
        if text:
            prose = Markdown(text)
            rendered.append(Panel(prose, title="Overview", border_style="cyan") if overview else prose)
            rendered.append(Text(""))
            overview = False

    def visit(node: Tag | NavigableString) -> None:
        nonlocal overview
        if isinstance(node, Tag) and node.name == "table":
            flush()
            overview = False
            rendered.extend([_render_table(node, width, facts=facts), Text("")])
        elif isinstance(node, Tag) and _HEADINGS.fullmatch(node.name or ""):
            flush()
            overview = False
            level = int(node.name[1])
            title = Text(node.get_text(" ", strip=True), style="bold cyan")
            title.plain = "  " * max(0, level - 2) + title.plain
            heading = (Panel(title, border_style="cyan", padding=(0, 1)) if level <= 2
                       else Group(title, Rule(style="dim cyan")))
            rendered.extend([heading, Text("")])
        elif isinstance(node, Tag) and node.find(["table", "h1", "h2", "h3", "h4", "h5", "h6"]):
            for child in node.children:
                visit(child)
        else:
            pending.append(escape(str(node)) if isinstance(node, NavigableString) else str(node))

    for child in article.children:
        visit(child)
    flush()
    return rendered


def pager_styles(console: Console) -> bool:
    # pydoc's system pager is not always ANSI-aware (notably Windows more).
    # Preserve color only when an explicitly configured pager advertises it.
    command = os.environ.get("MANPAGER") or os.environ.get("PAGER", "")
    return console.is_terminal and bool(
        re.search(r"\bless(?:\.exe)?\b", command)
        and (re.search(r"-[A-Za-z]*[Rr]", command) or re.search(r"[Rr]", os.environ.get("LESS", "")))
    )


def render_page(html: str, title: str, width: int) -> Group:
    """Lay out an article for ``width`` columns: title, quick facts, then body."""
    article = clean_article(html)
    url = "https://oldschool.runescape.wiki/w/" + quote(title.replace(" ", "_"), safe="")
    rendered = [Panel(Group(Text(title, style="bold cyan"), Text(url, style="dim")),
                      border_style="cyan", padding=(1, 2)), Text("")]
    infoboxes = [element for element in article.select(".infobox")
                 if not any("infobox" in parent.get("class", []) for parent in element.parents
                            if isinstance(parent, Tag))]
    for infobox in infoboxes:
        infobox.extract()
        if infobox.name == "table":
            facts = _render_table(infobox, max(1, width - 4), facts=True)
        else:
            facts = Group(*_body(infobox, max(1, width - 4), facts=True))
        rendered.extend([Panel(facts, title="Quick facts", border_style="cyan"), Text("")])
    rendered.extend(_body(article, width))
    return Group(*rendered)
