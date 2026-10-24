"""The game cache's debug names: exact ID lookup and fuzzy search, offline."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Literal, overload

from rich.table import Table as RichTable
from rich.text import Text

from seers.data.kind import Kind
from seers.data.store import DB_FILENAME, read_header, read_table_bytes
from seers.data.updater import CacheUpdater
from seers.display import Results, RichDisplay, format_cell, make_table
from seers.validation import validate_duration, validate_int

_TOKEN_SPLIT_RE = re.compile(r"[\s_]+")
_INVALID_NAME_CHARS = frozenset(("/", "\\", ":", "\0"))


def _validate_table_name(name: str) -> str:
    if (
        not isinstance(name, str)
        or not name
        or name == "."
        or ".." in name
        or any(ch in _INVALID_NAME_CHARS for ch in name)
    ):
        raise ValueError("Invalid table name")
    return name


def _is_db_file(path: Path) -> bool:
    return path.suffix == ".db" and not path.is_dir()


def _resolve_in_dir(directory: Path, name: str) -> Path:
    _validate_table_name(name)
    resolved = (directory / name).resolve()
    if resolved.parent != directory:
        raise ValueError("Invalid table name: path escapes the data directory")
    return resolved


def _file_times(stats: os.stat_result) -> tuple[datetime, datetime]:
    """Modified and created times in UTC; created falls back to ``st_ctime``."""
    created = getattr(stats, "st_birthtime", stats.st_ctime)
    return (
        datetime.fromtimestamp(stats.st_mtime, timezone.utc),
        datetime.fromtimestamp(created, timezone.utc),
    )


def _score_precomputed(text: str, pattern: str, tokens: tuple[str, ...]) -> int:
    if pattern in text:
        return 100
    if len(tokens) > 1 and all(token in text for token in tokens):
        return 75

    pos = -1
    for ch in pattern:
        pos = text.find(ch, pos + 1)
        if pos == -1:
            return 0

    score = pattern_index = consecutive = 0
    pattern_len = len(pattern)
    for ch in text:
        if ch == pattern[pattern_index]:
            score += 1 + consecutive
            consecutive += 1
            pattern_index += 1
            if pattern_index == pattern_len:
                return min(50, (score * 20) // pattern_len)
        else:
            consecutive = 0
    return 0


def fuzzy_score(text: str, pattern: str) -> int:
    """Score exact substrings (100), unordered tokens (75), then subsequences (1..50)."""
    folded_text = text.lower()
    folded_pattern = pattern.lower()
    if folded_pattern in folded_text:
        return 100
    tokens = tuple(t for t in _TOKEN_SPLIT_RE.split(folded_pattern) if t)
    return _score_precomputed(folded_text, folded_pattern, tokens)


@dataclass(frozen=True)
class Entry:
    """One row of a table: an ID and its internal debug name."""

    id: str
    name: str
    line: int = field(default=0, repr=False)


class _LoadedTable:
    """Lazily indexed table representation backed by a contiguous buffer."""

    __slots__ = (
        "_by_id",
        "_entries",
        "created",
        "folded_block",
        "key",
        "line_numbers",
        "modified",
        "raw_block",
        "row_count",
        "size",
    )

    def __init__(
        self,
        key: tuple[Path, int, int],
        raw_text: str,
        size: int,
        modified: datetime,
        created: datetime,
        *,
        normalized: bool,
    ) -> None:
        self.key = key
        self.size = size
        self.modified = modified
        self.created = created
        self._entries: tuple[Entry, ...] | None = None
        self._by_id: dict[str, Entry] | None = None

        if normalized:
            cleaned = raw_text.rstrip("\n")
            self.raw_block = cleaned
            self.folded_block = cleaned.lower()
            self.row_count = (cleaned.count("\n") + 1) if cleaned else 0
            self.line_numbers: tuple[int, ...] | None = None
        else:
            norm_lines: list[str] = []
            line_nums: list[int] = []
            for number, raw_line in enumerate(raw_text.splitlines(), 1):
                line = raw_line.rstrip("\r\n")
                if not line.strip():
                    continue
                parts = line.split(None, 1)
                ident = parts[0]
                name = parts[1] if len(parts) > 1 else ""
                norm_lines.append(f"{ident}\t{name}")
                line_nums.append(number)
            joined = "\n".join(norm_lines)
            self.raw_block = joined
            self.folded_block = joined.lower()
            self.row_count = len(norm_lines)
            self.line_numbers = tuple(line_nums)

    def _line_for_index(self, index_0: int) -> int:
        if self.line_numbers is not None:
            return self.line_numbers[index_0]
        return index_0 + 1

    def _make_entry(self, start: int, end: int) -> Entry:
        ident, _, name = self.raw_block[start:end].partition("\t")
        index_0 = self.raw_block.count("\n", 0, start)
        return Entry(ident, name, self._line_for_index(index_0))

    @property
    def entries(self) -> tuple[Entry, ...]:
        if self._entries is None:
            if not self.raw_block:
                self._entries = ()
            else:
                lines = self.raw_block.split("\n")
                self._entries = tuple(
                    Entry(
                        *(line.split("\t", 1)),
                        self._line_for_index(idx),
                    )
                    for idx, line in enumerate(lines)
                )
        return self._entries

    def get(self, wanted: str) -> Entry | None:
        if self._by_id is not None:
            return self._by_id.get(wanted)
        if not self.raw_block:
            return None
        prefix = f"{wanted}\t"
        if self.raw_block.startswith(prefix):
            end = self.raw_block.find("\n")
            return self._make_entry(0, len(self.raw_block) if end == -1 else end)
        needle = f"\n{wanted}\t"
        pos = self.raw_block.find(needle)
        if pos == -1:
            return None
        start = pos + 1
        end = self.raw_block.find("\n", start)
        return self._make_entry(start, len(self.raw_block) if end == -1 else end)

    def search(self, query: str, limit: int, offset: int) -> Results[Entry]:
        if not self.raw_block:
            return Results([], 0, query)

        pattern = query.replace(" ", "_").lower()
        if not pattern:
            all_entries = self.entries
            return Results(list(all_entries[offset : offset + limit]), len(all_entries), query)

        tokens = tuple(t for t in _TOKEN_SPLIT_RE.split(pattern) if t)
        seed = tokens[0] if tokens else pattern
        parts = [re.escape(seed[0])]
        for ch in seed[1:]:
            esc = re.escape(ch)
            parts.append(f"[^{esc}\\n]*{esc}")
        parts.append(r"[^\n]*")
        line_re = re.compile("".join(parts))

        folded = self.folded_block
        scored: list[tuple[int, int, int]] = []

        for match in line_re.finditer(folded):
            line_start = folded.rfind("\n", 0, match.start()) + 1
            line_end = match.end()
            fline = folded[line_start:line_end]
            score = _score_precomputed(fline, pattern, tokens)
            if score:
                scored.append((score, line_start, line_end))
        scored.sort(key=lambda item: item[0], reverse=True)
        page = [
            self._make_entry(start, end)
            for _, start, end in scored[offset : offset + limit]
        ]
        return Results(page, len(scored), query)


class Table(RichDisplay):
    """One debug-name table: iteration, exact ID lookup and fuzzy search."""

    def __init__(self, cache: Cache, name: str) -> None:
        self._cache = cache
        self.name = name
        self._loaded: _LoadedTable | None = None

    def __repr__(self) -> str:
        return f"Table({self.name!r})"

    @property
    def path(self) -> Path:
        source = self._cache.path
        if _is_db_file(source):
            return source / _validate_table_name(self.name)
        return _resolve_in_dir(source, self.name)

    @property
    def exists(self) -> bool:
        source = self._cache.path
        if _is_db_file(source):
            try:
                _, manifest = read_header(source)
            except (OSError, ValueError):
                return False
            return self.name in manifest["tables"]
        return _resolve_in_dir(source, self.name).is_file()

    def _load(self) -> _LoadedTable:
        source = self._cache.path
        in_db = _is_db_file(source)
        if in_db:
            _validate_table_name(self.name)
            if not source.is_file():
                raise FileNotFoundError(f"Database not found: {source}")
            file_path = source
        else:
            file_path = _resolve_in_dir(source, self.name)
            if not file_path.is_file():
                raise FileNotFoundError(f"File not found: {file_path}")

        stats = file_path.stat()
        key = (file_path, stats.st_mtime_ns, stats.st_size)
        if self._loaded is not None and self._loaded.key == key:
            return self._loaded

        if in_db:
            try:
                raw_bytes, details = read_table_bytes(source, self.name)
            except KeyError as error:
                raise FileNotFoundError(f"Table not found in {source}: {self.name}") from error
            raw_text = raw_bytes.decode("utf-8", errors="replace")
            size = details["bytes"]
        else:
            raw_text = file_path.read_text(encoding="utf-8", errors="replace")
            size = stats.st_size

        modified, created = _file_times(stats)
        self._loaded = _LoadedTable(
            key=key,
            raw_text=raw_text,
            size=size,
            modified=modified,
            created=created,
            normalized=in_db,
        )
        return self._loaded

    def _db_count(self, source: Path, key: Literal["bytes", "rows"]) -> int:
        _, manifest = read_header(source)
        if self.name not in manifest["tables"]:
            raise FileNotFoundError(f"Table not found: {self.name}")
        return manifest["tables"][self.name][key]

    @property
    def size(self) -> int:
        """Uncompressed size in bytes."""
        source = self._cache.path
        return self._db_count(source, "bytes") if _is_db_file(source) else self._load().size

    @property
    def modified(self) -> datetime:
        return self._load().modified

    @property
    def created(self) -> datetime:
        return self._load().created

    def __iter__(self) -> Iterator[Entry]:
        return iter(self._load().entries)

    def __len__(self) -> int:
        source = self._cache.path
        return self._db_count(source, "rows") if _is_db_file(source) else self._load().row_count

    def get(self, id: int | str) -> Entry:
        """Return the entry with the given ID, e.g. ``data.items.get(4151)``."""
        wanted = str(id)
        found = self._load().get(wanted)
        if found is None:
            raise KeyError(f"No {self.name} entry with id {wanted}")
        return found

    def search(self, query: str, limit: int = 10, offset: int = 0) -> Results[Entry]:
        """Fuzzy name search where spaces match underscores."""
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        validate_int(limit, "limit")
        validate_int(offset, "offset", min_value=0)
        return self._load().search(query, limit, offset)

    def __rich__(self) -> RichTable:
        result = make_table(self.name)
        result.show_header = False
        result.add_column(style="bold cyan")
        result.add_column()
        result.add_row("Entries", format_cell(len(self)))
        result.add_row("Size", Text(f"{self.size:,} bytes"))
        result.add_row("Modified", format_cell(self.modified))
        result.add_row("Path", format_cell(self.path))
        return result


@dataclass(frozen=True, slots=True)
class _KindTable:
    """``Cache`` class attribute that resolves to the table for one ``Kind``."""

    kind: Kind

    @overload
    def __get__(self, cache: None, owner: type[Cache]) -> _KindTable: ...

    @overload
    def __get__(self, cache: Cache, owner: type[Cache]) -> Table: ...

    def __get__(self, cache: Cache | None, owner: type[Cache]) -> _KindTable | Table:
        return self if cache is None else cache.table(self.kind)


class Cache(RichDisplay):
    """Debug names from the bundled ``cache.db``, a downloaded snapshot, or a custom ``path``.

    >>> cache = Cache()
    >>> cache.items.search("abyssal whip")[0]
    Entry(id='4151', name='abyssal_whip')
    """

    varps = _KindTable(Kind.VARPS)
    varbits = _KindTable(Kind.VARBITS)
    interfaces = _KindTable(Kind.INTERFACES)
    inventories = _KindTable(Kind.INVENTORIES)
    locs = _KindTable(Kind.LOCS)
    npcs = _KindTable(Kind.NPCS)
    items = _KindTable(Kind.ITEMS)
    dbrows = _KindTable(Kind.DBROWS)
    animations = _KindTable(Kind.ANIMATIONS)
    sounds = _KindTable(Kind.SOUNDS)
    spotanims = _KindTable(Kind.SPOTANIMS)
    sprites = _KindTable(Kind.SPRITES)
    dbtables = _KindTable(Kind.DBTABLES)

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        cache_dir: str | Path | None = None,
        auto_update: bool = False,
        max_age: float = 86400,
    ) -> None:
        if not isinstance(auto_update, bool):
            raise ValueError("auto_update must be a boolean")
        self._max_age = validate_duration(max_age, "max_age", positive=False)
        if path is not None and (auto_update or cache_dir is not None):
            raise ValueError("path cannot be combined with auto_update or cache_dir")

        self._auto_update = auto_update
        self._bundled = (Path(__file__).parent / DB_FILENAME).resolve()
        self.updater = CacheUpdater(cache_dir=cache_dir) if path is None else None
        active = self.updater.current_path() if self.updater is not None else None
        self._path = Path(path).resolve() if path is not None else (active or self._bundled)
        self._tables: dict[str, Table] = {kind.table: Table(self, kind.table) for kind in Kind}

    def __repr__(self) -> str:
        return f"Cache({str(self._path)!r})"

    @property
    def path(self) -> Path:
        """Active ``cache.db`` or directory, refreshed first when ``auto_update`` is enabled."""
        if self.updater is not None:
            if self._auto_update:
                self.updater.update(max_age=self._max_age)
            self._path = self.updater.current_path() or self._bundled
        return self._path

    def update(self, *, force: bool = True) -> Path:
        """Download the latest OpenRS2 snapshot into ``cache_dir`` and activate it."""
        if self.updater is None:
            raise ValueError("Updates use the managed cache, not a custom path")
        self._path = self.updater.update(force=force, max_age=self._max_age)
        return self._path

    def table(self, name: str | Kind) -> Table:
        """A table by ``Kind``, cache name (``"objtypes"``) or custom file name."""
        if isinstance(name, Kind):
            return self._tables[name.table]
        _validate_table_name(name)
        source = self.path
        if not _is_db_file(source):
            _resolve_in_dir(source, name)
        if name not in self._tables:
            self._tables[name] = Table(self, name)
        return self._tables[name]

    @property
    def tables(self) -> list[Table]:
        """Every table in the active ``cache.db`` or directory, sorted by name."""
        source = self.path
        if _is_db_file(source):
            try:
                _, manifest = read_header(source)
            except (OSError, ValueError):
                return []
            names = list(manifest["tables"])
        elif source.is_dir():
            names = []
            for candidate in source.iterdir():
                try:
                    if _resolve_in_dir(source, candidate.name).is_file():
                        names.append(candidate.name)
                except ValueError:
                    continue
        else:
            return []
        return [self.table(name) for name in sorted(names)]

    def __rich__(self) -> RichTable:
        result = make_table(str(self.path))
        result.add_column("Attribute", style="bold cyan")
        result.add_column("Table")
        result.add_column("Entries", justify="right")
        aliases = {kind.table: kind.value for kind in Kind}
        for found in self.tables:
            result.add_row(aliases.get(found.name, ""), found.name, format_cell(len(found)))
        return result
