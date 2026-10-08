"""Grand Exchange items, prices and price history."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from rich.table import Table

from ..display import RichDisplay, cell, table


def from_timestamp(timestamp: Any) -> datetime | None:
    return datetime.fromtimestamp(timestamp, timezone.utc) if isinstance(timestamp, (int, float)) else None


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
    def from_json(cls, data: dict[str, Any]) -> "Item":
        return cls(data["id"], data["name"], bool(data.get("members")), data.get("limit"),
                   data.get("value"), data.get("highalch"), data.get("lowalch"),
                   data.get("examine", ""), data.get("icon", ""))


@dataclass(frozen=True)
class Price(RichDisplay):
    """Latest instant-buy (``high``) and instant-sell (``low``) prices."""

    item_id: int
    high: int | None
    low: int | None
    high_time: datetime | None = None
    low_time: datetime | None = None
    name: str = ""

    @property
    def margin(self) -> int | None:
        return self.high - self.low if self.high is not None and self.low is not None else None

    def __rich__(self) -> Table:
        result = table(self.name or f"Item {self.item_id}")
        result.add_column("")
        result.add_column("Price", justify="right", style="bold green")
        result.add_column("Traded")
        result.add_row("Buy (high)", cell(self.high), cell(self.high_time))
        result.add_row("Sell (low)", cell(self.low), cell(self.low_time))
        result.add_row("Margin", cell(self.margin), "")
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
    timestep: str
    points: list[PricePoint] = field(repr=False)
    name: str = ""

    def __iter__(self) -> Iterator[PricePoint]:
        return iter(self.points)

    def __len__(self) -> int:
        return len(self.points)

    def __rich__(self) -> Table:
        recent = self.points[-20:]
        result = table(f"{self.name or f'Item {self.item_id}'}, {self.timestep} averages (latest {len(recent)} of {len(self.points)})")
        for name in ("Time", "Avg high", "Avg low", "High volume", "Low volume"):
            result.add_column(name, justify="left" if name == "Time" else "right")
        for point in recent:
            result.add_row(cell(point.time), cell(point.avg_high), cell(point.avg_low),
                           cell(point.high_volume), cell(point.low_volume))
        return result
