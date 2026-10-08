"""Game definitions: the cache's internal names, searchable offline."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from pathlib import Path
import re
from typing import Any

from rich.table import Table
from rich.text import Text

from ..display import RichDisplay, Results, cell, table
from ..validation import integer
from .fetch import DataUpdater


def fuzzy_score(text: str, pattern: str) -> int:
    """Score substrings, unordered tokens, then consecutive subsequences."""
    text = text.lower()
    pattern = pattern.lower()
    if pattern in text:
        return 100
    tokens = [token for token in re.split(r"[\s_]+", pattern) if token]
    if len(tokens) > 1 and all(token in text for token in tokens):
        return 75
    score = pattern_index = consecutive = 0
    for character in text:
        if character == pattern[pattern_index]:
            score += 1 + consecutive
            consecutive += 1
            pattern_index += 1
            if pattern_index == len(pattern):
                return min(50, (score * 20) // len(pattern))
        else:
            consecutive = 0
    return 0


@dataclass(frozen=True)
class Definition:
    id: str
    name: str
    line: int = field(default=0, repr=False)


class DefinitionFile(RichDisplay):
    """One definition file. Iterate it, ``get`` an ID, or ``search`` names."""

    def __init__(self, store: "Definitions", filename: str) -> None:
        self._store = store
        self.filename = filename

    def __repr__(self) -> str:
        return f"DefinitionFile({self.filename!r})"

    @property
    def path(self) -> Path:
        """The file in the active data directory, which may change after an update."""
        return self._store._file_path(self.filename)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def size(self) -> int:
        """Size in bytes."""
        return self._open_path().stat().st_size

    @property
    def modified(self) -> datetime:
        return datetime.fromtimestamp(self._open_path().stat().st_mtime, timezone.utc)

    @property
    def created(self) -> datetime:
        """Creation time, or the inode change time where the OS doesn't record it."""
        stats = self._open_path().stat()
        return datetime.fromtimestamp(getattr(stats, "st_birthtime", stats.st_ctime), timezone.utc)

    def _open_path(self) -> Path:
        path = self.path
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        return path

    def __iter__(self) -> Iterator[Definition]:
        with self._open_path().open(encoding="utf-8", errors="replace") as source:
            for number, line in enumerate(source, 1):
                line = line.rstrip("\r\n")
                if line.strip():
                    identifier, name = (line.split(None, 1) + [""])[:2]
                    yield Definition(identifier, name, number)

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def get(self, id: int | str) -> Definition:
        """Return the definition with this ID, e.g. ``data.items.get(4151)``."""
        wanted = str(id)
        found = next((definition for definition in self if definition.id == wanted), None)
        if found is None:
            raise KeyError(f"No {self.filename} entry with id {wanted}")
        return found

    def search(self, query: str, limit: int = 10, offset: int = 0) -> Results[Definition]:
        """Fuzzy name search; spaces match underscores. Best matches first, ties in file order."""
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        integer(limit, "limit")
        integer(offset, "offset", minimum=0)
        pattern = query.replace(" ", "_")
        scored = [(score, definition) for definition in self
                  if (score := fuzzy_score(f"{definition.id}\t{definition.name}", pattern))]
        scored.sort(key=lambda match: match[0], reverse=True)
        return Results([definition for _, definition in scored[offset:offset + limit]], len(scored), query)

    def __rich__(self) -> Table:
        result = table(self.filename)
        result.show_header = False
        result.add_column(style="bold cyan")
        result.add_column()
        result.add_row("Definitions", cell(len(self)))
        result.add_row("Size", Text(f"{self.size:,} bytes"))
        result.add_row("Modified", cell(self.modified))
        result.add_row("Path", cell(self.path))
        return result


class _Kind:
    """Class attribute that returns the store's DefinitionFile for one cache file."""

    def __init__(self, filename: str) -> None:
        self.filename = filename

    def __get__(self, store: "Definitions | None", owner: type) -> Any:
        return self if store is None else DefinitionFile(store, self.filename)


class Definitions(RichDisplay):
    """The bundled snapshot, a downloaded update, or your own ``data_dir``.

    >>> data = Definitions()
    >>> data.items.search("abyssal whip")[0]
    Definition(id='4151', name='abyssal_whip')

    Updates are opt-in: ``auto_update=True`` refreshes on first access when the
    snapshot is older than ``max_age`` seconds, ``update()`` refreshes now.
    """

    # ``items`` are objtypes and ``locs`` are world objects (loctypes).
    varps = _Kind("varptypes.txt")
    varbits = _Kind("varbittypes.txt")
    interfaces = _Kind("iftypes.txt")
    inventories = _Kind("invtypes.txt")
    locs = _Kind("loctypes.txt")
    npcs = _Kind("npctypes.txt")
    items = _Kind("objtypes.txt")
    rows = _Kind("rowtypes.txt")
    animations = _Kind("seqtypes.txt")
    sounds = _Kind("soundtypes.txt")
    spotanims = _Kind("spottypes.txt")
    sprites = _Kind("spritetypes.txt")
    tables = _Kind("tabletypes.txt")

    def __init__(
        self,
        data_dir: str | Path | None = None,
        *,
        cache_dir: str | Path | None = None,
        auto_update: bool = False,
        max_age: float = 86400,
    ) -> None:
        if not isinstance(auto_update, bool):
            raise ValueError("auto_update must be a boolean")
        if isinstance(max_age, bool) or not isinstance(max_age, (int, float)) or not math.isfinite(max_age) or max_age < 0:
            raise ValueError("max_age must be finite, nonnegative seconds")
        if data_dir is not None and (auto_update or cache_dir is not None):
            raise ValueError("data_dir cannot be combined with auto_update or cache_dir")
        self._auto_update = auto_update
        self._max_age = max_age
        self._bundled_dir = (Path(__file__).parent / "bundled").resolve()
        self.updater = DataUpdater(cache_dir=cache_dir) if data_dir is None else None
        active = self.updater.current_data_dir() if self.updater is not None else None
        self._data_dir = Path(data_dir).resolve() if data_dir is not None else (active or self._bundled_dir)

    def __repr__(self) -> str:
        return f"Definitions({str(self._data_dir)!r})"

    @property
    def kinds(self) -> dict[str, DefinitionFile]:
        """The 13 known files by attribute name, e.g. ``{"items": ..., "npcs": ...}``."""
        return {kind: getattr(self, kind) for kind in KINDS}

    @property
    def data_dir(self) -> Path:
        """The active directory, refreshed first when ``auto_update`` is on."""
        if self.updater is not None:
            if self._auto_update:
                self.updater.update(max_age=self._max_age)
            self._data_dir = self.updater.current_data_dir() or self._bundled_dir
        return self._data_dir

    def update(self, *, force: bool = True) -> Path:
        """Download the latest snapshot into the cache and switch to it.

        A failed update raises DataUpdateError and keeps the current files.
        """
        if self.updater is None:
            raise ValueError("Updates use the managed cache, not a supplied data_dir")
        self._data_dir = self.updater.update(force=force, max_age=self._max_age)
        return self._data_dir

    def _file_path(self, filename: str, *, data_dir: Path | None = None) -> Path:
        if (
            not isinstance(filename, str)
            or not filename
            or filename == "."
            or ".." in filename
            or any(character in filename for character in ("/", "\\", ":", "\0"))
        ):
            raise ValueError("Invalid filename: expected a direct child filename")
        directory = data_dir if data_dir is not None else self.data_dir
        resolved = (directory / filename).resolve()
        if resolved.parent != directory:
            raise ValueError("Invalid filename: file escapes the data directory")
        return resolved

    def file(self, filename: str) -> DefinitionFile:
        """Any file in the data directory, e.g. one you added yourself."""
        self._file_path(filename)
        return DefinitionFile(self, filename)

    @property
    def files(self) -> list[DefinitionFile]:
        """Regular files in the data directory, sorted by name."""
        directory = self.data_dir
        if not directory.is_dir():
            return []
        names = []
        for candidate in directory.iterdir():
            try:
                if self._file_path(candidate.name, data_dir=directory).is_file():
                    names.append(candidate.name)
            except ValueError:
                continue
        return [DefinitionFile(self, name) for name in sorted(names)]

    def __rich__(self) -> Table:
        result = table(str(self.data_dir))
        result.add_column("Attribute", style="bold cyan")
        result.add_column("File")
        result.add_column("Definitions", justify="right")
        by_file = {filename: kind for kind, filename in KINDS.items()}
        for found in self.files:
            result.add_row(by_file.get(found.filename, ""), found.filename, cell(len(found)))
        return result


# Attribute name -> cache file, e.g. {"items": "objtypes.txt", ...}.
KINDS = {name: value.filename for name, value in vars(Definitions).items() if isinstance(value, _Kind)}
