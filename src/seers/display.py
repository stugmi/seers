"""Rich display helpers and the ``Results`` container."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from typing import Any, Generic, TypeVar, overload

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

T = TypeVar("T")


def make_table(title: str = "") -> Table:
    """Create a consistently styled Rich table."""
    return Table(
        title=Text(title) if title else None,
        title_style="bold green",
        title_justify="left",
        box=box.ROUNDED,
        header_style="bold cyan",
        border_style="bright_black",
    )


def format_cell(value: Any) -> Text:
    """Format a value for a Rich table cell without interpreting Rich markup."""
    if value is None:
        return Text("")
    if isinstance(value, bool):
        return Text("yes" if value else "no")
    if isinstance(value, int):
        return Text(f"{value:,}")
    if isinstance(value, datetime):
        return Text(value.strftime("%Y-%m-%d %H:%M"))
    return Text(str(value))


class RichDisplay:
    """Mixin that renders Rich views in IPython/Jupyter while keeping dataclass ``repr``."""

    def _repr_pretty_(self, printer: Any, cycle: bool) -> None:
        if cycle:
            printer.text(f"{type(self).__name__}(...)")
            return
        console = Console(force_terminal=True, force_jupyter=False)
        with console.capture() as capture:
            console.print(self)
        printer.text(capture.get().rstrip("\n"))


@dataclass(frozen=True)
class Results(RichDisplay, Sequence[T], Generic[T]):
    """A page of search results that behaves like a read-only sequence of ``items``."""

    items: list[T]
    total: int
    query: str = ""

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> list[T]: ...

    def __getitem__(self, index: int | slice) -> T | list[T]:
        return self.items[index]

    def __len__(self) -> int:
        return len(self.items)

    def __rich__(self) -> Table:
        shown = f"{len(self.items)} of {self.total:,}"
        title = f"{self.query!r}: {shown} results" if self.query else f"{shown} results"
        result = make_table(title)
        if not self.items or not is_dataclass(self.items[0]):
            for item in self.items:
                result.add_row(format_cell(item))
            return result

        columns = [field.name for field in fields(self.items[0]) if field.repr]
        for name in columns:
            result.add_column(name.replace("_", " ").title())
        for item in self.items:
            result.add_row(
                *(
                    Text(str(getattr(item, name))) if name == "id" else format_cell(getattr(item, name))
                    for name in columns
                )
            )
        return result
