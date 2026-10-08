import httpx
import pytest

from seers import Item, OSRSError

from conftest import reply

DRAGON_ITEMS = [
    {"id": 1215, "name": "Dragon dagger", "members": True, "limit": 70},
    {"id": 4587, "name": "Dragon scimitar", "members": True, "limit": 70, "highalch": 60000},
    {"id": 13652, "name": "Dragon claws", "members": True, "limit": 8},
    {"id": 99999, "name": "dragon"},
    {"id": 1333, "name": "Rune scimitar", "limit": 70},
    {"id": 11335, "name": "Dragon full helm", "members": True},
    {"id": 22978, "name": "Sanguine dragon claws"},
]


def mapping_then(handler=None, items=DRAGON_ITEMS):
    """Serve the item list on /mapping and pass anything else to ``handler``."""
    def respond(request):
        if request.url.path.endswith("/mapping"):
            return httpx.Response(200, json=items)
        return handler(request)
    return respond


def test_search_ranks_exact_then_prefix_then_substring(make_client):
    ge = make_client(mapping_then()).ge
    names = [item.name for item in ge.search("DRAGON")]
    assert names == ["dragon", "Dragon claws", "Dragon dagger", "Dragon full helm",
                     "Dragon scimitar", "Sanguine dragon claws"]


def test_search_limit_offset_and_total(make_client):
    ge = make_client(mapping_then()).ge
    page = ge.search("dragon", limit=2, offset=1)

    assert [item.id for item in page] == [13652, 1215]
    assert (len(page), page.total, page.query) == (2, 6, "dragon")
    assert list(ge.search("dragon", offset=50)) == []
    assert ge.search("bronze").total == 0


def test_items_are_typed_and_keep_optional_fields(make_client):
    scimitar = make_client(mapping_then()).ge.item("dragon SCIMITAR")
    assert scimitar == Item(4587, "Dragon scimitar", members=True, limit=70, high_alch=60000)
    assert make_client(mapping_then()).ge.item(1333).members is False


def test_ties_keep_mapping_order(make_client):
    items = [{"id": 1, "name": "Shark"}, {"id": 2, "name": "shark"}, {"id": 3, "name": "Shark lure"}]
    assert [i.id for i in make_client(mapping_then(items=items)).ge.search("shark")] == [1, 2, 3]


def test_item_list_is_fetched_once_until_refresh(make_client):
    state = {"name": "Ranarr weed", "fetches": 0}

    def handler(request):
        state["fetches"] += 1
        return httpx.Response(200, json=[{"id": 257, "name": state["name"]}])

    ge = make_client(handler).ge
    assert ge.search("ranarr")[0].name == "Ranarr weed"
    state["name"] = "Ranarr weed (renamed)"
    assert ge.search("ranarr")[0].name == "Ranarr weed"
    assert state["fetches"] == 1

    ge.refresh()
    assert ge.search("ranarr")[0].name == "Ranarr weed (renamed)"
    assert state["fetches"] == 2


def test_a_broken_item_list_is_not_cached(make_client):
    state = {"payload": {"error": "maintenance"}}
    ge = make_client(lambda request: httpx.Response(200, json=state["payload"])).ge

    with pytest.raises(OSRSError, match="Invalid GE mapping"):
        ge.search("shark")
    state["payload"] = [{"id": 385, "name": "Shark"}]
    assert ge.search("shark")[0].id == 385


def prices(request):
    assert request.url.params["id"] == "13652"
    if request.url.path.endswith("/latest"):
        return httpx.Response(200, json={"data": {"13652": {
            "high": 48_200_000, "highTime": 1759900000, "low": 47_850_000, "lowTime": None}}})
    return httpx.Response(200, json={"data": [
        {"timestamp": 1759800000, "avgHighPrice": 48_100_000, "avgLowPrice": None,
         "highPriceVolume": 41, "lowPriceVolume": 0},
        {"timestamp": 1759886400, "avgHighPrice": 48_300_000, "avgLowPrice": 47_900_000,
         "highPriceVolume": 37, "lowPriceVolume": 52},
    ]})


@pytest.mark.parametrize("reference", [13652, "Dragon claws", "dragon claws"])
def test_price_accepts_an_id_or_a_name(make_client, reference):
    price = make_client(mapping_then(prices)).ge.price(reference)
    assert (price.item_id, price.high, price.low, price.margin) == (13652, 48_200_000, 47_850_000, 350_000)
    assert price.high_time.year == 2025
    assert price.low_time is None


def test_price_only_knows_the_name_when_it_was_looked_up(make_client):
    ge = make_client(mapping_then(prices)).ge
    assert ge.price(13652).name == ""
    assert ge.price(ge.item("Dragon claws")).name == "Dragon claws"


def test_history_is_oldest_first(make_client):
    history = make_client(mapping_then(prices)).ge.history("Dragon claws", "24h")
    assert (history.name, history.timestep, len(history)) == ("Dragon claws", "24h", 2)
    first, latest = history
    assert first.time < latest.time
    assert (first.avg_low, latest.avg_low) == (None, 47_900_000)


def test_unknown_items_and_empty_prices(make_client):
    ge = make_client(mapping_then(reply({"data": {}}))).ge
    with pytest.raises(KeyError):
        ge.item("Bronze 2h of doom")
    assert ge.price(1215).margin is None

    with pytest.raises(OSRSError, match="Invalid GE latest"):
        make_client(reply([])).ge.price(1215)


@pytest.mark.parametrize(("method", "args"), [
    ("search", ("",)),
    ("search", ("shark", 0)),
    ("search", ("shark", True)),
    ("search", ("shark", 10, -1)),
    ("price", (0,)),
    ("price", (1.5,)),
    ("price", (True,)),
    ("history", (385, "10m")),
    ("history", (-1, "5m")),
])
def test_bad_arguments_fail_before_any_request(make_client, method, args):
    def forbidden(request):
        pytest.fail(f"unexpected request to {request.url}")

    with pytest.raises(ValueError):
        getattr(make_client(forbidden).ge, method)(*args)
