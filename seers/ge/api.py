"""Client for the Wiki's real-time prices API (prices.runescape.wiki)."""

from typing import TYPE_CHECKING, Literal

from ..display import Results
from ..errors import OSRSError
from ..validation import integer, string
from .models import Item, Price, PriceHistory, PricePoint, from_timestamp

if TYPE_CHECKING:
    from ..client import Client


PRICES_URL = "https://prices.runescape.wiki/api/v1/osrs"
Timestep = Literal["5m", "1h", "6h", "24h"]


class GrandExchange:
    """Item search and prices. The item list is fetched once and cached."""

    def __init__(self, client: "Client") -> None:
        self._client = client
        self._items: list[Item] | None = None

    def __repr__(self) -> str:
        return "GrandExchange()"

    @property
    def items(self) -> list[Item]:
        """Every tradeable item. Call ``refresh()`` to fetch the list again."""
        if self._items is None:
            mapping = self._client.get_json(f"{PRICES_URL}/mapping")
            if not isinstance(mapping, list) or any(
                not isinstance(item, dict) or not isinstance(item.get("name"), str)
                or isinstance(item.get("id"), bool) or not isinstance(item.get("id"), int)
                for item in mapping
            ):
                raise OSRSError("Invalid GE mapping: expected a list of named items")
            self._items = [Item.from_json(item) for item in mapping]
        return self._items

    def refresh(self) -> None:
        """Forget the cached item list; prices are never cached."""
        self._items = None

    def search(self, query: str, limit: int = 20, offset: int = 0) -> Results[Item]:
        """Exact name matches first, then prefixes, then substrings."""
        string(query, "query")
        integer(limit, "limit")
        integer(offset, "offset", minimum=0)
        needle = query.lower()
        scored = []
        for item in self.items:
            name = item.name.lower()
            score = 3 if name == needle else 2 if name.startswith(needle) else 1 if needle in name else 0
            if score:
                scored.append((score, item))
        scored.sort(key=lambda match: (-match[0], match[1].name.casefold()))
        return Results([item for _, item in scored[offset:offset + limit]], len(scored), query)

    def item(self, item: "int | str | Item") -> Item:
        """Look up an item by ID or exact (case-insensitive) name."""
        if isinstance(item, Item):
            return item
        if isinstance(item, str):
            string(item, "item")
            found = next((i for i in self.items if i.name.casefold() == item.casefold()), None)
        else:
            integer(item, "item")
            found = next((i for i in self.items if i.id == item), None)
        if found is None:
            raise KeyError(f"No Grand Exchange item {item!r}")
        return found

    def _resolve(self, item: "int | str | Item") -> tuple[int, str]:
        """ID and name; a bare ID is not looked up, so it costs no extra request."""
        if isinstance(item, (Item, str)):
            found = self.item(item)
            return found.id, found.name
        integer(item, "item")
        return item, ""

    def price(self, item: "int | str | Item") -> Price:
        item_id, name = self._resolve(item)
        data = self._client.get_json(f"{PRICES_URL}/latest", {"id": item_id})
        if not isinstance(data, dict) or not isinstance(data.get("data"), dict):
            raise OSRSError("Invalid GE latest response: expected a data object")
        latest = data["data"].get(str(item_id), {})
        return Price(item_id, latest.get("high"), latest.get("low"),
                     from_timestamp(latest.get("highTime")), from_timestamp(latest.get("lowTime")), name)

    def history(self, item: "int | str | Item", timestep: Timestep = "1h") -> PriceHistory:
        if timestep not in ("5m", "1h", "6h", "24h"):
            raise ValueError("timestep must be one of 5m, 1h, 6h, 24h")
        item_id, name = self._resolve(item)
        data = self._client.get_json(f"{PRICES_URL}/timeseries", {"id": item_id, "timestep": timestep})
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise OSRSError("Invalid GE timeseries response: expected a data list")
        points = [
            PricePoint(from_timestamp(point.get("timestamp")), point.get("avgHighPrice"), point.get("avgLowPrice"),
                       point.get("highPriceVolume", 0), point.get("lowPriceVolume", 0))
            for point in data["data"] if isinstance(point, dict)
        ]
        return PriceHistory(item_id, timestep, points, name)
