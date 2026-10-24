"""Decode the public JS5 archive/index wire format and archive-24 debug names."""

from __future__ import annotations

import bz2
from dataclasses import dataclass
import gzip
import zlib

from seers.data.kind import Kind


@dataclass(slots=True)
class _BufferReader:
    data: bytes
    position: int = 0

    def take(self, size: int) -> bytes:
        end = self.position + size
        if size < 0 or end > len(self.data):
            raise ValueError("Truncated JS5 data")
        chunk = self.data[self.position : end]
        self.position = end
        return chunk

    def number(self, size: int, *, signed: bool = False) -> int:
        return int.from_bytes(self.take(size), "big", signed=signed)

    def smart(self) -> int:
        if self.position >= len(self.data):
            raise ValueError("Truncated JS5 index")
        if self.data[self.position] & 0x80:
            return self.number(4) & 0x7FFFFFFF
        value = self.number(2)
        if value == 32767:
            raise ValueError("Null JS5 index identifier/count")
        return value

    def string(self) -> str:
        end = self.data.find(b"\0", self.position)
        if end == -1:
            raise ValueError("Unterminated debug name")
        value = self.take(end - self.position).decode("utf-8")
        self.take(1)
        return value

    def finish(self) -> None:
        if self.position != len(self.data):
            raise ValueError("Unexpected trailing JS5 data")


def _container_end(data: bytes) -> int:
    if len(data) < 5:
        raise ValueError("Truncated JS5 container")
    header_size = 5 if data[0] == 0 else 9
    end = header_size + int.from_bytes(data[1:5], "big")
    if len(data) not in (end, end + 2):
        raise ValueError("Invalid JS5 container length")
    return end


def decompress(data: bytes) -> bytes:
    """Decompress a JS5 container (uncompressed, bzip2, or gzip)."""
    end = _container_end(data)
    compression = data[0]
    if compression == 0:
        return data[5:end]

    expected = int.from_bytes(data[5:9], "big")
    payload = data[9:end]
    try:
        if compression == 1:
            result = bz2.decompress(b"BZh1" + payload)
        elif compression == 2:
            result = gzip.decompress(payload)
        else:
            raise ValueError(f"Unsupported JS5 compression type: {compression}")
    except (OSError, EOFError, zlib.error) as error:
        raise ValueError(f"Invalid JS5 compressed payload: {error}") from error

    if len(result) != expected:
        raise ValueError("Invalid JS5 uncompressed length")
    return result


@dataclass(frozen=True, slots=True)
class Group:
    file_ids: tuple[int, ...]
    checksum: int
    version: int


def read_index(container: bytes) -> tuple[int, dict[int, Group]]:
    """Decode JS5 index protocols 5..7."""
    reader = _BufferReader(decompress(container))
    protocol = reader.number(1)
    if protocol not in (5, 6, 7):
        raise ValueError(f"Unsupported JS5 index protocol: {protocol}")

    revision = reader.number(4) if protocol >= 6 else 0
    flags = reader.number(1)
    if flags & ~15:
        raise ValueError("Unsupported JS5 index flags")

    read_count = reader.smart if protocol == 7 else lambda: reader.number(2)
    group_count = read_count()
    group_ids: list[int] = []
    previous = 0
    for index in range(group_count):
        delta = read_count()
        if index and delta == 0:
            raise ValueError("Duplicate JS5 group ID")
        previous += delta
        group_ids.append(previous)

    if flags & 1:
        reader.take(group_count * 4)
    checksums = [reader.number(4) for _ in group_ids]
    if flags & 8:
        reader.take(group_count * 4)
    if flags & 2:
        reader.take(group_count * 64)
    if flags & 4:
        reader.take(group_count * 8)

    versions = [reader.number(4) for _ in group_ids]
    sizes = [read_count() for _ in group_ids]
    files: list[tuple[int, ...]] = []
    for size in sizes:
        ids: list[int] = []
        previous = 0
        for index in range(size):
            delta = read_count()
            if index and delta == 0:
                raise ValueError("Duplicate JS5 file ID")
            previous += delta
            ids.append(previous)
        files.append(tuple(ids))

    if flags & 1:
        reader.take(sum(sizes) * 4)
    reader.finish()

    return revision, {
        identifier: Group(file_ids, checksum, version)
        for identifier, file_ids, checksum, version in zip(group_ids, files, checksums, versions)
    }


def unpack_group(container: bytes, group: Group) -> dict[int, bytes]:
    """Unpack interleaved file chunks using the index's file IDs."""
    end = _container_end(container)
    if zlib.crc32(container[:end]) != group.checksum:
        raise ValueError("JS5 group checksum mismatch")
    if len(container) == end + 2 and int.from_bytes(container[end:], "big") != (group.version & 0xFFFF):
        raise ValueError("JS5 group version mismatch")

    payload = decompress(container)
    count = len(group.file_ids)
    if count == 0:
        raise ValueError("Empty JS5 debug-name group")
    if count == 1:
        return {group.file_ids[0]: payload}
    if not payload:
        raise ValueError("Missing JS5 chunk footer")

    chunks = payload[-1]
    footer_start = len(payload) - 1 - chunks * count * 4
    if not chunks or footer_start < 0:
        raise ValueError("Invalid JS5 chunk footer")

    footer = _BufferReader(payload[footer_start:-1])
    files = [bytearray() for _ in group.file_ids]
    position = 0
    for _ in range(chunks):
        size = 0
        for file_buf in files:
            size += footer.number(4, signed=True)
            if size < 0 or position + size > footer_start:
                raise ValueError("Invalid JS5 chunk size")
            file_buf.extend(payload[position : position + size])
            position += size

    if position != footer_start:
        raise ValueError("JS5 chunk data length mismatch")
    return dict(zip(group.file_ids, (bytes(buf) for buf in files)))


def names_text(kind: Kind, files: dict[int, bytes]) -> str:
    """Convert raw archive-24 debug names into ``ID<TAB>name`` lines."""
    rows: list[str] = []
    for identifier, payload in sorted(files.items()):
        if kind is Kind.INTERFACES:
            reader = _BufferReader(payload)
            name = reader.string()
            seen: set[int] = set()
            while True:
                component = reader.number(2)
                if component == 0xFFFF:
                    break
                if component in seen:
                    raise ValueError("Duplicate interface component ID")
                seen.add(component)
                rows.append(f"{identifier}:{component}\t{name}:{reader.string()}")
            reader.finish()
        elif kind is Kind.DBTABLES:
            reader = _BufferReader(payload)
            present = reader.number(1)
            if present not in (0, 1):
                raise ValueError("Invalid table-name presence flag")
            if present:
                name = reader.string()
                column = 0
                while reader.number(1):
                    rows.append(f"{identifier}:{column}\t{name}:{reader.string()}")
                    column += 1
            reader.finish()
        else:
            rows.append(f"{identifier}\t{payload.decode('utf-8')}")
    return "\n".join(rows) + ("\n" if rows else "")
