"""The shared server: one process serving every relay on the machine, gone when unused.

Each connection from a relay (``seers.mcp.relay``) is one client's MCP session,
framed exactly like stdio: a JSON-RPC message per line. All sessions use the
same ``AsyncClient``, so the cache is opened and synced once.

A relay's connection lasts as long as its client, which makes the number of
connected relays the number of clients. When it has been zero for
``idle_timeout`` seconds the server exits; the next relay starts a new one.
Connections that never say hello (a port scan, another program) do not count.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import anyio
from anyio.abc import SocketStream
from anyio.streams.buffered import BufferedByteReceiveStream
from mcp.server.stdio import stdio_server

from seers.mcp.relay import HOST, hello
from seers.mcp.server import SeersMCP, open_client

logger = logging.getLogger("seers.mcp")

_HELLO_TIMEOUT = 10.0
_MAX_LINE = 1 << 24

_GONE = (
    anyio.IncompleteRead,  # end of stream
    anyio.DelimiterNotFound,  # no line within _MAX_LINE: not a client worth keeping
    anyio.BrokenResourceError,
    anyio.ClosedResourceError,
)


class _Lines:
    """A relay's connection as the line-based text streams ``stdio_server`` reads and writes."""

    def __init__(self, stream: SocketStream) -> None:
        self._stream = stream
        self._buffered = BufferedByteReceiveStream(stream)

    def __aiter__(self) -> _Lines:
        return self

    async def __anext__(self) -> str:
        try:
            line = await self._buffered.receive_until(b"\n", _MAX_LINE)
        except _GONE:
            raise StopAsyncIteration from None
        return line.decode("utf-8", errors="replace")

    async def write(self, text: str) -> None:
        try:
            await self._stream.send(text.encode())
        except (anyio.BrokenResourceError, anyio.ClosedResourceError):
            pass  # the client left; the read side ends the session

    async def flush(self) -> None:
        pass


async def _welcome(lines: _Lines, options: list[str]) -> bool:
    """Exchange hellos; whether the other side is a relay asking for the server that runs here."""
    ours = hello(options)
    with anyio.move_on_after(_HELLO_TIMEOUT):
        theirs = await anext(lines, "")
        await lines.write(ours.decode())  # a relay with other options learns what runs here
        return theirs.encode() + b"\n" == ours
    return False


async def _session(server: SeersMCP, lines: _Lines) -> None:
    """Serve one client until its relay disconnects."""
    lowlevel = server._lowlevel_server  # the SDK has no public way to serve custom streams
    async with stdio_server(lines, lines) as (read, write):  # type: ignore[arg-type]
        await lowlevel.run(read, write, lowlevel.create_initialization_options())


async def serve(port: int, options: list[str], idle_timeout: float, **settings: Any) -> None:
    """Serve relays on ``port`` until no client has been connected for ``idle_timeout`` seconds.

    ``options`` are the command-line options this server was started with, which a relay
    must match; ``settings`` are the same options as ``open_client`` arguments.
    """
    try:
        listener = await anyio.create_tcp_listener(local_host=HOST, local_port=port)
    except OSError as error:  # normally another seers server: the port is the lock
        raise SystemExit(f"seers-mcp: cannot listen on {HOST}:{port}: {error}") from error

    # The listener closes first: a relay arriving during shutdown is refused and starts a new server.
    async with open_client(**settings) as client, listener:
        server = SeersMCP(client)
        clients = 0
        # The relay that started this server is about to connect; give it time even with a zero timeout.
        grace = max(idle_timeout, _HELLO_TIMEOUT)
        with anyio.CancelScope(deadline=anyio.current_time() + grace) as idle:

            async def handle(stream: SocketStream) -> None:
                nonlocal clients
                try:
                    async with stream:
                        lines = _Lines(stream)
                        if not await _welcome(lines, options):
                            return
                        clients += 1
                        idle.deadline = math.inf
                        try:
                            await _session(server, lines)
                        finally:
                            clients -= 1
                            if not clients:
                                idle.deadline = anyio.current_time() + idle_timeout
                except Exception:
                    logger.exception("A client session failed")

            await listener.serve(handle)
