import errno

import pytest

from seers import data as default_data
from seers import default_client
from seers.data import Cache, Kind, fuzzy_score


@pytest.fixture
def folder(tmp_path):
    path = tmp_path / "tables"
    path.mkdir()
    return path


@pytest.fixture
def cache(folder):
    return Cache(folder)


def write(folder, name, content):
    (folder / name).write_bytes(content.encode("utf-8"))


def symlink_or_skip(link, target, **kwargs):
    try:
        link.symlink_to(target, **kwargs)
    except OSError as error:
        if getattr(error, "winerror", None) == 1314 or error.errno in (errno.EPERM, errno.EACCES):
            pytest.skip("creating symlinks needs extra privileges here")
        raise


# Fuzzy matching


@pytest.mark.parametrize(("better", "worse", "pattern"), [
    ("twisted_bow", "bow_of_twisted_fate", "twisted_bow"),
    ("bow_of_twisted_fate", "twxisxtexd_bxow", "twisted_bow"),
    ("tzhaar_cape_fire", "tzhaar_cape_of_fire", "cape_fire"),
])
def test_substrings_beat_scattered_words_beat_subsequences(better, worse, pattern):
    assert fuzzy_score(better, pattern) > fuzzy_score(worse, pattern) > 0


@pytest.mark.parametrize(("text", "pattern"), [("Toxic_Blowpipe", "BLOWPIPE"), ("anything", "")])
def test_matching_ignores_case_and_empty_patterns_match_everything(text, pattern):
    assert fuzzy_score(text, pattern) == 100


def test_unrelated_names_score_zero():
    assert fuzzy_score("dragon_claws", "xyz") == 0


# Custom tables


def test_search_ranks_best_first_and_keeps_line_numbers(folder, cache):
    write(folder, "melee.txt",
          "1215\tdragon_dagger\n4587\tdragon_scimitar\n1333\trune_scimitar\n"
          "11335\tdragon_full_helm\n22978\tdragon_scimitar_or\n")
    melee = cache.table("melee.txt")

    first = melee.search("dragon scimitar", limit=2)
    assert [(d.id, d.name, d.line) for d in first] == [("4587", "dragon_scimitar", 2),
                                                       ("22978", "dragon_scimitar_or", 5)]
    assert first.total == 2
    assert [d.line for d in melee.search("dragon scimitar", offset=1)] == [5]
    assert list(melee.search("dragon scimitar", offset=99)) == []



def test_search_matches_unordered_tokens_and_subsequences(folder, cache):
    write(folder, "bows", "1\ttwisted_bow\n2\tbow_of_twisted_fate\n3\ttwxisxtexd_bxow\n4\tshortbow\n")
    results = cache.table("bows").search("twisted bow")
    assert [d.name for d in results] == ["twisted_bow", "bow_of_twisted_fate", "twxisxtexd_bxow"]


def test_kind_attributes_point_at_the_cache_tables(folder, cache):
    write(folder, "objtypes", "13652\tdragon_claws\n13653\tcert_dragon_claws\n")
    items = cache.items

    assert items.name == "objtypes"
    assert len(items) == 2
    assert items.get(13652).name == "dragon_claws"
    assert items.get("13653").name == "cert_dragon_claws"
    assert list(items.search("DRAGON CLAWS")) == list(items.search("dragon_claws"))
    with pytest.raises(KeyError):
        items.get(4151)
    assert items is cache.table(Kind.ITEMS) is cache.table("objtypes")
    assert all(getattr(cache, kind.value) is cache.table(kind) for kind in Kind)


def test_lines_parse_into_ids_and_names(folder, cache):
    write(folder, "mixed.txt", "lonely_name\r\n7   two words\r\n\r\n109:30\tdom_delve_level:boss_hp\n")
    parsed = [(d.id, d.name, d.line) for d in cache.table("mixed.txt")]
    assert parsed == [("lonely_name", "", 1), ("7", "two words", 2), ("109:30", "dom_delve_level:boss_hp", 4)]


@pytest.mark.parametrize("bad", [{"limit": 0}, {"limit": -1}, {"limit": True}, {"limit": 1.5}, {"offset": -1}])
def test_search_rejects_bad_bounds(folder, cache, bad):
    write(folder, "npctypes", "8061\tvorkath\n")
    with pytest.raises(ValueError):
        cache.npcs.search("vorkath", **bad)


@pytest.mark.parametrize("filename", [
    "../objtypes.txt", "..", ".", "", "nested/objtypes.txt", "nested\\objtypes.txt",
    "/tmp/objtypes.txt", "C:\\cache\\objtypes.txt", "C:objtypes.txt", "objtypes.txt:stream",
    "\\\\server\\share\\objtypes.txt", "obj\0types.txt",
])
def test_filenames_cannot_leave_the_folder(cache, filename):
    with pytest.raises(ValueError):
        cache.table(filename)


def test_symlinks_out_of_the_folder_are_refused_and_hidden(tmp_path, folder, cache):
    secret = tmp_path / "bank_pin.txt"
    secret.write_text("1 1234", encoding="utf-8")
    symlink_or_skip(folder / "escape.txt", secret)

    with pytest.raises(ValueError):
        cache.table("escape.txt")
    assert cache.tables == []


def test_missing_files_and_directories_are_not_tables(folder, cache):
    (folder / "folder.txt").mkdir()
    for name in ("missing.txt", "folder.txt"):
        found = cache.table(name)
        assert not found.exists
        with pytest.raises(FileNotFoundError):
            found.search("anything")
    assert cache.tables == []


def test_tables_lists_regular_files_with_their_details(folder, cache):
    for name in ("seqtypes.txt", "notes.csv", "npctypes.txt"):
        write(folder, name, "1")
    (folder / "subfolder.txt").mkdir()

    files = cache.tables
    assert [f.name for f in files] == ["notes.csv", "npctypes.txt", "seqtypes.txt"]
    assert files[1].size == 1
    assert files[1].modified.tzinfo is not None
    assert files[1].created.tzinfo is not None


def test_your_own_folder_is_never_updated(folder, cache):
    with pytest.raises(ValueError):
        cache.update()
    with pytest.raises(ValueError):
        Cache(folder, auto_update=True)
    with pytest.raises(ValueError):
        Cache(folder, cache_dir=folder)


# Bundled snapshot


@pytest.fixture
def bundled(tmp_path):
    return Cache(cache_dir=tmp_path / "empty-cache")


@pytest.mark.parametrize(("kind", "query", "expected"), [
    ("items", "twisted bow", ("20997", "twisted_bow", 20998)),
    ("items", "toxic blowpipe", ("12924", "toxic_blowpipe", 12925)),
    ("items", "bandos chestplate", ("11832", "bandos_chestplate", 11833)),
])
def test_bundled_snapshot_has_real_names(bundled, kind, query, expected):
    found = getattr(bundled, kind).search(query)[0]
    assert (found.id, found.name, found.line) == expected


def test_bundled_snapshot_covers_every_kind(bundled):
    assert bundled.npcs.get(8061).name == "vorkath"
    assert all(len(bundled.table(kind)) > 0 for kind in Kind)


def test_module_attributes_use_the_default_client():
    assert default_data.path == default_client().data.path
    assert default_data.table(Kind.ITEMS) is default_client().data.items
    assert default_data.items.get(13652).name == "dragon_claws"
    with pytest.raises(AttributeError):
        default_data.not_a_kind
