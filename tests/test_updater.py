"""The OpenRS2 downloader and JS5 decoder, against a fake archive server."""

import bz2
import gzip
import json
import struct
import threading
from unittest.mock import patch
import zlib

import httpx
import pytest

from seers import Cache
from seers.data import Kind
from seers.data.js5 import decompress, read_index, unpack_group
from seers.data.store import DB_FILENAME, read_header, read_table_bytes, write_store
from seers.data.updater import CacheUpdateError, CacheUpdater
from test_cache import symlink_or_skip

CLOCK = "seers.data.updater.time.time"
GROUPS = {kind.table: kind.group for kind in Kind}


def container(payload, compression=0):
    if compression == 0:
        return b"\0" + struct.pack(">I", len(payload)) + payload
    encoded = bz2.compress(payload, compresslevel=1)[4:] if compression == 1 else gzip.compress(payload)
    return bytes([compression]) + struct.pack(">II", len(encoded), len(payload)) + encoded


def chunked(files):
    """Two chunks, unequal file lengths and signed footer deltas."""
    payload, footer = bytearray(), bytearray()
    for chunk in range(2):
        previous = 0
        for file in files:
            middle = len(file) // 2
            part = file[:middle] if chunk == 0 else file[middle:]
            payload.extend(part)
            footer.extend(struct.pack(">i", len(part) - previous))
            previous = len(part)
    return bytes(payload + footer + b"\x02")


def index_container(groups, protocol=7, flags=0):
    def number(value):
        if protocol >= 7 and value >= 32767:
            return struct.pack(">I", value | 0x80000000)
        return struct.pack(">H", value)

    ids = sorted(groups)
    output = bytearray([protocol])
    if protocol >= 6:
        output.extend(struct.pack(">I", 19))
    output.append(flags)
    output.extend(number(len(ids)))
    previous = 0
    for identifier in ids:
        output.extend(number(identifier - previous))
        previous = identifier
    if flags & 1:
        output.extend(b"\0" * (4 * len(ids)))
    for identifier in ids:
        output.extend(struct.pack(">I", zlib.crc32(groups[identifier][1])))
    if flags & 8:
        output.extend(b"\0" * (4 * len(ids)))
    if flags & 2:
        output.extend(b"\0" * (64 * len(ids)))
    if flags & 4:
        output.extend(b"\0" * (8 * len(ids)))
    output.extend(struct.pack(">I", 1) * len(ids))
    for identifier in ids:
        output.extend(number(len(groups[identifier][0])))
    for identifier in ids:
        previous = 0
        for file_id in groups[identifier][0]:
            output.extend(number(file_id - previous))
            previous = file_id
    if flags & 1:
        output.extend(b"\0" * (4 * sum(len(groups[identifier][0]) for identifier in ids)))
    return container(bytes(output), 2)


def archive_groups(tag):
    """Every definition group with two names containing ``tag`` (and a non-ASCII character)."""
    groups = {}
    for name, identifier in GROUPS.items():
        payloads = []
        for file_id in (3, 9):
            value = f"{name}_café_{tag}_{file_id}".encode()
            if name == "iftypes":
                value += b"\0\0\0first\0\x01\xffsecond\0\xff\xff"
            elif name == "tabletypes":
                value = b"\x01" + value + b"\0\x01first\0\x02second\0\0"
            payloads.append(value)
        groups[identifier] = ((3, 9), container(chunked(payloads), identifier % 3))
    return groups


class FakeOpenRS2:
    """Serves caches.json, the archive 24 index and its groups like archive.openrs2.org."""

    def __init__(self):
        self.groups = archive_groups("old")
        self.requests = []
        self._lock = threading.Lock()
        self.failing_group = None
        self.body_override = None
        self.on_request = None
        self.records = [{
            "id": 77, "scope": "runescape", "game": "oldschool",
            "environment": "live", "language": "en", "builds": [{"major": 241}],
            "timestamp": "2026-10-07T10:45:05Z", "sources": ["Jagex", "测试"],
            "indexes": 25, "valid_indexes": 25, "groups": 100, "valid_groups": 100,
            "disk_store_valid": True, "hidden": False,
        }]

    def replace_group(self, name, payload):
        self.groups[GROUPS[name]] = ((3,), container(payload))

    def __call__(self, request):
        with self._lock:
            self.requests.append(request)
            if self.on_request is not None:
                self.on_request()
        path = request.url.path
        if path == "/caches.json":
            return httpx.Response(200, json=self.records)
        prefix = "/caches/runescape/77/archives/"
        if path == prefix + "255/groups/24.dat":
            return httpx.Response(200, content=index_container(self.groups))
        if path.startswith(prefix + "24/groups/"):
            identifier = int(path.rsplit("/", 1)[1].removesuffix(".dat"))
            if identifier == self.failing_group:
                return httpx.Response(503, text="temporarily unavailable")
            if self.body_override is not None:
                return httpx.Response(200, content=self.body_override)
            return httpx.Response(200, content=self.groups[identifier][1])
        return httpx.Response(404)


@pytest.fixture
def server():
    return FakeOpenRS2()


@pytest.fixture
def http(server):
    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        yield client


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "cache"


@pytest.fixture
def make_updater(cache, http):
    def make(**options):
        return CacheUpdater(cache, source_url="https://cache.example", http_client=http, **options)
    return make


@pytest.fixture
def updater(make_updater):
    return make_updater()


def publish(updater, at=1_000_000, **options):
    with patch(CLOCK, return_value=at):
        return updater.update(**options)


def read_store_entry(db_path, filename):
    raw, _ = read_table_bytes(db_path, filename)
    return raw.decode("utf-8")


def snapshot_files(db_path):
    _, manifest = read_header(db_path)
    return {name: read_table_bytes(db_path, name)[0] for name in manifest["tables"]}

# JS5 decoding


@pytest.mark.parametrize("protocol", [5, 6, 7])
@pytest.mark.parametrize("flags", [0, 1, 15])
def test_index_and_groups_decode_for_every_protocol_and_compression(protocol, flags):
    groups = archive_groups("old")
    revision, index = read_index(index_container(groups, protocol, flags))

    assert revision == (19 if protocol >= 6 else 0)
    assert index[0].file_ids == (3, 9)
    for name in ("objtypes", "npctypes", "invtypes"):
        group_id = GROUPS[name]
        files = unpack_group(groups[group_id][1] + b"\0\x01", index[group_id])
        assert (files[3].decode(), files[9].decode()) == (f"{name}_café_old_3", f"{name}_café_old_9")


def test_large_sparse_file_ids():
    _, index = read_index(index_container({14: ((40000,), container(b"name"))}))
    assert index[14].file_ids == (40000,)


def test_corrupt_groups_and_containers_are_rejected():
    groups = archive_groups("old")
    _, index = read_index(index_container(groups))
    with pytest.raises(ValueError):
        unpack_group(groups[0][1][:-1] + b"x", index[0])

    broken = {0: ((3, 9), container(b"\xff"))}
    _, broken_index = read_index(index_container(broken))
    with pytest.raises(ValueError):
        unpack_group(broken[0][1], broken_index[0])

    for data in (b"<html>error</html>", b"\x02\0\0\0\x01\0\0\0\x05x"):
        with pytest.raises(ValueError):
            decompress(data)


# Choosing a cache


def test_undated_caches_are_skipped_unless_pinned(server, updater, make_updater):
    dated = server.records[0]
    undated = {**dated, "id": 9999, "timestamp": None}
    server.records = [undated, dated]
    selected = publish(updater)
    assert updater.status().cache["id"] == 77

    server.records = [undated]
    with pytest.raises(CacheUpdateError):
        publish(updater, force=True)
    assert updater.current_path() == selected

    server.records = [{**dated, "timestamp": None}]
    pinned = make_updater(cache_id=77)
    pinned.update(force=True)
    assert pinned.status().cache["id"] == 77
    assert pinned.status().cache["timestamp"] is None


def test_newest_complete_live_cache_wins(server, updater, make_updater):
    base = server.records[0]
    server.records += [
        dict(base, id=999, timestamp="2026-10-01T00:00:00Z"),
        dict(base, id=888, timestamp="2026-10-08T00:00:00Z", valid_groups=99),
        dict(base, id=777, game="runescape"),
    ]
    publish(updater)
    assert updater.status().cache["id"] == 77
    with pytest.raises(CacheUpdateError):
        make_updater(cache_id=888).update(force=True)


# Freshness


def test_freshness_is_shared_between_updater_instances(server, updater, make_updater):
    assert updater.current_path() is None
    assert updater.is_stale()
    assert updater.status() is None

    first = publish(updater)
    requests = len(server.requests)
    other = make_updater()
    with patch(CLOCK, return_value=1_000_010):
        assert not other.is_stale(max_age=60)
        assert other.update(max_age=60) == first
    assert len(server.requests) == requests

    with patch(CLOCK, return_value=1_000_060):
        assert other.is_stale(max_age=60)
        newer = other.update(max_age=60)
    assert newer == first and other.current_path() == newer
    assert first.is_file()


def test_changing_source_or_pin_counts_as_stale(cache, http, updater, make_updater):
    publish(updater)
    elsewhere = CacheUpdater(cache, source_url="https://mirror.example", http_client=http)
    pinned = make_updater(cache_id=77)
    with patch(CLOCK, return_value=1_000_001):
        assert elsewhere.is_stale()
        elsewhere.update()
        assert elsewhere.status().source == "https://mirror.example"
        assert pinned.is_stale()
        pinned.update()
        assert not pinned.is_stale()
    assert pinned.status().cache["id"] == 77


def test_cache_refreshes_lazily_on_its_own_schedule(server, cache, updater):
    with patch("seers.data.cache.CacheUpdater", return_value=updater):
        automatic = Cache(cache_dir=cache, auto_update=True, max_age=60)
        offline = Cache(cache_dir=cache)
    assert server.requests == []

    with patch(CLOCK, return_value=1_000_000):
        assert len(automatic.items.search("café_old")) == 2
    requests = len(server.requests)
    with patch(CLOCK, return_value=1_000_010):
        assert len(automatic.items.search("café_old")) == 2
    assert len(server.requests) == requests

    server.groups = archive_groups("new")
    with patch(CLOCK, return_value=1_000_060):
        assert len(automatic.items.search("café_new")) == 2
    requests = len(server.requests)
    assert len(offline.items.search("café_new")) == 2
    assert len(server.requests) == requests
    assert automatic.path == offline.path


# Publishing safely


def test_readers_see_the_old_snapshot_until_the_new_one_is_complete(server, updater, make_updater):
    old = publish(updater)
    server.groups = archive_groups("new")
    seen = []
    server.on_request = lambda: seen.append(read_store_entry(make_updater().current_path(), "objtypes"))

    new = publish(updater, at=1_000_001, force=True)

    assert all("café_old" in content for content in seen)
    assert make_updater().current_path() == new == old
    assert "café_new" in read_store_entry(new, "objtypes")


def test_a_failed_download_leaves_everything_as_it_was(server, cache, updater):
    old = publish(updater)
    db_bytes = (cache / DB_FILENAME).read_bytes()
    files = snapshot_files(old)
    server.failing_group = GROUPS["objtypes"]

    with pytest.raises(CacheUpdateError):
        publish(updater, at=1_000_100, force=True)

    assert (cache / DB_FILENAME).read_bytes() == db_bytes
    assert updater.current_path() == old
    assert snapshot_files(old) == files
    assert {entry.name for entry in cache.iterdir()} == {DB_FILENAME}


@pytest.mark.parametrize("bad_names", [b"<html>error</html>", b"\xff", b"", b"line\nnext", b"tab\tname", b"null\0name"])
def test_garbage_names_are_never_published(server, cache, updater, bad_names):
    old = publish(updater)
    db_bytes = (cache / DB_FILENAME).read_bytes()
    server.replace_group("objtypes", bad_names)

    with pytest.raises(CacheUpdateError):
        publish(updater, at=1_000_200, force=True)
    assert (cache / DB_FILENAME).read_bytes() == db_bytes
    assert updater.current_path() == old


def test_html_error_pages_are_never_published(server, cache, updater):
    publish(updater)
    db_bytes = (cache / DB_FILENAME).read_bytes()
    server.body_override = b"<!doctype html><html>bad gateway</html>"
    with pytest.raises(CacheUpdateError):
        publish(updater, force=True)
    assert (cache / DB_FILENAME).read_bytes() == db_bytes


def test_an_incomplete_first_download_publishes_nothing(server, cache, updater):
    del server.groups[GROUPS["soundtypes"]]
    with pytest.raises(CacheUpdateError):
        publish(updater)
    assert updater.current_path() is None
    assert not (cache / DB_FILENAME).exists()


def test_a_failed_store_swap_keeps_the_previous_snapshot(cache, updater):
    old = publish(updater)
    db_bytes = (cache / DB_FILENAME).read_bytes()
    with patch("seers.data.updater.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(CacheUpdateError):
            publish(updater, at=1_000_300, force=True)
    assert (cache / DB_FILENAME).read_bytes() == db_bytes
    assert updater.current_path() == old
    assert {entry.name for entry in cache.iterdir()} == {DB_FILENAME}


def test_snapshot_contents_and_request_headers(server, cache, http, make_updater):
    updater = make_updater(user_agent="seers-tests/1")
    path = publish(updater)
    status = updater.status()

    assert set(status.rows) == set(GROUPS)
    for kind in Kind:
        assert status.rows[kind.table] == (4 if kind.composite else 2)
        assert "café" in read_store_entry(path, kind.table)
    assert "3:511\tiftypes_café_old_3:second" in read_store_entry(path, "iftypes")
    assert "9:1\ttabletypes_café_old_9:second" in read_store_entry(path, "tabletypes")

    _, manifest = read_header(path)
    assert manifest["timestamp"] == 1_000_000
    assert "测试" in json.dumps(manifest, ensure_ascii=False)
    assert status.updated_at.endswith("Z")
    assert {request.headers["User-Agent"] for request in server.requests} == {"seers-tests/1"}
    assert not http.is_closed


@pytest.mark.parametrize("failing_group", [None, GROUPS["objtypes"]])
def test_an_owned_http_client_is_always_closed(server, cache, failing_group):
    server.failing_group = failing_group
    owned = httpx.Client(transport=httpx.MockTransport(server))
    updater = CacheUpdater(cache, source_url="https://cache.example")
    with patch("seers.data.updater.httpx.Client", return_value=owned):
        if failing_group is None:
            updater.update(force=True)
        else:
            with pytest.raises(CacheUpdateError):
                updater.update(force=True)
    assert owned.is_closed


# Tampered caches


def test_corrupt_store_or_missing_tables_are_never_used(cache, updater):
    publish(updater)
    db_path = cache / DB_FILENAME
    db_path.write_text("not-a-seersdb", encoding="utf-8")
    with pytest.raises(CacheUpdateError):
        updater.is_stale()

    repaired = publish(updater, at=1_000_100, force=True)
    assert updater.current_path() == repaired

    # Remove soundtypes from the binary store
    _, manifest = read_header(repaired)
    entries = {
        name: (read_table_bytes(repaired, name)[0], details["rows"])
        for name, details in manifest["tables"].items()
        if name != "soundtypes"
    }
    provenance = {k: v for k, v in manifest.items() if k not in ("schema", "tables")}
    write_store(repaired, entries, provenance)

    with pytest.raises(CacheUpdateError):
        updater.current_path()


def test_symlinked_store_is_refused(tmp_path, cache, updater):
    publish(updater)
    outside = tmp_path / "outside.db"
    outside.write_bytes((cache / DB_FILENAME).read_bytes())
    (cache / DB_FILENAME).unlink()
    symlink_or_skip(cache / DB_FILENAME, outside)

    with pytest.raises(CacheUpdateError):
        updater.current_path()
    with pytest.raises(CacheUpdateError):
        publish(updater, force=True)


# Arguments


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "30"])
def test_durations_must_be_finite_numbers(make_updater, updater, value):
    with pytest.raises(ValueError):
        make_updater(timeout=value)
    with pytest.raises(ValueError):
        updater.is_stale(max_age=value)
    with pytest.raises(ValueError):
        updater.update(max_age=value)


def test_zero_timeout_is_refused_but_zero_max_age_means_always_stale(make_updater, updater):
    with pytest.raises(ValueError):
        make_updater(timeout=0)
    publish(updater)
    with patch(CLOCK, return_value=1_000_000):
        assert updater.is_stale(max_age=0)


@pytest.mark.parametrize("source", ["relative", "file:///tmp/data", "https://", "https://host?x=1",
                                    "https://host/#x", "https://user@host", "https://host bad"])
def test_source_must_be_a_plain_absolute_url(cache, source):
    with pytest.raises(ValueError):
        CacheUpdater(cache, source_url=source)
