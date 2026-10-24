"""Compact indexed binary store (``SEERSDB\\x01``) for the cache's debug-name tables."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import struct
from typing import Any, TypedDict
import zlib

DB_MAGIC = b"SEERSDB\x01"
PREFIX_STRUCT = struct.Struct(">8sI")
DB_FILENAME = "cache.db"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class TableInfo(TypedDict):
    """Location and checksum of one compressed table block."""

    offset: int
    size: int
    bytes: int
    rows: int
    sha256: str


class Provenance(TypedDict):
    """Where and when a snapshot was downloaded."""

    source: str
    requested_cache_id: int | None
    version: str
    timestamp: float
    updated_at: str
    cache: dict[str, Any]


class Manifest(Provenance):
    """JSON header of a ``cache.db`` file."""

    schema: int
    tables: dict[str, TableInfo]


def format_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def write_store(
    path: Path,
    tables: dict[str, tuple[bytes, int]],
    provenance: Provenance,
    *,
    compression_level: int = 6,
) -> None:
    """Pack definition tables and provenance metadata into a ``SEERSDB\\x01`` file."""
    tables_meta: dict[str, TableInfo] = {}
    blocks: list[bytes] = []
    offset = 0

    for table_name in sorted(tables):
        raw_bytes, row_count = tables[table_name]
        compressed = zlib.compress(raw_bytes, level=compression_level)
        tables_meta[table_name] = {
            "offset": offset,
            "size": len(compressed),
            "bytes": len(raw_bytes),
            "rows": row_count,
            "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        }
        blocks.append(compressed)
        offset += len(compressed)

    manifest = Manifest(schema=1, **provenance, tables=tables_meta)
    header_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    with path.open("wb") as handle:
        handle.write(PREFIX_STRUCT.pack(DB_MAGIC, len(header_bytes)))
        handle.write(header_bytes)
        for block in blocks:
            handle.write(block)
        handle.flush()


def _is_int(value: object, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def read_header(
    path: Path,
    *,
    expected_tables: set[str] | None = None,
) -> tuple[int, Manifest]:
    """Read and validate the ``SEERSDB\\x01`` header and table index."""
    file_size = path.stat().st_size
    if file_size < PREFIX_STRUCT.size:
        raise ValueError("Truncated SEERSDB header")

    with path.open("rb") as handle:
        magic, header_len = PREFIX_STRUCT.unpack(handle.read(PREFIX_STRUCT.size))
        if magic != DB_MAGIC:
            raise ValueError("Invalid SEERSDB magic header")
        body_start = PREFIX_STRUCT.size + header_len
        if header_len <= 0 or body_start > file_size:
            raise ValueError("Invalid SEERSDB header length")
        manifest = json.loads(handle.read(header_len).decode("utf-8"))

        if not isinstance(manifest, dict) or manifest.get("schema") != 1:
            raise ValueError("Unsupported cache manifest")

        timestamp = manifest.get("timestamp")
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, (int, float))
            or not math.isfinite(timestamp)
            or timestamp < 0
        ):
            raise ValueError("Invalid cache timestamp")
        if manifest.get("updated_at") != format_utc(timestamp):
            raise ValueError("Invalid cache update time")
        if not isinstance(manifest.get("source"), str) or not isinstance(manifest.get("version"), str):
            raise ValueError("Invalid cache provenance")
        if not isinstance(manifest.get("cache"), dict):
            raise ValueError("Invalid upstream cache metadata")

        tables = manifest.get("tables")
        if not isinstance(tables, dict) or not tables:
            raise ValueError("Empty SEERSDB table directory")
        if expected_tables is not None and set(tables) != expected_tables:
            raise ValueError("Incomplete SEERSDB table directory")

        total_compressed = 0
        for table_name, details in tables.items():
            if (
                not isinstance(details, dict)
                or not _is_int(details.get("rows"), 1)
                or not _is_int(details.get("offset"), 0)
                or not _is_int(details.get("size"), 1)
                or not _is_int(details.get("bytes"), 1)
                or not isinstance(details.get("sha256"), str)
                or not _SHA256_RE.fullmatch(details["sha256"])
            ):
                raise ValueError(f"Invalid table metadata: {table_name}")
            block_end = body_start + details["offset"] + details["size"]
            if block_end > file_size:
                raise ValueError(f"Truncated table block: {table_name}")
            total_compressed += details["size"]

        if body_start + total_compressed != file_size:
            raise ValueError("SEERSDB file size does not match table directory")

    return body_start, manifest


def read_table_bytes(path: Path, table_name: str) -> tuple[bytes, TableInfo]:
    """Seek directly to ``table_name``'s compressed block and decompress only that table."""
    body_start, manifest = read_header(path)
    tables = manifest["tables"]
    if table_name not in tables:
        raise KeyError(f"Table not found in store: {table_name}")
    details = tables[table_name]
    with path.open("rb") as handle:
        handle.seek(body_start + details["offset"])
        compressed = handle.read(details["size"])
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as error:
        raise ValueError(f"Corrupt table block in {path}: {table_name}") from error
    if len(raw) != details["bytes"]:
        raise ValueError(f"Table length mismatch in {path}: {table_name}")
    return raw, details
