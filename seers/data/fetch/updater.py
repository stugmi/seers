"""Download coherent OpenRS2 debug-name snapshots into a user-owned cache."""

from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from ...version import USER_AGENT
from .js5 import GROUPS, names_text, read_index, unpack_group


# The 13 definition files decoded from archive 24's debug names.
DATA_TYPES = (
    "varptypes", "varbittypes", "iftypes", "invtypes", "loctypes", "npctypes",
    "objtypes", "rowtypes", "seqtypes", "soundtypes", "spottypes", "spritetypes",
    "tabletypes",
)


DEFAULT_SOURCE_URL = "https://archive.openrs2.org"


class DataUpdateError(Exception):
    """A download, decoding, validation or cache publication failed."""


def _duration(value: float, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def _default_cache_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif os.sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        configured = os.environ.get("XDG_CACHE_HOME")
        base = Path(configured) if configured and Path(configured).is_absolute() else Path.home() / ".cache"
    return base / "seers"


def _utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_text(data_type: str, content: bytes) -> int:
    text = content.decode("utf-8")
    rows = text.splitlines()
    if not rows:
        raise ValueError(f"{data_type}: empty data")
    identifier_pattern = r"[0-9]+:[0-9]+" if data_type in ("iftypes", "tabletypes") else r"[0-9]+"
    seen = set()
    for number, line in enumerate(rows, 1):
        identifier, separator, name = line.partition("\t")
        if (
            not separator or not re.fullmatch(identifier_pattern, identifier)
            or not name.strip() or any(ord(character) < 32 for character in name)
            or "<" in name or ">" in name or identifier in seen
        ):
            raise ValueError(f"{data_type}: invalid data on line {number}")
        seen.add(identifier)
    return len(rows)


class DataUpdater:
    """Publish all thirteen name mappings together; library methods print nothing.

    ``source_url`` is an OpenRS2-compatible API root. ``cache_id`` pins an
    upstream cache; otherwise the newest complete English live OSRS cache is
    selected by timestamp. Injected HTTP clients remain owned by the caller.
    """

    def __init__(
        self,
        cache_dir: Path | str | None = None,
        *,
        source_url: str | None = None,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
        cache_id: int | None = None,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.timeout = _duration(timeout, "timeout", positive=True)
        source_url = DEFAULT_SOURCE_URL if source_url is None else source_url
        if not isinstance(source_url, str):
            raise ValueError("source_url must be an absolute HTTP(S) URL")
        try:
            parts = urlsplit(source_url)
            valid = parts.scheme in ("http", "https") and parts.hostname and not parts.query and not parts.fragment
            parts.port
        except ValueError as error:
            raise ValueError("source_url must be an absolute HTTP(S) URL") from error
        if not valid or parts.username is not None or parts.password is not None or any(character.isspace() for character in source_url):
            raise ValueError("source_url must be an absolute HTTP(S) API root without credentials/query/fragment")
        if cache_id is not None and (isinstance(cache_id, bool) or not isinstance(cache_id, int) or cache_id < 0):
            raise ValueError("cache_id must be a nonnegative integer or None")
        self.source_url = source_url.rstrip("/")
        self.cache_dir = Path(cache_dir).expanduser().resolve() if cache_dir is not None else _default_cache_dir().resolve()
        self.cache_id = cache_id
        self.user_agent = user_agent
        self._http_client = http_client

    def _snapshot(self) -> tuple[Path, dict[str, Any]] | None:
        pointer = self.cache_dir / "active.json"
        try:
            if pointer.is_symlink():
                raise ValueError("Cache manifest must not be a symlink")
            try:
                content = pointer.read_text(encoding="utf-8")
            except FileNotFoundError:
                return None
            manifest = json.loads(content)
            if not isinstance(manifest, dict) or manifest.get("schema") != 1:
                raise ValueError("Unsupported cache manifest")
            snapshot = manifest.get("snapshot")
            if not isinstance(snapshot, str) or not re.fullmatch(r"[0-9a-f]{32}", snapshot):
                raise ValueError("Unsafe snapshot pointer")
            snapshots = self.cache_dir / "snapshots"
            path = snapshots / snapshot
            if snapshots.is_symlink() or snapshots.resolve() != snapshots or path.is_symlink() or path.resolve().parent != snapshots:
                raise ValueError("Snapshot path escapes cache directory")
            timestamp = manifest.get("timestamp")
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp < 0:
                raise ValueError("Invalid cache timestamp")
            if manifest.get("updated_at") != _utc(timestamp):
                raise ValueError("Invalid cache update time")
            if not isinstance(manifest.get("source"), str) or not isinstance(manifest.get("version"), str):
                raise ValueError("Invalid cache provenance")
            if not isinstance(manifest.get("cache"), dict):
                raise ValueError("Invalid upstream cache metadata")
            metadata = manifest.get("files")
            if not isinstance(metadata, dict) or set(metadata) != {f"{name}.txt" for name in DATA_TYPES}:
                raise ValueError("Incomplete cache manifest")
            for name in DATA_TYPES:
                file = path / f"{name}.txt"
                if file.is_symlink() or file.resolve().parent != path or not file.is_file():
                    raise ValueError(f"Unsafe or missing snapshot file: {file.name}")
                details = metadata[file.name]
                if (
                    not isinstance(details, dict)
                    or isinstance(details.get("rows"), bool)
                    or not isinstance(details.get("rows"), int) or details["rows"] <= 0
                    or details.get("bytes") != file.stat().st_size
                    or not isinstance(details.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", details["sha256"])
                ):
                    raise ValueError(f"Snapshot metadata mismatch: {file.name}")
            return path, manifest
        except (OSError, ValueError, TypeError, OverflowError) as error:
            raise DataUpdateError(f"Invalid active data cache: {error}") from error

    def current_data_dir(self) -> Path | None:
        """Return a complete validated snapshot, or None when no cache exists."""
        snapshot = self._snapshot()
        return snapshot[0] if snapshot is not None else None

    def _fresh(self, manifest: dict[str, Any], max_age: float) -> bool:
        age = time.time() - manifest["timestamp"]
        return (
            manifest["source"] == self.source_url
            and manifest.get("requested_cache_id") == self.cache_id
            and 0 <= age < max_age
        )

    def is_stale(self, max_age: float = 86400) -> bool:
        """Account for TTL and configured source/cache-ID changes across instances."""
        max_age = _duration(max_age, "max_age")
        snapshot = self._snapshot()
        return snapshot is None or not self._fresh(snapshot[1], max_age)

    def status(self) -> dict[str, Any]:
        """Return persisted provenance and record counts without network access."""
        snapshot = self._snapshot()
        if snapshot is None:
            return {"available": False, "source": self.source_url, "path": None,
                    "version": None, "updated_at": None, "rows": {}}
        path, manifest = snapshot
        return {
            "available": True, "source": manifest["source"], "path": str(path),
            "version": manifest["version"], "updated_at": manifest["updated_at"],
            "rows": {name: details["rows"] for name, details in manifest["files"].items()},
            "cache": manifest["cache"],
        }

    def _get(self, client: httpx.Client, path: str) -> httpx.Response:
        response = client.get(f"{self.source_url}/{path}", timeout=self.timeout,
                              headers={"User-Agent": self.user_agent}, follow_redirects=True)
        response.raise_for_status()
        return response

    def _select_cache(self, client: httpx.Client) -> dict[str, Any]:
        records = self._get(client, "caches.json").json()
        if not isinstance(records, list):
            raise ValueError("Invalid OpenRS2 cache listing")
        candidates = []
        for record in records:
            if not isinstance(record, dict) or any(record.get(key) != value for key, value in (
                ("game", "oldschool"), ("environment", "live"), ("language", "en")
            )) or record.get("hidden", False):
                continue
            if self.cache_id is not None and record.get("id") != self.cache_id:
                continue
            if (
                not record.get("disk_store_valid")
                or not record.get("indexes") or record.get("valid_indexes") != record["indexes"]
                or not record.get("groups") or record.get("valid_groups") != record["groups"]
            ):
                continue
            identifier, scope = record.get("id"), record.get("scope")
            if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier < 0:
                raise ValueError("Invalid upstream cache ID")
            if not isinstance(scope, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", scope):
                raise ValueError("Unsafe upstream cache scope")
            if self.cache_id is not None:
                return record
            upstream_timestamp = record.get("timestamp")
            # OpenRS2 also archives undated caches; they cannot be ranked as latest.
            if upstream_timestamp is None:
                continue
            if not isinstance(upstream_timestamp, str):
                raise ValueError("Invalid upstream cache timestamp")
            timestamp = datetime.fromisoformat(upstream_timestamp.replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("Upstream cache timestamp must include a timezone")
            candidates.append((timestamp, identifier, record))
        if not candidates:
            raise ValueError("No complete English live Old School cache is available")
        return max(candidates, key=lambda candidate: candidate[:2])[2]

    def _download(self, client: httpx.Client, staging: Path) -> dict[str, Any]:
        cache = self._select_cache(client)
        prefix = f"caches/{cache['scope']}/{cache['id']}/archives"
        revision, groups = read_index(self._get(client, f"{prefix}/255/groups/24.dat").content)
        if not all(group in groups and groups[group].file_ids for group in GROUPS.values()):
            raise ValueError("Selected cache lacks a complete archive-24 debug-name index")
        files = {}
        for name in DATA_TYPES:
            group_id = GROUPS[name]
            container = self._get(client, f"{prefix}/24/groups/{group_id}.dat").content
            data = names_text(name, unpack_group(container, groups[group_id])).encode("utf-8")
            rows = _validate_text(name, data)
            filename = f"{name}.txt"
            (staging / filename).write_bytes(data)
            files[filename] = {"rows": rows, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        timestamp = time.time()
        return {
            "schema": 1, "source": self.source_url,
            "requested_cache_id": self.cache_id,
            "version": f"{cache['scope']}:{cache['id']}:24:{revision}",
            "timestamp": timestamp, "updated_at": _utc(timestamp), "files": files,
            "cache": {key: cache.get(key) for key in ("id", "scope", "builds", "timestamp", "sources")},
        }

    def update(self, *, force: bool = False, max_age: float = 86400) -> Path:
        """Publish one immutable snapshot only after every mapping is validated.

        Failures preserve the previous manifest, timestamp and snapshot. Force
        refresh also permits repairing a corrupt manifest without trusting it.
        """
        max_age = _duration(max_age, "max_age")
        if not force:
            snapshot = self._snapshot()
            if snapshot is not None and self._fresh(snapshot[1], max_age):
                return snapshot[0]
        token = uuid4().hex
        staging = self.cache_dir / f".staging-{token}"
        snapshots = self.cache_dir / "snapshots"
        target = snapshots / token
        pointer_temp = self.cache_dir / f".active-{token}.json"
        published = False
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            if snapshots.is_symlink() or snapshots.resolve() != snapshots:
                raise ValueError("Snapshot directory escapes cache directory")
            snapshots.mkdir(exist_ok=True)
            staging.mkdir()
            context = nullcontext(self._http_client) if self._http_client is not None else httpx.Client()
            with context as client:
                manifest = self._download(client, staging)
            manifest["snapshot"] = token
            staging.rename(target)
            with pointer_temp.open("x", encoding="utf-8", newline="\n") as file:
                json.dump(manifest, file, ensure_ascii=False, indent=2, allow_nan=False)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(pointer_temp, self.cache_dir / "active.json")
            published = True
            return target
        except (httpx.HTTPError, OSError, ValueError, TypeError, KeyError, OverflowError, EOFError) as error:
            raise DataUpdateError(f"Unable to update OSRS data: {error}") from error
        finally:
            if staging.exists():
                shutil.rmtree(staging)
            if pointer_temp.exists():
                pointer_temp.unlink()
            if not published and target.exists():
                shutil.rmtree(target)


