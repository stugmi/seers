# Seers

![Supported Python Versions](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)

Python client for Old School RuneScape data.

| Module | Source |
| :--- | :--- |
| `seers.wiki` | [OSRS Wiki](https://oldschool.runescape.wiki) pages and search |
| `seers.ge` | Grand Exchange prices from the Wiki's [real-time prices API](https://prices.runescape.wiki) |
| `seers.hiscores` | Official hiscores |
| `seers.data` | Internal names from the game cache (items, NPCs, objects, interfaces, varps, varbits, ...), bundled for offline use |

It also ships two command-line tools and an optional MCP server. Requires Python 3.10+.

## Install

From a checkout:

```sh
python -m pip install .
python -m pip install ".[mcp]"   # with the MCP server
```

## Usage

```python
from seers import wiki, ge, hiscores, data

page = wiki.page("Abyssal whip")
price = ge.price("Abyssal whip")
player = hiscores.lookup("Lynx Titan")
item = data.items.get(4151)
```

Results are frozen dataclasses that also implement Rich's console protocol, so `rich.print(result)` renders a table or a formatted article. In the REPL, `rich.pretty.install()` does this automatically; `repr()` still shows the plain dataclass.

### Async

`AsyncClient` has the same services with awaitable methods, and runs under asyncio or trio:

```python
import anyio
from seers import AsyncClient

async def main():
    async with AsyncClient() as client:
        price = await client.ge.price("Abyssal whip")
        player = await client.hiscores.lookup("Lynx Titan")
        item = client.data.items.get(4151)   # the cache is local, so this stays synchronous

anyio.run(main)
```

`ge.items` is a property on `Client` and a method on `AsyncClient` (`await client.ge.items()`).

### Wiki

Redirects are followed.

```python
from seers import wiki

page = wiki.page("Marks of grace")   # resolves to "Mark of Grace"
page.url
page.text                            # plain text
page.markdown                        # Markdown, including tables and references
page.html                            # parsed HTML from the API
page.soup                            # cleaned BeautifulSoup tag
page.tables                          # every table as rows of strings
page.table("Marks/h")                # first table containing "Marks/h"

page.show(pager=True, width=100)     # render in the terminal

wiki.search("dragon scimitar", limit=5)
wiki.info("Abyssal whip", "Vorkath")  # existence, page ID, revision, length, last edit
```

### Grand Exchange

Items can be given as an ID, a case-insensitive exact name, or an `Item`.

```python
from seers import ge

price = ge.price("Abyssal whip")
price.high, price.low, price.margin

ge.history(4151, "24h")              # up to 365 points; "5m", "1h", "6h" or "24h"
ge.search("dragon", limit=10)

whip = ge.item("Abyssal whip")
whip.id, whip.limit, whip.high_alch
```

The item list (`ge.items`) is downloaded on first use and kept in memory; `ge.refresh()` reloads it. Prices are not cached.

### Hiscores

`lookup()` queries the `main`, `ironman`, `hardcore` and `ultimate` tables to determine the account type.

```python
from seers import hiscores

player = hiscores.lookup("Lynx Titan")
player.mode                          # "main", "ironman", "hardcore" or "ultimate"
player.total_level
player.skills["attack"].xp
player.bosses["vorkath"].score
player.clues["clue_scrolls_all"].score
```

`player.stats` holds every table that was fetched. `player.deironed`, `player.hardcore_died` and `player.deulted` are set by comparing XP across them.

To fetch a single table, including `deadman` and `seasonal`:

```python
hiscores.stats("Lynx Titan", mode="main")
```

Keys are the hiscores names in `snake_case` (`"kril_tsutsaroth"`, `"lms_rank"`). Unranked entries have rank `-1`.

### Cache names

The package includes `cache.db`, a snapshot of the internal names from archive 24 of the game cache. No network access is needed.

```python
from seers import data

data.items.get(4151)                 # Entry(id='4151', name='abyssal_whip')
data.items.search("abyssal whip")    # fuzzy; spaces match underscores
data.npcs.search("vorkath")

for varbit in data.varbits:
    ...
```

| Attribute | `Kind` | Cache table | Contents |
| :--- | :--- | :--- | :--- |
| `data.items` | `Kind.ITEMS` | `objtypes` | Items |
| `data.npcs` | `Kind.NPCS` | `npctypes` | NPCs |
| `data.locs` | `Kind.LOCS` | `loctypes` | World objects |
| `data.animations` | `Kind.ANIMATIONS` | `seqtypes` | Animations |
| `data.spotanims` | `Kind.SPOTANIMS` | `spottypes` | Spot animations |
| `data.sounds` | `Kind.SOUNDS` | `soundtypes` | Sound effects |
| `data.sprites` | `Kind.SPRITES` | `spritetypes` | Sprites |
| `data.interfaces` | `Kind.INTERFACES` | `iftypes` | Interfaces (`id:component`) |
| `data.inventories` | `Kind.INVENTORIES` | `invtypes` | Inventories |
| `data.varps` | `Kind.VARPS` | `varptypes` | VarPlayers |
| `data.varbits` | `Kind.VARBITS` | `varbittypes` | VarBits |
| `data.dbrows` | `Kind.DBROWS` | `rowtypes` | Database rows |
| `data.dbtables` | `Kind.DBTABLES` | `tabletypes` | Database tables (`id:column`) |

`data.table()` takes a `Kind` or a cache table name (`data.table("objtypes")`), and `data.tables` lists every table. `Cache("/path/to/dir")` reads plain-text tables from a directory instead: one file per table, one `id name` pair per line.

### Updating the cache

The bundled snapshot goes out of date when the game updates. `update()` downloads the latest live English cache from the [OpenRS2 Archive](https://archive.openrs2.org/caches.json) and decodes the names locally:

```python
from seers import data, Cache

data.update()                                # download now
Cache(auto_update=True, max_age=86400)       # refresh on access when older than a day
```

A download is validated in a staging file and then swapped in atomically; if it fails, the previous snapshot stays active. Snapshots are stored in:

- Windows: `%LOCALAPPDATA%\seers`
- macOS: `~/Library/Caches/seers`
- Linux: `~/.cache/seers`

`cache_dir=` overrides the location. `CacheUpdater` does the download on its own, and `CacheUpdater().status()` reports the active snapshot's source, version and row counts.

### Configuration

The Wiki asks API clients to send a `User-Agent` with contact details. The default is `seers/<version> (+https://github.com/stugmi/seers)`. To change it on the default client:

```python
import seers

seers.configure(user_agent="my-app/1.0 (me@example.com)", timeout=15.0)
```

Or use a separate client:

```python
from seers import Client

with Client(user_agent="my-app/1.0", timeout=10.0, auto_update=True) as client:
    client.wiki.page("Vorkath")
```

### Errors

| Exception | Raised when |
| :--- | :--- |
| `OSRSError` | An upstream request fails or returns invalid data |
| `PlayerNotFoundError` | The name is not on the hiscores |
| `CacheUpdateError` | A cache download, validation or swap fails |
| `KeyError` | A local lookup finds nothing, e.g. `ge.item("not an item")` |
| `ValueError` | An argument is invalid |

## Command line

```sh
seers-wiki "Mark of Grace"
seers-wiki "Abyssal whip" --pager --width 80
```

On Windows the default pager drops colours; set `PAGER="less -R"` or omit `--pager`.

```sh
seers-update                   # update the cache; skipped if the snapshot is under a day old
seers-update --force           # update regardless of age
seers-update --cache-id 2746   # pin an OpenRS2 cache ID
```

Both also run as modules: `python -m seers.cli.wiki`, `python -m seers.cli.update`.

## MCP server

An optional extension in `seers.mcp`, installed with the `mcp` extra (MCP Python SDK 2.x). `import seers` never loads it. It runs over stdio, one server per client:

```sh
seers-mcp          # or: python -m seers.mcp
```

| Tool | Returns |
| :--- | :--- |
| `cache_search`, `cache_get` | Internal IDs and debug names from the bundled cache |
| `wiki_search`, `wiki_page` | Wiki search hits; an article as Markdown |
| `ge_search`, `ge_price`, `ge_history` | Items, latest prices, price history |
| `player_lookup`, `player_stats` | Hiscores with account type detected; one hiscores table |

All tools are read-only and return structured results with an output schema, except `wiki_page`, which returns Markdown text. Lookups that fail (unknown player, missing ID) come back as tool errors with a readable message.

The server exits when its stdin closes, and also when the client process that started it exits, even if another process still holds the pipe open.

Options: `--cache-path` (your own `cache.db` or directory), `--cache-dir`, `--auto-update`, `--max-age`.

Client configuration:

```json
{
  "mcpServers": {
    "seers": {
      "command": "/absolute/path/to/venv/bin/seers-mcp"
    }
  }
}
```

On Windows the script is `Scripts\seers-mcp.exe` inside the venv. With `uv`:

```json
{
  "mcpServers": {
    "seers": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/seers", "--extra", "mcp", "seers-mcp"]
    }
  }
}
```

From Python, `seers.mcp.SeersMCP` is an `MCPServer`: `SeersMCP().run()`, or `SeersMCP(client)` to share an `AsyncClient` you manage.

## Examples

```sh
python examples/agility_marks.py   # agility courses ranked by marks of grace and XP/hr
python examples/cache_names.py
```

## License

[WTFPL](LICENSE). Game data and names in the bundled cache belong to Jagex.
