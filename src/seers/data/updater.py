"""Download coherent OpenRS2 debug-name snapshots into a binary ``cache.db`` store."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
from uuid import uuid4

import httpx

from seers._compat import fromisoformat
from seers.data.js5 import Group, names_text, read_index, unpack_group
from seers.data.kind import Kind
from seers.data.store import DB_FILENAME, Manifest, Provenance, format_utc, read_header, write_store
from seers.validation import validate_base_url, validate_duration, validate_int

DEFAULT_SOURCE_URL = "https://archive.openrs2.org"
_DEFAULT_USER_AGENT = "seers (+https://github.com/stugmi/seers)"
_EXPECTED_TABLES = frozenset(kind.table for kind in Kind)

_SCOPE_RE = re.compile(r"[A-Za-z0-9_-]+")
_SIMPLE_ID_RE = re.compile(r"[0-9]+")
_COMPOSITE_ID_RE = re.compile(r"[0-9]+:[0-9]+")
_INVALID_NAME_RE = re.compile(r"[\x00-\x1f<>]")


class CacheUpdateError(Exception):
    """A download, decoding, validation or cache publication failed."""


@dataclass(frozen=True, slots=True)
class CacheStatus:
    """Provenance and row counts of the active downloaded snapshot."""

    path: Path
    source: str
    version: str
    updated_at: str
    rows: dict[str, int]
    cache: dict[str, Any]


def _default_cache_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        configured = os.environ.get("XDG_CACHE_HOME")
        base = (
            Path(configured)
            if configured and Path(configured).is_absolute()
            else Path.home() / ".cache"
        )
    return base / "seers"


def _validate_rows(kind: Kind, text: str) -> int:
    rows = text.splitlines()
    if not rows:
        raise ValueError(f"{kind.table}: empty data")
    id_re = _COMPOSITE_ID_RE if kind.composite else _SIMPLE_ID_RE
    seen: set[str] = set()
    for number, line in enumerate(rows, 1):
        identifier, separator, name = line.partition("\t")
        if (
            not separator
            or not id_re.fullmatch(identifier)
            or not name.strip()
            or _INVALID_NAME_RE.search(name)
            or identifier in seen
        ):
            raise ValueError(f"{kind.table}: invalid data on line {number}")
        seen.add(identifier)
    return len(rows)


class CacheUpdater:
    """Download, validate, and atomically publish all 13 OpenRS2 debug-name tables.

    Snapshots are stored as a single indexed binary database (``cache.db``)
    inside ``cache_dir``.
    """

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        *,
        source_url: str | None = None,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
        cache_id: int | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.timeout = validate_duration(timeout, "timeout", positive=True)
        self.source_url = validate_base_url(
            DEFAULT_SOURCE_URL if source_url is None else source_url,
            "source_url",
        )
        if cache_id is not None:
            validate_int(cache_id, "cache_id", min_value=0)
        self.cache_dir = (
            Path(cache_dir).expanduser().resolve()
            if cache_dir is not None
            else _default_cache_dir().resolve()
        )
        self.cache_id = cache_id
        self.user_agent = user_agent or _DEFAULT_USER_AGENT
        self._http_client = http_client

    @property
    def db_path(self) -> Path:
        return self.cache_dir / DB_FILENAME

    def _read_snapshot(self) -> tuple[Path, Manifest] | None:
        db_path = self.db_path
        try:
            if db_path.is_symlink():
                raise ValueError("Cache database must not be a symlink")
            if not db_path.exists():
                return None
            if not db_path.is_file() or db_path.resolve().parent != self.cache_dir:
                raise ValueError("Cache database escapes cache directory")

            _, manifest = read_header(db_path, expected_tables=set(_EXPECTED_TABLES))
            return db_path, manifest
        except (OSError, ValueError, TypeError, OverflowError) as error:
            raise CacheUpdateError(f"Invalid active data cache: {error}") from error

    def current_path(self) -> Path | None:
        """Return the active validated ``cache.db`` path, or ``None`` when no cache exists."""
        snapshot = self._read_snapshot()
        return snapshot[0] if snapshot is not None else None

    def _is_fresh(self, manifest: Manifest, max_age: float) -> bool:
        age = time.time() - manifest["timestamp"]
        return (
            manifest["source"] == self.source_url
            and manifest.get("requested_cache_id") == self.cache_id
            and 0 <= age < max_age
        )

    def is_stale(self, max_age: float = 86400) -> bool:
        """Return True if the cache is missing, older than ``max_age``, or from another source/ID."""
        max_age = validate_duration(max_age, "max_age")
        snapshot = self._read_snapshot()
        return snapshot is None or not self._is_fresh(snapshot[1], max_age)

    def status(self) -> CacheStatus | None:
        """Provenance and row counts of the active snapshot without network access."""
        snapshot = self._read_snapshot()
        if snapshot is None:
            return None
        path, manifest = snapshot
        return CacheStatus(
            path=path,
            source=manifest["source"],
            version=manifest["version"],
            updated_at=manifest["updated_at"],
            rows={name: details["rows"] for name, details in manifest["tables"].items()},
            cache=manifest["cache"],
        )

    def _get(self, client: httpx.Client, path: str) -> httpx.Response:
        response = client.get(
            f"{self.source_url}/{path}",
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        )
        response.raise_for_status()
        return response

    def _select_cache(self, client: httpx.Client) -> dict[str, Any]:
        records = self._get(client, "caches.json").json()
        if not isinstance(records, list):
            raise ValueError("Invalid OpenRS2 cache listing")

        candidates: list[tuple[datetime, int, dict[str, Any]]] = []
        for record in records:
            if (
                not isinstance(record, dict)
                or record.get("game") != "oldschool"
                or record.get("environment") != "live"
                or record.get("language") != "en"
                or record.get("hidden", False)
            ):
                continue
            if self.cache_id is not None and record.get("id") != self.cache_id:
                continue
            if (
                not record.get("disk_store_valid")
                or not record.get("indexes")
                or record.get("valid_indexes") != record["indexes"]
                or not record.get("groups")
                or record.get("valid_groups") != record["groups"]
            ):
                continue

            identifier = record.get("id")
            scope = record.get("scope")
            if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier < 0:
                raise ValueError("Invalid upstream cache ID")
            if not isinstance(scope, str) or not _SCOPE_RE.fullmatch(scope):
                raise ValueError("Unsafe upstream cache scope")
            if self.cache_id is not None:
                return record

            upstream_timestamp = record.get("timestamp")
            if upstream_timestamp is None:
                continue
            if not isinstance(upstream_timestamp, str):
                raise ValueError("Invalid upstream cache timestamp")
            parsed_time = fromisoformat(upstream_timestamp)
            if parsed_time.tzinfo is None:
                raise ValueError("Upstream cache timestamp must include a timezone")
            candidates.append((parsed_time, identifier, record))

        if not candidates:
            raise ValueError("No complete English live Old School cache is available")
        return max(candidates, key=lambda candidate: candidate[:2])[2]

    def _fetch_group(
        self,
        client: httpx.Client,
        prefix: str,
        kind: Kind,
        group: Group,
    ) -> tuple[str, bytes, int]:
        container = self._get(client, f"{prefix}/24/groups/{kind.group}.dat").content
        text = names_text(kind, unpack_group(container, group))
        rows = _validate_rows(kind, text)
        return kind.table, text.encode("utf-8"), rows

    def _download_store(self, client: httpx.Client, staging_db: Path) -> None:
        cache = self._select_cache(client)
        prefix = f"caches/{cache['scope']}/{cache['id']}/archives"
        revision, groups = read_index(self._get(client, f"{prefix}/255/groups/24.dat").content)
        if not all(kind.group in groups and groups[kind.group].file_ids for kind in Kind):
            raise ValueError("Selected cache lacks a complete archive-24 debug-name index")

        with ThreadPoolExecutor(max_workers=len(Kind)) as pool:
            futures = [
                pool.submit(self._fetch_group, client, prefix, kind, groups[kind.group])
                for kind in Kind
            ]
            results = [future.result() for future in futures]

        tables = {name: (data, rows) for name, data, rows in results}
        timestamp = time.time()
        provenance = Provenance(
            source=self.source_url,
            requested_cache_id=self.cache_id,
            version=f"{cache['scope']}:{cache['id']}:24:{revision}",
            timestamp=timestamp,
            updated_at=format_utc(timestamp),
            cache={key: cache.get(key) for key in ("id", "scope", "builds", "timestamp", "sources")},
        )
        write_store(staging_db, tables, provenance)

    def update(self, *, force: bool = False, max_age: float = 86400) -> Path:
        """Download, validate, and atomically publish a ``cache.db`` snapshot."""
        max_age = validate_duration(max_age, "max_age")
        if not force:
            snapshot = self._read_snapshot()
            if snapshot is not None and self._is_fresh(snapshot[1], max_age):
                return snapshot[0]

        token = uuid4().hex
        staging_db = self.cache_dir / f".cache-{token}.db"

        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            if self.db_path.is_symlink():
                raise ValueError("Cache database must not be a symlink")

            context = (
                nullcontext(self._http_client)
                if self._http_client is not None
                else httpx.Client(follow_redirects=True)
            )
            with context as client:
                self._download_store(client, staging_db)

            os.replace(staging_db, self.db_path)
            return self.db_path
        except (
            httpx.HTTPError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
            OverflowError,
            EOFError,
        ) as error:
            raise CacheUpdateError(f"Unable to update OSRS data: {error}") from error
        finally:
            if staging_db.exists():
                staging_db.unlink()
