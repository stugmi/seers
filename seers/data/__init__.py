"""Game definitions: the cache's internal names, bundled for offline use.

>>> from seers import data
>>> data.items.get(4151)
Definition(id='4151', name='abyssal_whip')
>>> data.npcs.search("vorkath")

Attributes here (``items``, ``npcs``, ``update()``, ...) forward to the default
client's ``Definitions``. Create ``Definitions(...)`` for your own settings.
"""

from typing import TYPE_CHECKING, Any

from .definitions import KINDS, Definition, DefinitionFile, Definitions, fuzzy_score
from .fetch import DataUpdateError, DataUpdater

if TYPE_CHECKING:
    from pathlib import Path

    varps: DefinitionFile
    varbits: DefinitionFile
    interfaces: DefinitionFile
    inventories: DefinitionFile
    locs: DefinitionFile
    npcs: DefinitionFile
    items: DefinitionFile
    rows: DefinitionFile
    animations: DefinitionFile
    sounds: DefinitionFile
    spotanims: DefinitionFile
    sprites: DefinitionFile
    tables: DefinitionFile
    files: list[DefinitionFile]
    kinds: dict[str, DefinitionFile]
    data_dir: Path
    updater: DataUpdater | None

    def file(filename: str) -> DefinitionFile: ...
    def update(*, force: bool = True) -> Path: ...

__all__ = ["Definitions", "DefinitionFile", "Definition", "DataUpdater", "DataUpdateError",
           "KINDS", "fuzzy_score", *KINDS, "file", "files", "kinds", "update", "data_dir", "updater"]

_FORWARDED = {*KINDS, "file", "files", "kinds", "update", "data_dir", "updater"}


def __getattr__(name: str) -> Any:
    if name in _FORWARDED:
        from ..client import default_client
        return getattr(default_client().data, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
