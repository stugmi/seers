import httpx
import pytest

from seers import OSRSError, PlayerNotFoundError
from seers.hiscores import Mode

SUFFIXES = {mode.suffix: mode.value for mode in Mode}


def table(total_xp, *, name="Bank Stander"):
    payload = {"skills": [{"id": 0, "name": "Overall", "rank": 1520, "level": 2277, "xp": total_xp}],
               "activities": []}
    if name is not None:
        payload["name"] = name
    return payload


@pytest.fixture
def hiscores(make_client):
    """Hiscores backed by a dict of mode -> JSON payload, or an HTTP status for that mode."""
    def build(modes, *, html="", html_status=200):
        def handler(request):
            if request.url.path.endswith("/overall.ws"):
                return httpx.Response(html_status, text=html)
            suffix = request.url.path.split("m=hiscore_oldschool", 1)[1].split("/", 1)[0]
            answer = modes.get(SUFFIXES[suffix], 404)
            return httpx.Response(answer) if isinstance(answer, int) else httpx.Response(200, json=answer)
        return make_client(handler).hiscores
    return build


def test_stats_are_keyed_by_name_not_position(hiscores):
    payload = {
        "skills": [
            {"id": 0, "name": "Sailing", "rank": 8, "level": 42, "xp": 10_000},
            {"id": 999, "name": "Slayer", "rank": 7, "level": 99, "xp": 13_034_431},
            {"id": 13, "name": "Overall", "rank": 3, "level": 2277, "xp": 500},
            {"id": 25, "name": "Some Future Skill", "rank": 20, "level": 2, "xp": 83},
        ],
        "activities": [
            {"id": 0, "name": "Vorkath", "rank": 9, "score": 1_250},
            {"id": 1, "name": "K'ril Tsutsaroth", "rank": 2, "score": 3},
            {"id": 400, "name": "Clue Scrolls (master)", "rank": 4, "score": 12},
            {"id": 2, "name": "LMS - Rank", "rank": 3, "score": 40},
            {"id": 999, "name": "Brand New Boss", "rank": None, "score": None},
        ],
    }
    stats = hiscores({"main": payload}).stats("bank stander")

    assert (stats.player, stats.mode, stats.total_level, stats.total_xp) == ("bank stander", "main", 2277, 500)
    assert stats.skills["slayer"].level == 99
    assert stats.skills["sailing"].xp == 10_000
    assert stats.skills["some_future_skill"].level == 2
    assert stats.bosses["vorkath"].score == 1_250
    assert stats.bosses["kril_tsutsaroth"].score == 3
    assert list(stats.clues) == ["clue_scrolls_master"]
    assert stats.activities["lms_rank"].score == 40

    unknown = stats.activities["brand_new_boss"]
    assert (unknown.rank, unknown.ranked) == (-1, False)
    assert "brand_new_boss" not in stats.bosses


@pytest.mark.parametrize("mode", ["main", "ironman", "hardcore", "ultimate", "deadman", "seasonal"])
def test_stats_reads_exactly_one_table(hiscores, mode):
    stats = hiscores({mode: table(777)}).stats("Bank Stander", mode)
    assert (stats.mode, stats.total_xp) == (mode, 777)
    assert stats.mode is Mode(mode)

    stats_enum = hiscores({mode: table(777)}).stats("Bank Stander", Mode(mode))
    assert stats_enum.mode is Mode(mode)


@pytest.mark.parametrize(("tables", "mode", "hardcore_died", "deulted", "deironed"), [
    ({"main": 100}, "main", False, False, False),
    ({"main": 100, "ironman": 100}, "ironman", False, False, False),
    ({"main": 110, "ironman": 100}, "main", False, False, True),
    ({"main": 100, "ironman": 100, "hardcore": 100}, "hardcore", False, False, False),
    ({"main": 100, "ironman": 100, "hardcore": 90}, "ironman", True, False, False),
    ({"main": 110, "ironman": 100, "hardcore": 90}, "main", True, False, True),
    ({"main": 100, "ironman": 100, "ultimate": 100}, "ultimate", False, False, False),
    ({"main": 100, "ironman": 100, "ultimate": 90}, "ironman", False, True, False),
    ({"main": 110, "ironman": 100, "ultimate": 90}, "main", False, True, True),
])
def test_lookup_works_out_the_account_type(hiscores, tables, mode, hardcore_died, deulted, deironed):
    player = hiscores({key: table(xp) for key, xp in tables.items()}).lookup("bank stander")

    assert (player.name, player.mode) == ("Bank Stander", mode)
    assert player.mode is Mode(mode)
    assert player.mode == mode
    assert (player.hardcore_died, player.deulted, player.deironed) == (hardcore_died, deulted, deironed)
    assert player.total_level == 2277
    assert {key: stats.total_xp for key, stats in player.stats.items()} == tables


def test_hardcore_wins_over_ultimate_but_both_are_kept(hiscores):
    player = hiscores({"main": table(100), "ironman": table(100),
                       "hardcore": table(100), "ultimate": table(90)}).lookup("Bank Stander")
    assert (player.mode, player.deulted) == ("hardcore", False)
    assert player.stats["ultimate"].total_xp == 90


def test_no_ironman_table_means_no_further_iron_lookups(hiscores):
    service = hiscores({"main": table(100), "ironman": 404, "hardcore": 503, "ultimate": 503})
    player = service.lookup("Bank Stander")
    assert (player.mode, list(player.stats)) == ("main", ["main"])
    with pytest.raises(PlayerNotFoundError):
        service.stats("Bank Stander", "ironman")


def test_name_comes_from_json_when_present(hiscores):
    service = hiscores({"main": table(100, name="BaNk StAnDeR")}, html_status=503)
    assert service.lookup("bank stander").name == "BaNk StAnDeR"


@pytest.mark.parametrize(("html", "expected"), [
    ('<tr class="personal-hiscores__row"><td>someone else</td></tr>'
     '<tr class="personal-hiscores__row personal-hiscores__row--type-highlight">'
     '<td>3</td><td><a href="?user=Bank-Stander">BaNk-Stander</a></td></tr>', "BaNk-Stander"),
    ('<tr class="personal-hiscores__row personal-hiscores__row--type-highlight"><td>Bank&nbsp;Stander</td></tr>',
     "Bank Stander"),
    ("<html>no highlighted row</html>", "bank_stander"),
])
def test_name_falls_back_to_the_highlighted_html_row(hiscores, html, expected):
    service = hiscores({"main": table(100, name=None)}, html=html)
    assert service.lookup("bank_stander").name == expected


def test_name_lookup_404_keeps_the_typed_name_but_outages_raise(hiscores):
    assert hiscores({"main": table(100, name=None)}, html_status=404).lookup("bank_stander").name == "bank_stander"
    with pytest.raises(OSRSError, match="HTTP 503"):
        hiscores({"main": table(100, name=None)}, html_status=503).lookup("bank_stander")


def test_unknown_players_are_not_confused_with_outages(hiscores):
    with pytest.raises(PlayerNotFoundError, match="Player not found: Bank Stander"):
        hiscores({"main": 404}).lookup("Bank Stander")
    for tables in ({"main": 503}, {"main": table(100), "ironman": 503},
                   {"main": table(100), "ironman": table(100), "hardcore": 503},
                   {"main": table(100), "ironman": table(100), "ultimate": 503}):
        with pytest.raises(OSRSError, match="HTTP 503") as raised:
            hiscores(tables).lookup("Bank Stander")
        assert not isinstance(raised.value, PlayerNotFoundError)


def test_connection_failures_on_optional_tables_still_raise(make_client):
    def handler(request):
        if "_ironman" in request.url.path:
            raise httpx.ConnectError("ironman hiscores unreachable", request=request)
        return httpx.Response(200, json=table(100))

    with pytest.raises(OSRSError, match="ironman hiscores unreachable"):
        make_client(handler).hiscores.lookup("Bank Stander")


@pytest.mark.parametrize("payload", [
    {},
    {"skills": [], "activities": []},
    {"skills": [{"name": "Overall", "rank": 1, "level": 1, "xp": 0}], "activities": "nope"},
    {"skills": [{"name": "Overall", "xp": "lots"}], "activities": []},
])
def test_malformed_tables_raise(hiscores, payload):
    with pytest.raises(OSRSError, match="Invalid hiscores"):
        hiscores({"main": payload}).stats("Bank Stander")


@pytest.mark.parametrize(("method", "args"), [
    ("lookup", ("",)),
    ("lookup", ("zezima!",)),
    ("lookup", ("a" * 13,)),
    ("stats", ("Bank Stander", "tournament")),
])
def test_bad_names_and_modes_fail_before_any_request(make_client, method, args):
    def forbidden(request):
        pytest.fail(f"unexpected request to {request.url}")

    with pytest.raises(ValueError):
        getattr(make_client(forbidden).hiscores, method)(*args)
