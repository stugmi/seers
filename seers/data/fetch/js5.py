"""Decode the public JS5 archive/index wire format and archive-24 debug names.

Protocol references: OpenRS2 and zwyz/osrs-cache's JS5 format readers. This
implementation reads raw names; it does not synthesize missing game definitions.
"""

import bz2
from dataclasses import dataclass
import gzip
import zlib


GROUPS = {
    "objtypes": 0, "npctypes": 1, "invtypes": 2, "varptypes": 3,
    "varbittypes": 4, "loctypes": 6, "seqtypes": 7, "spottypes": 8,
    "rowtypes": 9, "tabletypes": 10, "soundtypes": 11, "spritetypes": 12,
    "iftypes": 14,
}


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0

    def take(self, size: int) -> bytes:
        end = self.position + size
        if size < 0 or end > len(self.data):
            raise ValueError("Truncated JS5 data")
        value = self.data[self.position:end]
        self.position = end
        return value

    def number(self, size: int, *, signed: bool = False) -> int:
        return int.from_bytes(self.take(size), "big", signed=signed)

    def smart(self) -> int:
        if self.position >= len(self.data):
            raise ValueError("Truncated JS5 index")
        if self.data[self.position] & 0x80:
            return self.number(4) & 0x7fffffff
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
    end = (5 if data[0] == 0 else 9) + int.from_bytes(data[1:5], "big")
    if len(data) not in (end, end + 2):
        raise ValueError("Invalid JS5 container length")
    return end


def decompress(data: bytes) -> bytes:
    """Decode none/bzip2/gzip containers, allowing the two-byte revision suffix."""
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


@dataclass(frozen=True)
class Group:
    file_ids: tuple[int, ...]
    checksum: int
    version: int


def read_index(container: bytes) -> tuple[int, dict[int, Group]]:
    """Read protocols 5–7, including optional name/digest/length metadata."""
    reader = _Reader(decompress(container))
    protocol = reader.number(1)
    if protocol not in (5, 6, 7):
        raise ValueError(f"Unsupported JS5 index protocol: {protocol}")
    revision = reader.number(4) if protocol >= 6 else 0
    flags = reader.number(1)
    if flags & ~15:
        raise ValueError("Unsupported JS5 index flags")
    count = reader.smart if protocol == 7 else lambda: reader.number(2)
    group_count = count()
    group_ids = []
    previous = 0
    for index in range(group_count):
        delta = count()
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
    sizes = [count() for _ in group_ids]
    files = []
    for size in sizes:
        ids = []
        previous = 0
        for index in range(size):
            delta = count()
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
    """Split interleaved chunks using the index's actual (possibly sparse) IDs."""
    end = _container_end(container)
    if zlib.crc32(container[:end]) != group.checksum:
        raise ValueError("JS5 group checksum mismatch")
    if len(container) == end + 2 and int.from_bytes(container[end:], "big") != (group.version & 0xffff):
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
    footer = _Reader(payload[footer_start:-1])
    files = [bytearray() for _ in group.file_ids]
    position = 0
    for _ in range(chunks):
        size = 0
        for file in files:
            size += footer.number(4, signed=True)
            if size < 0 or position + size > footer_start:
                raise ValueError("Invalid JS5 chunk size")
            file.extend(payload[position:position + size])
            position += size
    if position != footer_start:
        raise ValueError("JS5 chunk data length mismatch")
    return dict(zip(group.file_ids, (bytes(file) for file in files)))


def names_text(data_type: str, files: dict[int, bytes]) -> str:
    """Convert internal debug names to the toolkit's ID TAB name text format."""
    rows = []
    for identifier, payload in sorted(files.items()):
        if data_type == "iftypes":
            reader = _Reader(payload)
            name = reader.string()
            seen = set()
            while True:
                component = reader.number(2)
                if component == 0xffff:
                    break
                if component in seen:
                    raise ValueError("Duplicate interface component ID")
                seen.add(component)
                rows.append(f"{identifier}:{component}\t{name}:{reader.string()}")
            reader.finish()
        elif data_type == "tabletypes":
            reader = _Reader(payload)
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
