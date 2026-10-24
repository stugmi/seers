"""Grand Exchange items, prices and price history."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from rich.table import Table

from seers._compat import StrEnum
from seers.display import RichDisplay, format_cell, make_table


class Timestep(StrEnum):
    FIVE_MINUTES = "5m"
    ONE_HOUR = "1h"
    SIX_HOURS = "6h"
    ONE_DAY = "24h"


def from_timestamp(timestamp: Any) -> datetime | None:
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc)


@dataclass(frozen=True)
class Item:
    id: int
    name: str
    members: bool = False
    limit: int | None = None
    value: int | None = None
    high_alch: int | None = None
    low_alch: int | None = None
    examine: str = field(default="", repr=False)
    icon: str = field(default="", repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Item:
        return cls(
            id=data["id"],
            name=data["name"],
            members=bool(data.get("members")),
            limit=data.get("limit"),
            value=data.get("value"),
            high_alch=data.get("highalch"),
            low_alch=data.get("lowalch"),
            examine=data.get("examine", ""),
            icon=data.get("icon", ""),
        )


@dataclass(frozen=True)
class Price(RichDisplay):
    """Latest instant-buy (``high``) and instant-sell (``low``) prices."""

    item_id: int
    high: int | None
    low: int | None
    high_time: datetime | None = None
    low_time: datetime | None = None
    name: str | None = None  # None when looked up by bare ID

    @property
    def margin(self) -> int | None:
        if self.high is None or self.low is None:
            return None
        return self.high - self.low

    def __rich__(self) -> Table:
        result = make_table(self.name or f"Item {self.item_id}")
        result.add_column("")
        result.add_column("Price", justify="right", style="bold green")
        result.add_column("Traded")
        result.add_row("Buy (high)", format_cell(self.high), format_cell(self.high_time))
        result.add_row("Sell (low)", format_cell(self.low), format_cell(self.low_time))
        result.add_row("Margin", format_cell(self.margin), "")
        return result


@dataclass(frozen=True)
class PricePoint:
    time: datetime
    avg_high: int | None
    avg_low: int | None
    high_volume: int
    low_volume: int


@dataclass(frozen=True)
class PriceHistory(RichDisplay):
    """Up to 365 averaged price points, oldest first."""

    item_id: int
    timestep: Timestep
    points: list[PricePoint] = field(repr=False)
    name: str | None = None  # None when looked up by bare ID

    def __iter__(self) -> Iterator[PricePoint]:
        return iter(self.points)

    def __len__(self) -> int:
        return len(self.points)

    def __rich__(self) -> Table:
        recent = self.points[-20:]
        label = self.name or f"Item {self.item_id}"
        title = f"{label}, {self.timestep} averages (latest {len(recent)} of {len(self.points)})"
        result = make_table(title)
        for col in ("Time", "Avg high", "Avg low", "High volume", "Low volume"):
            result.add_column(col, justify="left" if col == "Time" else "right")
        for point in recent:
            result.add_row(
                format_cell(point.time),
                format_cell(point.avg_high),
                format_cell(point.avg_low),
                format_cell(point.high_volume),
                format_cell(point.low_volume),
            )
        return result
