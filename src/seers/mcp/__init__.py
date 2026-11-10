"""MCP server for seers, an optional extension: ``pip install "seers[mcp]"``.

Run it with ``seers-mcp`` or ``python -m seers.mcp``. Nothing in ``seers`` imports
this package, so without the extra it costs nothing.
"""

from importlib.util import find_spec
from typing import TYPE_CHECKING, Any

if find_spec("mcp") is None:
    raise ModuleNotFoundError('seers.mcp needs the MCP SDK: pip install "seers[mcp]"', name="mcp")

from seers.mcp.cli import main

if TYPE_CHECKING:
    from seers.mcp.server import SeersMCP

__all__ = ["SeersMCP", "main"]


def __getattr__(name: str) -> Any:
    # Loaded on first use: the stdio relay runs from this package and must not pay for the SDK.
    if name == "SeersMCP":
        from seers.mcp.server import SeersMCP

        return SeersMCP
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
