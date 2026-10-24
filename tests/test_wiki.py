from io import StringIO
import os
import re
from unittest.mock import patch

from bs4 import BeautifulSoup
import httpx
import pytest
from rich.console import Console

from conftest import reply
from seers import OSRSError, WikiPage
from seers.wiki.render import _table_parts, _table_rows, page_markdown, pager_styles

ARTICLE = """
<div id="outside">Outside article</div>
<div class="mw-parser-output">
  <div id="toc">Table of contents clutter</div>
  <div class="navbox"><span class="metadata">Navigation clutter</span></div>
  <script>Hidden script</script><style>Hidden style</style>
  <h2>Obtaining marks<span class="mw-editsection">Edit clutter</span></h2>
  <p>Spend <strong>260 marks</strong> at <a href="/w/Rogues%27_Den">Rogues' Den</a>.
     <sup class="reference">Citation clutter</sup></p>
  <ul><li>Train Agility</li><li>Buy graceful</li></ul>
  <table><tbody>
    <tr class="mw-empty-elt"></tr>
    <tr><th>Item</th><th>Price<br>in marks</th></tr>
    <tr><td>Graceful hood</td><td>35</td></tr>
  </tbody></table>
</div>
"""

SPANNED_TABLE = """
<table><caption>Market values</caption><tbody>
<tr><th rowspan="2">Item</th><th colspan="2">Price</th><th rowspan="2"></th></tr>
<tr><th>Buy</th><th>Sell</th></tr>
<tr><td rowspan="2">Hood</td><td>350</td><td>250</td><td><img src="hood.png"></td></tr>
<tr><td>351</td><td>251</td><td><img src="hood.png"></td></tr>
<tr><td colspan="2">Trade notes<br>Keep receipt<ul><li>Ask vendor</li><li>Check stock</li></ul></td>
    <td>900</td><td></td></tr>
</tbody></table>
"""


def render(html, *, width=100, terminal=None, title="Mark of Grace"):
    stream = StringIO()
    WikiPage(title, html).show(console=Console(file=stream, width=terminal or width, color_system=None), width=width)
    return stream.getvalue()


def cells(rows):
    return [[cell.plain if cell else "" for cell in row] for row in rows]


# Fetching


def test_page_follows_redirects_and_exposes_its_content(make_client):
    html = ('<table><tr><th>Course</th><th>Marks/h<sup>[1]</sup></th></tr>'
            '<tr><td>Canifis</td><td>19</td></tr></table><table><tr><td>Other</td></tr></table>')

    def handler(request):
        assert request.url.params["redirects"] == "1"
        return httpx.Response(200, json={"parse": {"title": "Mark of grace", "pageid": 7, "revid": 9, "text": html}})

    page = make_client(handler).wiki.page("Marks of grace")

    assert (page.title, page.page_id, page.revision_id) == ("Mark of grace", 7, 9)
    assert page.url == "https://oldschool.runescape.wiki/w/Mark_of_grace"
    assert page.table("Marks/h") == [["Course", "Marks/h"], ["Canifis", "19"]]
    assert len(page.tables) == 2
    assert "Canifis" in page.text
    assert "html" not in repr(page)
    with pytest.raises(KeyError):
        page.table("XP/h")


def test_search_strips_highlighting_and_links_to_sections(make_client):
    payload = {"query": {"searchinfo": {"totalhits": 42}, "search": [{
        "title": "Dragon scimitar", "sectiontitle": "Special attack",
        "snippet": 'The <span class="searchmatch">dragon</span> scimitar'}]}}
    results = make_client(reply(payload)).wiki.search("dragon", limit=1)

    assert (results.total, len(results)) == (42, 1)
    hit = results[0]
    assert (hit.title, hit.snippet, hit.section) == ("Dragon scimitar", "The dragon scimitar", "Special attack")
    assert hit.url == "https://oldschool.runescape.wiki/w/Dragon_scimitar#Special_attack"


def test_info_answers_in_request_order_and_flags_missing_pages(make_client):
    payload = {"query": {
        "normalized": [{"from": "twisted_bow", "to": "Twisted bow"}],
        "pages": [
            {"title": "Bronze 2h of doom", "missing": True},
            {"title": "Twisted bow", "pageid": 1, "lastrevid": 2, "length": 3,
             "touched": "2026-01-02T03:04:05Z", "redirect": True},
        ]}}

    def handler(request):
        assert request.url.params["titles"] == "twisted_bow|Bronze 2h of doom"
        return httpx.Response(200, json=payload)

    bow, missing = make_client(handler).wiki.info("twisted_bow", "Bronze 2h of doom")

    assert (bow.title, bow.exists, bow.page_id, bow.revision_id, bow.length, bow.redirect) == (
        "Twisted bow", True, 1, 2, 3, True)
    assert bow.touched.year == 2026
    assert (missing.title, missing.exists) == ("Bronze 2h of doom", False)


@pytest.mark.parametrize("payload", [{}, {"parse": {}}, {"parse": {"text": None}}])
def test_pages_without_content_raise(make_client, payload):
    with pytest.raises(OSRSError, match="Wiki page content not found: Bronze 2h of doom"):
        make_client(reply(payload)).wiki.page("Bronze 2h of doom")


@pytest.mark.parametrize(("payload", "message"), [
    ({"error": {"code": "missingtitle", "info": "The page you specified doesn't exist."}}, "missingtitle"),
    ({"errors": [{"code": "badvalue"}]}, "badvalue"),
])
def test_mediawiki_errors_raise(make_client, payload, message):
    with pytest.raises(OSRSError, match=message):
        make_client(reply(payload)).wiki.search("Vorkath")


@pytest.mark.parametrize(("method", "args", "kwargs"), [
    ("search", ("Vorkath",), {"limit": 51}),
    ("search", ("Vorkath",), {"limit": 0}),
    ("search", ("Vorkath",), {"limit": False}),
    ("search", ("Vorkath",), {"offset": -1}),
    ("search", ("Vorkath",), {"offset": 1.5}),
    ("search", (1,), {}),
    ("page", (None,), {}),
    ("page", ("",), {}),
    ("info", (), {}),
])
def test_bad_arguments_fail_before_any_request(make_client, method, args, kwargs):
    def forbidden(request):
        pytest.fail(f"unexpected request to {request.url}")

    with pytest.raises(ValueError):
        getattr(make_client(forbidden).wiki, method)(*args, **kwargs)


# Reading view


def test_rich_view_keeps_the_article_and_drops_wiki_chrome():
    stream = StringIO()
    Console(file=stream, width=100, force_terminal=True, color_system="standard").print(WikiPage("Mark of Grace", ARTICLE))
    text = stream.getvalue()

    assert "\x1b[" in text
    for kept in ("Mark of Grace", "Mark_of_Grace", "Obtaining marks", "260 marks", "Rogues' Den",
                 "Train Agility", "Buy graceful", "Graceful hood", "35"):
        assert kept in text
    for dropped in ("Outside article", "contents clutter", "Navigation clutter", "Hidden script",
                    "Hidden style", "Edit clutter", "Citation clutter", "/w/Rogues%27_Den", "| Graceful hood |"):
        assert dropped not in text


def test_rich_view_caps_width_while_repr_stays_plain():
    page = WikiPage("Mark of Grace", ARTICLE)
    stream = StringIO()
    Console(file=stream, width=160, color_system=None).print(page)

    assert max(map(len, stream.getvalue().splitlines())) <= 100
    assert repr(page) == "WikiPage(title='Mark of Grace', page_id=0, revision_id=0)"


def test_ipython_gets_the_rich_view():
    class Printer:
        def text(self, value):
            self.value = value

    printer = Printer()
    WikiPage("Mark of Grace", ARTICLE)._repr_pretty_(printer, cycle=False)
    assert "Graceful hood" in printer.value


@pytest.mark.parametrize("width", [100, 45, 24])
def test_spanned_tables_render_every_cell_at_any_width(width):
    text = render(f'<div class="mw-parser-output">{SPANNED_TABLE}</div>', width=width)
    for token in ("Market", "values", "Item", "Price", "Buy", "Sell", "Hood", "350", "250", "351", "251",
                  "Trade", "notes", "Keep", "receipt", "Ask", "vendor", "Check", "stock", "900"):
        assert token in text
    assert "|" not in text and "<td" not in text
    assert max(map(len, text.splitlines())) <= width


def test_span_grid_puts_cells_at_their_real_coordinates():
    table = BeautifulSoup(SPANNED_TABLE, "html.parser").table
    for image in table.find_all("img"):
        image.decompose()
    labels, body = _table_parts(_table_rows(table))

    assert labels == ["Item", "Price / Buy", "Price / Sell"]
    assert cells(body[:2]) == [["Hood", "350", "250"], ["Hood", "351", "251"]]
    assert body[0][0] is body[1][0]
    assert body[2][0] is body[2][1]
    assert body[2][2].plain == "900"
    notes = body[2][0].markdown
    assert "* Ask vendor" in notes and "* Check stock" in notes and "\n" in notes and "|" not in notes


def test_narrow_screens_switch_wide_tables_to_labelled_records():
    html = """<div class="mw-parser-output"><table>
    <tr><th>Item</th><th>Price</th><th>Weight</th><th>Level</th><th>Source</th></tr>
    <tr><td>Hood</td><td>350</td><td>0.5 kg</td><td>12</td><td>Vendor A</td></tr>
    <tr><td>Cape</td><td>400</td><td>0.7 kg</td><td>20</td><td>Vendor B</td></tr>
    </table></div>"""
    text = render(html, width=44)
    for pattern in (r"Price[^\n]*350", r"Price[^\n]*400", r"Source[^\n]*Vendor A", r"Source[^\n]*Vendor B"):
        assert re.search(pattern, text)
    assert text.index("Hood") < text.index("Cape")
    assert "|" not in text


def test_nested_infoboxes_are_shown_once():
    html = """<div class="mw-parser-output"><div class="infobox">
      <table class="infobox"><tr><th colspan="2">Artifact details</th></tr>
      <tr><th>Members</th><td>Yes indeed</td></tr>
      <tr><th>Variants</th><td><table><tr><th>Type</th><th>Code</th></tr>
      <tr><td>Ancient</td><td>R123</td></tr></table></td></tr></table>
      </div><div><p>Intro paragraph.</p><section><h2>Uses</h2>
      <p>Later paragraph.</p></section></div></div>"""
    text = render(html)
    for content in ("Artifact details", "Members", "Yes indeed", "Variants", "Ancient",
                    "R123", "Intro paragraph.", "Uses", "Later paragraph."):
        assert text.count(content) == 1, content
    assert "|" not in text


def test_infobox_image_rows_do_not_eat_labels():
    html = """<div class="mw-parser-output"><table class="infobox">
    <tr><th colspan="20">Artifact details</th></tr>
    <tr><td colspan="20"><img src="artifact.png"></td></tr>
    <tr><th colspan="7">Released</th><td colspan="13">5 December 2013</td></tr>
    <tr><th colspan="7">Members</th><td colspan="13">Yes indeed</td></tr>
    </table><p>Visible article.</p><!--Internal parser report--></div>"""
    text = render(html)
    assert re.search(r"Released[^\n]*5 December 2013", text)
    assert re.search(r"Members[^\n]*Yes indeed", text)
    assert "Visible article." in text
    assert "Internal parser report" not in text


def test_nested_tables_stay_inside_their_cell():
    html = """<table><tr><th>Category</th><th>Details</th></tr>
    <tr><td>Runes</td><td><table><caption>Variants</caption>
    <tr><th>Element</th><th>Cost</th></tr><tr><td>Air<br>Water<ul><li>Rune pack</li></ul></td><td>15</td></tr>
    </table></td></tr></table>"""
    rows = _table_rows(BeautifulSoup(html, "html.parser").table)

    assert [len(row) for row in rows] == [2, 2]
    details = rows[1][1].markdown
    for content in ("Variants", "Element", "Air", "Water", "* Rune pack", "Cost", "15"):
        assert content in details
    assert "|" not in details


def test_rowspan_zero_stops_at_the_end_of_its_group():
    html = """<table><tbody><tr><td rowspan="0">Group A</td><td>10</td></tr>
    <tr><td>20</td></tr></tbody><tbody><tr><td>Group B</td><td>30</td></tr></tbody></table>"""
    rows = _table_rows(BeautifulSoup(html, "html.parser").table)
    assert cells(rows) == [["Group A", "10"], ["Group A", "20"], ["Group B", "30"]]


def test_icon_columns_do_not_take_a_data_column():
    html = """<table><tr><th colspan="2">Item</th><th>Price</th></tr>
    <tr><td><img src="icon.png"></td><td>Hood</td><td>350</td></tr></table>"""
    labels, body = _table_parts(_table_rows(BeautifulSoup(html, "html.parser").table))
    assert (labels, cells(body)) == (["Item", "Price"], [["Hood", "350"]])


def test_section_order_and_markdown_survive_wrapper_divs():
    html = """<div class="mw-parser-output"><div><p>Intro prose.</p>
    <section><h2>Primary section</h2><p>First body paragraph.</p>
    <div><h3>Nested section</h3><p>Second body paragraph.</p>
    <ol><li>First step</li><li>Second step</li></ol></div></section>
    <h2>References</h2><ol class="references"><li>Published source.</li></ol>
    </div></div>"""
    text = render(html)
    expected = ("Intro prose.", "Primary section", "First body paragraph.", "Nested section",
                "Second body paragraph.", "First step", "Second step", "References", "Published source.")
    positions = [text.index(content) for content in expected]
    assert positions == sorted(positions)

    markdown = page_markdown(html)
    for content in ("## Primary section", "### Nested section", "1. First step", "Published source."):
        assert content in markdown


@pytest.mark.parametrize(("width", "terminal"), [(100, 36), (60, 140)])
def test_titles_are_never_treated_as_markup(width, terminal):
    text = render(ARTICLE, width=width, terminal=terminal, title="[red]Rune[/red]")
    assert "[red]Rune[/red]" in text
    assert "\x1b[" not in text
    assert max(map(len, text.splitlines())) <= min(width, terminal)


def test_long_headings_wrap_instead_of_truncating():
    heading = "A long section title containing important final words"
    text = render(f'<div class="mw-parser-output"><h2>{heading}</h2><p>Body survives.</p></div>', width=24)
    assert all(word in text for word in heading.split())
    assert "Body survives." in text


@pytest.mark.parametrize(("pager", "coloured"), [("less -R", True), ("less -r", True), ("less", False), ("more", False)])
def test_pager_keeps_colour_only_when_it_understands_ansi(pager, coloured):
    stream = StringIO()
    with patch.dict(os.environ, {"PAGER": pager, "MANPAGER": "", "LESS": ""}):
        assert pager_styles(Console(file=stream, force_terminal=True)) is coloured
        assert pager_styles(Console(file=stream, force_terminal=False)) is False
