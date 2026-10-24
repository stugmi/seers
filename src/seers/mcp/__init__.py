"""MCP server for seers, an optional extension: ``pip install "seers[mcp]"``.

Run it with ``seers-mcp`` or ``python -m seers.mcp``. Nothing in ``seers`` imports
this package, so without the extra it costs nothing.
"""

try:
    import mcp  # noqa: F401
except ModuleNotFoundError as error:
    if error.name != "mcp":
        raise
    raise ModuleNotFoundError(
        'seers.mcp needs the MCP SDK: pip install "seers[mcp]"', name=error.name
    ) from error

from seers.mcp.server import SeersMCP, main

__all__ = ["SeersMCP", "main"]
