"""Optional MCP server. Requires ``pip install "seers[mcp]"``."""

from .server import create_server, main

__all__ = ["create_server", "main"]
