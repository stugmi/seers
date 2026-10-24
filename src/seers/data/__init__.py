"""The game cache's debug names, bundled for offline use.

>>> from seers import data
>>> data.items.get(4151)
Entry(id='4151', name='abyssal_whip')
>>> data.npcs.search("vorkath")

Module attributes (``items``, ``npcs``, ``tables``, ``path``, ...) forward to the
default client's ``Cache``. Instantiate ``Cache(...)`` for custom settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from seers import client as _client
from seers.data.cache import Cache, Entry, Table, fuzzy_score
from seers.data.kind import Kind
from seers.data.updater import CacheStatus, CacheUpdateError, CacheUpdater

if TYPE_CHECKING:
    animations: Table
    dbrows: Table
    dbtables: Table
    interfaces: Table
    inventories: Table
    items: Table
    locs: Table
    npcs: Table
    sounds: Table
    spotanims: Table
    sprites: Table
    varbits: Table
    varps: Table
    path: Path
    tables: list[Table]

__all__ = [
    "Cache",
    "CacheStatus",
    "CacheUpdateError",
    "CacheUpdater",
    "Entry",
    "Kind",
    "Table",
    "animations",
    "dbrows",
    "dbtables",
    "fuzzy_score",
    "interfaces",
    "inventories",
    "items",
    "locs",
    "npcs",
    "path",
    "sounds",
    "spotanims",
    "sprites",
    "table",
    "tables",
    "update",
    "varbits",
    "varps",
]

_FORWARDED = frozenset({*Kind, "path", "tables"})


def table(name: str | Kind) -> Table:
    """A table by ``Kind``, cache name (``"objtypes"``) or custom file name."""
    return _client.default_client().data.table(name)


def update(*, force: bool = True) -> Path:
    """Download the latest OpenRS2 snapshot and activate it."""
    return _client.default_client().data.update(force=force)


def __getattr__(name: str) -> Any:
    if name in _FORWARDED:
        return getattr(_client.default_client().data, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
