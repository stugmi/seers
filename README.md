# seers

Python package for osrs: the OSRS Wiki, Grand Exchange
prices, official hiscores, and the game's internal definition names (items,
NPCs, objects, interfaces, varps, varbits and more).

Written mainly for Python 3.10 and newer


## Installing


```bash
pip install .
pip install ".[mcp]"   # optional MCP server
```

A quick taste of what it looks like:

```python
from seers import wiki, ge, hiscores, data

wiki.page("Abyssal whip")
ge.price("Abyssal whip")
hiscores.lookup("Lynx Titan")
data.items.get(4151)
```

## The Wiki

```python
from seers import wiki

page = wiki.page("Marks of grace")   # redirects work, this lands on "Mark of Grace"
page.url
page.text                            # plain text of the article
page.markdown                        # or markdown, handy for feeding into other tools
page.html                            # or the raw parsed HTML
page.table("Marks/h")                # first table that mentions "Marks/h", as rows of strings
```

`page.tables` gives you every table on the page, and `page.soup` is the
cleaned-up article as BeautifulSoup if you want to dig in yourself.

Searching and page metadata:

```python
wiki.search("dragon scimitar", limit=5)
wiki.info("Abyssal whip", "Vorkath")   # exists? revision, length, last edited. No content.
```

If you just want to read something, `page.show(pager=True)` prints it one
screen at a time. There's also a small command for it:

```bash
seers-wiki "Mark of Grace"
seers-wiki "Abyssal whip" --pager
```

(On Windows the default pager loses the colours. Either skip `--pager` or set
`PAGER="less -R"`.)

## Grand Exchange prices

Prices come from the Wiki's real-time prices API. Anywhere an item is
expected you can pass the ID, the exact name, or an `Item` object.

```python
from seers import ge

ge.price("Abyssal whip")          # latest high / low and when they traded
ge.price(4151).margin
ge.history(4151, "24h")           # up to 365 points, timestep can be 5m, 1h, 6h or 24h
ge.search("dragon", limit=10)

whip = ge.item("Abyssal whip")
whip.limit, whip.high_alch
```

The full item list is downloaded once and kept around. Call `ge.refresh()` if
you want it fetched again. Prices are never cached.

## Hiscores

```python
from seers import hiscores

player = hiscores.lookup("Lynx Titan")
player.mode                      # main, ironman, hardcore or ultimate
player.total_level
player.skills["attack"].xp
player.bosses["vorkath"].score
player.clues["clue_scrolls_all"].score
```

`lookup` checks the ironman, hardcore and ultimate tables as well, works out
what kind of account it is, and keeps all of them in `player.stats`. It also
tells you if someone de-ironed, lost their hardcore status or de-ulted. If you
only care about one table, use `hiscores.stats("name", mode="ironman")`. That
also works for `deadman` and `seasonal`.

Keys are just the hiscores names in snake_case, so `"kril_tsutsaroth"`,
`"clue_scrolls_all"`, `"lms_rank"` and so on. Anything unranked has a rank of
-1. The hiscores API doesn't say which activities are bosses, so `bosses`
uses a built-in list. A brand new boss shows up in `activities` until that
list gets updated.

## Game definitions

The package comes with the internal names from the game cache, so this part
works offline:

```python
from seers import data

data.items.get(4151)                 # Definition(id='4151', name='abyssal_whip')
data.items.search("abyssal whip")
data.npcs.search("vorkath")
for varbit in data.varbits:
    ...
```

The search is fuzzy, and spaces match underscores. The 13 files have
friendlier names than the cache uses:

- `items` (objtypes), `npcs`, `locs` (world objects, loctypes)
- `animations` (seqtypes), `spotanims`, `sounds`, `sprites`
- `interfaces` (iftypes), `inventories` (invtypes)
- `varps`, `varbits`, `rows`, `tables`

`data.file("whatever.txt")` lets you search any other file in the same folder,
and you can point it at your own folder with `Definitions("/path/to/dir")`.

### Updating them

The bundled snapshot goes stale whenever the game updates. To get fresh names,
seers can download the latest cache from the
[OpenRS2 archive](https://archive.openrs2.org/caches.json) and decode the
names itself. These are the real internal names, not made-up placeholders.

Nothing downloads unless you ask for it:

```python
from seers import data, Definitions

data.update()                                          # download now
Definitions(auto_update=True, max_age=86400)           # refresh when older than a day
```

```bash
seers-data                 # same thing from the terminal
seers-data --cache-id 2735 # pin a specific cache
```

Downloads are checked before anything gets swapped in. If one fails, you keep
whatever you had before. Downloaded snapshots go to `%LOCALAPPDATA%\seers` on
Windows, `~/Library/Caches/seers` on macOS and `~/.cache/seers` on Linux.

## Settings

The `wiki`, `ge`, `hiscores` and `data` modules all share one default client.
The Wiki asks people to send a User-Agent that says who they are, so please
set one:

```python
import seers
seers.configure(user_agent="my-app/1.0 (me@example.com)")
```

If you want separate settings, make your own client. It has the same
`wiki`, `ge`, `hiscores` and `data` attributes:

```python
from seers import Client

with Client(user_agent="my-app/1.0", timeout=10) as client:
    client.wiki.page("Vorkath")
```

`Client` also takes your own `httpx.Client`, plus the same data options as
`Definitions` (`data_dir`, `cache_dir`, `auto_update`, `max_age`).

All the calls are blocking. If you're in async code, run them in a thread.

When something goes wrong upstream you get an `OSRSError`, or
`PlayerNotFoundError` when a name isn't on the hiscores. Bad arguments raise
`ValueError`. Lookups that find nothing, like `ge.item("not an item")`, raise
`KeyError`.

## Pretty printing

Everything you get back is a normal dataclass, so you can poke at it in a
script like any other object. If you print it with Rich, you get a nicely
formatted table or article instead. The idea is
that the same object works for both quick lookups in a REPL and actual code.

```python
from rich import print
print(hiscores.lookup("Lynx Titan"))
print(wiki.page("Mark of Grace"))
```

IPython and Jupyter do this on their own. In the plain Python REPL, run
`from rich import pretty; pretty.install()` once. `repr()` is left alone, so
logs and debuggers still show the normal dataclass.

## Examples

A few runnable scripts live in [`examples/`](examples/):

```bash
python examples/agility_marks.py   # ranks agility courses by marks of grace and xp
python examples/mark_of_grace.py
python examples/definitions.py
```

## MCP server

If you want to hand all of this to an LLM, there's an MCP server. It's an
optional extra on top though, the library is the main thing.


```bash
pip install ".[mcp]"
seers-mcp     # or python -m seers
```

```json
{
  "mcpServers": {
    "seers": {
      "command": "/absolute/path/to/venv/bin/python",
      "args": ["-m", "seers"]
    }
  }
}
```

(On Windows that's `Scripts\python.exe` inside the venv.)

It covers everything the library does: wiki search, pages (as markdown or
HTML) and page info, GE search, prices and history, hiscores lookups, and
searching or listing the definition files. `--data-dir` and
`--auto-update --cache-dir ... --max-age ...` work the same as in Python.

You can also run it from your own code with
`seers.mcp.create_server(client).run()`.

## Development

```bash
pip install -e ".[mcp,dev]"
pytest
```

The tests don't touch the network. CI runs them on Python 3.10 and 3.14.

Rough layout: `wiki/`, `ge/` and `hiscores/` each have an `api.py` that talks
to the service and a `models.py` with the dataclasses. `data/` has the bundled
files and the search code, with the downloader and cache decoder in
`data/fetch/`. The MCP server lives in `mcp/`.

## License

[WTFPL](LICENSE). Do what you want with it.

The game data and names in the bundled files belong to Jagex, not to this
project, so the license doesn't cover them.
