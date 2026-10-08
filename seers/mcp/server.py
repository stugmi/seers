"""MCP server exposing every library service as tools."""

import argparse
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from functools import partial
import json
from pathlib import Path
from typing import Annotated, Any, Literal

from ..client import Client
from ..data import KINDS


def _json(result: Any) -> str:
    if is_dataclass(result):
        result = asdict(result)
    elif isinstance(result, list):
        result = [asdict(item) if is_dataclass(item) else item for item in result]
    return json.dumps(result, ensure_ascii=False, default=str)


def create_server(
    client: Client | None = None,
    *,
    data_dir: str | Path | None = None,
    cache_dir: str | Path | None = None,
    auto_update: bool = False,
    max_age: float = 86400,
):
    """Create a FastMCP server; an injected client's lifetime stays with its caller.

    Install the ``mcp`` extra before calling this function.
    """
    try:
        import anyio
        from mcp.server.fastmcp import Context, FastMCP
        from pydantic import Field
    except ModuleNotFoundError as exc:
        if exc.name == "mcp":
            raise ImportError('MCP support requires: pip install "seers[mcp]"') from exc
        raise

    Limit = Annotated[int, Field(ge=1, le=100, strict=True)]
    WikiLimit = Annotated[int, Field(ge=1, le=50, strict=True)]
    Offset = Annotated[int, Field(ge=0, strict=True)]
    Query = Annotated[str, Field(min_length=1)]
    ItemRef = Annotated[int | str, Field(description="Item ID or exact item name")]
    Timestep = Literal["5m", "1h", "6h", "24h"]
    Mode = Literal["main", "ironman", "hardcore", "ultimate", "deadman", "seasonal"]
    Kind = Literal[tuple(KINDS)]  # type: ignore[valid-type]

    @asynccontextmanager
    async def lifespan(server):
        if client is not None:
            yield client
        else:
            with Client(data_dir=data_dir, cache_dir=cache_dir, auto_update=auto_update, max_age=max_age) as owned:
                yield owned

    server = FastMCP("seers", lifespan=lifespan)

    async def run(ctx: Any, function: Any) -> str:
        """Run blocking library code in a worker thread and return JSON or text."""
        result = await anyio.to_thread.run_sync(partial(function, ctx.request_context.lifespan_context))
        return result if isinstance(result, str) else _json(result)

    # Wiki

    @server.tool(structured_output=False)
    async def wiki_search(query: Query, ctx: Context, limit: WikiLimit = 10, offset: Offset = 0) -> str:
        """Full-text search of the OSRS Wiki. Returns titles, snippets and matching sections."""
        return await run(ctx, lambda c: c.wiki.search(query, limit, offset))

    @server.tool(structured_output=False)
    async def wiki_page(title: Query, ctx: Context, format: Literal["markdown", "html"] = "markdown") -> str:
        """Read an OSRS Wiki page as Markdown (default) or parsed HTML. Redirects are followed."""
        def read(c: Client) -> str:
            page = c.wiki.page(title)
            return page.html if format == "html" else f"# {page.title}\n{page.url}\n\n{page.markdown}"
        return await run(ctx, read)

    @server.tool(structured_output=False)
    async def wiki_page_info(titles: Annotated[list[Query], Field(min_length=1)], ctx: Context) -> str:
        """Metadata (exists, page ID, revision, length, last touched) for one or more titles."""
        return await run(ctx, lambda c: c.wiki.info(*titles))

    # Grand Exchange

    @server.tool(structured_output=False)
    async def ge_search(query: Query, ctx: Context, limit: Limit = 20, offset: Offset = 0) -> str:
        """Find Grand Exchange items by name (exact, then prefix, then substring)."""
        return await run(ctx, lambda c: c.ge.search(query, limit, offset))

    @server.tool(structured_output=False)
    async def ge_price(item: ItemRef, ctx: Context) -> str:
        """Latest instant-buy (high) and instant-sell (low) prices for an item."""
        return await run(ctx, lambda c: c.ge.price(item))

    @server.tool(structured_output=False)
    async def ge_history(item: ItemRef, ctx: Context, timestep: Timestep = "1h") -> str:
        """Up to 365 averaged price points for an item at 5m, 1h, 6h or 24h steps."""
        return await run(ctx, lambda c: c.ge.history(item, timestep))

    # Hiscores

    @server.tool(structured_output=False)
    async def player_lookup(name: Query, ctx: Context, mode: Mode | None = None) -> str:
        """Hiscores skills, bosses, clues and activities for a player.

        Omit mode to detect the account type and include every table they appear on.
        """
        return await run(ctx, lambda c: c.hiscores.lookup(name) if mode is None else c.hiscores.stats(name, mode))

    # Game definitions

    @server.tool(structured_output=False)
    async def definition_search(kind: Kind, query: str, ctx: Context, limit: Limit = 10, offset: Offset = 0) -> str:
        """Search the game cache's internal names (IDs and debug names).

        Kinds: items (objtypes), npcs, locs (world objects), animations (seqtypes),
        spotanims, sounds, sprites, interfaces, inventories, varps, varbits, rows, tables.
        """
        return await run(ctx, lambda c: getattr(c.data, kind).search(query, limit, offset))

    @server.tool(structured_output=False)
    async def definition_get(kind: Kind, id: str, ctx: Context) -> str:
        """Look up one definition by exact ID, e.g. kind=items, id=4151."""
        return await run(ctx, lambda c: getattr(c.data, kind).get(id))

    @server.tool(structured_output=False)
    async def data_files(ctx: Context, file_type: str | None = None) -> str:
        """List the data directory's files, optionally only those ending in .<file_type>."""
        def files(c: Client) -> dict[str, Any]:
            names = [f.filename for f in c.data.files if not file_type or f.filename.endswith(f".{file_type}")]
            return {"files": names, "path": str(c.data.data_dir)}
        return await run(ctx, files)

    @server.tool(structured_output=False)
    async def data_file_search(filename: Query, query: str, ctx: Context, limit: Limit = 10, offset: Offset = 0) -> str:
        """Search any file in the data directory by name, e.g. a custom definition file."""
        return await run(ctx, lambda c: c.data.file(filename).search(query, limit, offset))

    @server.tool(structured_output=False)
    async def data_file_details(filename: Query, ctx: Context) -> str:
        """Existence, size, definition count and timestamps for a file in the data directory."""
        def details(c: Client) -> dict[str, Any]:
            found = c.data.file(filename)
            if not found.exists:
                return {"exists": False}
            return {"exists": True, "size": found.size, "definitions": len(found),
                    "created": found.created, "modified": found.modified}
        return await run(ctx, details)

    return server


def main() -> None:
    """``seers-mcp`` / ``python -m seers``: run the stdio MCP server."""
    parser = argparse.ArgumentParser(description="seers MCP server")
    parser.add_argument("--data-dir", type=Path, help="Use your own definition files")
    parser.add_argument("--cache-dir", type=Path, help="Override the writable definition cache")
    parser.add_argument("--auto-update", action="store_true", help="Refresh definitions automatically on data access")
    parser.add_argument("--max-age", type=float, default=86400, help="Refresh interval in seconds (default: 86400)")
    args = parser.parse_args()
    if args.data_dir is not None and (args.auto_update or args.cache_dir is not None):
        parser.error("--data-dir cannot be combined with --auto-update or --cache-dir")
    try:
        server = create_server(data_dir=args.data_dir, cache_dir=args.cache_dir,
                               auto_update=args.auto_update, max_age=args.max_age)
    except ImportError as exc:
        parser.error(str(exc))
    server.run()
