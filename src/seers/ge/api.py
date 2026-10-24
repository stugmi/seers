"""The Wiki's real-time prices API (prices.runescape.wiki), as ``GrandExchange`` and ``AsyncGrandExchange``."""

from __future__ import annotations

from typing import TYPE_CHECKING

import anyio

from seers._http import Call, T, get_json
from seers.display import Results
from seers.errors import OSRSError
from seers.ge.models import Item, Price, PriceHistory, PricePoint, Timestep, from_timestamp
from seers.validation import validate_int, validate_str

if TYPE_CHECKING:
    from seers.client import AsyncClient, Client

PRICES_URL = "https://prices.runescape.wiki/api/v1/osrs"


class _Catalog:
    """The item mapping, downloaded on first use and kept until ``clear()``."""

    def __init__(self) -> None:
        self._items: list[Item] | None = None
        self._by_id: dict[int, Item] = {}
        self._by_name: dict[str, Item] = {}

    def clear(self) -> None:
        self._items = None
        self._by_id = {}
        self._by_name = {}

    def items(self) -> Call[list[Item]]:
        if self._items is not None:
            return self._items
        mapping = yield from get_json(f"{PRICES_URL}/mapping")
        if not isinstance(mapping, list) or any(
            not isinstance(entry, dict)
            or not isinstance(entry.get("name"), str)
            or isinstance(entry.get("id"), bool)
            or not isinstance(entry.get("id"), int)
            for entry in mapping
        ):
            raise OSRSError("Invalid GE mapping: expected a list of named items")

        items = [Item.from_json(entry) for entry in mapping]
        by_id: dict[int, Item] = {}
        by_name: dict[str, Item] = {}
        for item in items:
            by_id.setdefault(item.id, item)
            by_name.setdefault(item.name.casefold(), item)
        self._items, self._by_id, self._by_name = items, by_id, by_name
        return items

    def search(self, query: str, limit: int, offset: int) -> Call[Results[Item]]:
        needle = query.casefold()
        scored: list[tuple[int, str, Item]] = []
        for item in (yield from self.items()):
            folded = item.name.casefold()
            if folded == needle:
                score = 3
            elif folded.startswith(needle):
                score = 2
            elif needle in folded:
                score = 1
            else:
                continue
            scored.append((-score, folded, item))

        scored.sort(key=lambda match: (match[0], match[1]))
        page = [item for _, _, item in scored[offset : offset + limit]]
        return Results(page, len(scored), query)

    def item(self, item: int | str | Item) -> Call[Item]:
        if isinstance(item, Item):
            return item
        if isinstance(item, str):
            validate_str(item, "item")
            yield from self.items()
            found = self._by_name.get(item.casefold())
        else:
            validate_int(item, "item")
            yield from self.items()
            found = self._by_id.get(item)
        if found is None:
            raise KeyError(f"No Grand Exchange item {item!r}")
        return found

    def resolve(self, item: int | str | Item) -> Call[tuple[int, str | None]]:
        """``(id, name)``; a bare ID skips the item list, so its name is unknown."""
        if isinstance(item, (Item, str)):
            found = yield from self.item(item)
            return found.id, found.name
        validate_int(item, "item")
        return item, None

    def price(self, item: int | str | Item) -> Call[Price]:
        item_id, name = yield from self.resolve(item)
        payload = yield from get_json(f"{PRICES_URL}/latest", {"id": item_id})
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise OSRSError("Invalid GE latest response: expected a data object")

        latest = payload["data"].get(str(item_id), {})
        return Price(
            item_id=item_id,
            high=latest.get("high"),
            low=latest.get("low"),
            high_time=from_timestamp(latest.get("highTime")),
            low_time=from_timestamp(latest.get("lowTime")),
            name=name,
        )

    def history(self, item: int | str | Item, step: Timestep) -> Call[PriceHistory]:
        item_id, name = yield from self.resolve(item)
        payload = yield from get_json(f"{PRICES_URL}/timeseries", {"id": item_id, "timestep": step.value})
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise OSRSError("Invalid GE timeseries response: expected a data list")

        points = [
            PricePoint(
                time=from_timestamp(point.get("timestamp")),  # type: ignore[arg-type]
                avg_high=point.get("avgHighPrice"),
                avg_low=point.get("avgLowPrice"),
                high_volume=point.get("highPriceVolume", 0),
                low_volume=point.get("lowPriceVolume", 0),
            )
            for point in payload["data"]
            if isinstance(point, dict)
        ]
        return PriceHistory(item_id=item_id, timestep=step, points=points, name=name)


class GrandExchange:
    """Item search and real-time prices. The item list is downloaded once and kept."""

    def __init__(self, client: Client) -> None:
        self._client = client
        self._catalog = _Catalog()

    def __repr__(self) -> str:
        return "GrandExchange()"

    @property
    def items(self) -> list[Item]:
        """Every tradeable item. Call ``refresh()`` to download the list again."""
        return self._client._run(self._catalog.items())

    def refresh(self) -> None:
        """Forget the item list; prices are never cached."""
        self._catalog.clear()

    def search(self, query: str, limit: int = 20, offset: int = 0) -> Results[Item]:
        """Search items with exact matches first, then prefixes, then substrings."""
        validate_str(query, "query")
        validate_int(limit, "limit")
        validate_int(offset, "offset", min_value=0)
        return self._client._run(self._catalog.search(query, limit, offset))
    def item(self, item: int | str | Item) -> Item:
        """Look up an item by ID or exact (case-insensitive) name."""
        return self._client._run(self._catalog.item(item))

    def price(self, item: int | str | Item) -> Price:
        """Latest instant-buy and instant-sell prices for ``item``."""
        return self._client._run(self._catalog.price(item))
    def history(self, item: int | str | Item, timestep: Timestep | str = Timestep.ONE_HOUR) -> PriceHistory:
        """Up to 365 historical price points at ``timestep`` intervals."""
        try:
            step = Timestep(timestep)
        except ValueError:
            raise ValueError("timestep must be one of 5m, 1h, 6h, 24h") from None
        return self._client._run(self._catalog.history(item, step))


class AsyncGrandExchange:
    """``GrandExchange`` for ``AsyncClient``: the same methods, awaitable.

    Concurrent calls share one download of the item list.
    """

    def __init__(self, client: AsyncClient) -> None:
        self._client = client
        self._catalog = _Catalog()
        self._loading = anyio.Lock()

    def __repr__(self) -> str:
        return "AsyncGrandExchange()"

    async def _with_items(self, call: Call[T]) -> T:
        async with self._loading:
            await self._client._run(self._catalog.items())
        return await self._client._run(call)

    async def items(self) -> list[Item]:
        """Every tradeable item. Call ``refresh()`` to download the list again."""
        return await self._with_items(self._catalog.items())

    def refresh(self) -> None:
        """Forget the item list; prices are never cached."""
        self._catalog.clear()

    async def search(self, query: str, limit: int = 20, offset: int = 0) -> Results[Item]:
        """Search items with exact matches first, then prefixes, then substrings."""
        validate_str(query, "query")
        validate_int(limit, "limit")
        validate_int(offset, "offset", min_value=0)
        return await self._with_items(self._catalog.search(query, limit, offset))

    async def item(self, item: int | str | Item) -> Item:
        """Look up an item by ID or exact (case-insensitive) name."""
        return await self._with_items(self._catalog.item(item))

    async def price(self, item: int | str | Item) -> Price:
        """Latest instant-buy and instant-sell prices for ``item``."""
        call = self._catalog.price(item)
        return await (self._with_items(call) if isinstance(item, str) else self._client._run(call))

    async def history(self, item: int | str | Item, timestep: Timestep | str = Timestep.ONE_HOUR) -> PriceHistory:
        """Up to 365 historical price points at ``timestep`` intervals."""
        try:
            step = Timestep(timestep)
        except ValueError:
            raise ValueError("timestep must be one of 5m, 1h, 6h, 24h") from None
        call = self._catalog.history(item, step)
        return await (self._with_items(call) if isinstance(item, str) else self._client._run(call))
