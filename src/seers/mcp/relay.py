"""The process an MCP client launches: a relay to the one shared server.

Every MCP client (each agent session) launches its own stdio process. If each
of those were a full server, ten sessions would load the SDK and the cache ten
times. So the launched process only relays: it connects to the shared server
on a loopback port (``seers.mcp.shared``) and copies bytes between the
client's pipes and that connection.

Nothing has to be running beforehand. A relay that finds nobody listening
starts the server, detached from its own session, so the server serves the
clients that come later and exits by itself once it has had none for its idle
timeout. The port is the lock: a second server cannot bind it, so two relays
that start one at the same moment both end up on the winner.

The first line in each direction is a hello carrying the version and the server
options. It lets a relay tell a seers server from an unrelated program on the
port, and refuse a server left over from before an upgrade or one that runs
with a different cache than the one it was asked for.

This module must stay free of the MCP SDK: it is all a session costs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time

from seers import __version__

HOST = "127.0.0.1"
DEFAULT_PORT = 28765

_CONNECT_TIMEOUT = 0.25  # loopback answers at once when something listens
_HELLO_TIMEOUT = 10.0
_START_TIMEOUT = 30.0
_START_ATTEMPTS = 3
_LOG_LIMIT = 1 << 20


def hello(options: list[str]) -> bytes:
    """The line each side sends first: its version and the options the server runs with, or should."""
    return json.dumps({"seers-mcp": options, "version": __version__}).encode() + b"\n"


def log_path(port: int) -> Path:
    """Where a server started by a relay logs; it has no terminal and no single client."""
    return Path(tempfile.gettempdir()) / f"seers-mcp-{port}.log"


def _start_server(port: int, options: list[str]) -> subprocess.Popen[bytes]:
    path = log_path(port)
    oversized = path.exists() and path.stat().st_size > _LOG_LIMIT
    # Its own hidden console or session: closing the client's terminal must not take it down.
    detached = (
        {"creationflags": subprocess.CREATE_NO_WINDOW}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )
    with open(path, "wb" if oversized else "ab") as log:
        return subprocess.Popen(
            [sys.executable, "-m", "seers.mcp", "--serve", "--shared-port", str(port), *options],
            # None of the client's pipes: an inherited copy would keep them open after the relay.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=log,
            cwd=path.parent,  # not the client's project directory, which the server would pin
            **detached,
        )


def _exchange_hello(connection: socket.socket, options: list[str]) -> bytes | None:
    """Send our hello and return the reply line, or None if the other side hung up or stalled."""
    connection.settimeout(_HELLO_TIMEOUT)
    reply = b""
    try:
        connection.sendall(hello(options))
        # One byte at a time: whatever follows the line belongs to the MCP session.
        while not reply.endswith(b"\n") and len(reply) < 4096:
            byte = connection.recv(1)
            if not byte:
                return None
            reply += byte
    except OSError:
        return None
    return reply


def _refusal(port: int, reply: bytes) -> str:
    try:
        theirs = json.loads(reply)
        options, version = " ".join(theirs["seers-mcp"]), str(theirs["version"])
    except (ValueError, KeyError, TypeError):
        return f"seers-mcp: port {port} belongs to another program; choose one with --shared-port"
    if version != __version__:
        return (
            f"seers-mcp: the shared server on port {port} is still seers {version} and this is "
            f"{__version__}; it exits once the sessions using it are closed, so restart those"
        )
    return (
        f"seers-mcp: the shared server on port {port} runs with other options ({options}); "
        "pass the same ones, or --shared-port for a separate server"
    )


def connect(port: int, options: list[str]) -> socket.socket:
    """A connection to the shared server on ``port``, started first if nothing listens there."""
    deadline = time.monotonic() + _START_TIMEOUT
    server: subprocess.Popen[bytes] | None = None
    attempts = 0
    while time.monotonic() < deadline:
        try:
            connection = socket.create_connection((HOST, port), timeout=_CONNECT_TIMEOUT)
        except OSError:
            if server is None or server.poll() is not None:
                if attempts == _START_ATTEMPTS:
                    break
                server = _start_server(port, options)
                attempts += 1
            time.sleep(0.05)
            continue
        reply = _exchange_hello(connection, options)
        if reply == hello(options):
            connection.settimeout(None)
            return connection
        connection.close()
        if reply is not None:
            raise SystemExit(_refusal(port, reply))
        time.sleep(0.05)  # it hung up: a server caught while exiting idle; start over
    raise SystemExit(
        f"seers-mcp: could not reach or start the shared server on {HOST}:{port}; see {log_path(port)}"
    )


def run(port: int, options: list[str]) -> None:
    """Relay stdin and stdout to the shared server until the client or the server is done."""
    connection = connect(port, options)
    client_done = threading.Event()

    def send_stdin() -> None:
        try:
            while chunk := sys.stdin.buffer.read1(65536):
                connection.sendall(chunk)
        except OSError:
            pass
        client_done.set()
        try:
            connection.shutdown(socket.SHUT_WR)  # the server ends the session and hangs up
        except OSError:
            pass

    threading.Thread(target=send_stdin, name="seers-relay-stdin", daemon=True).start()

    output = sys.stdout.buffer
    while True:
        try:
            chunk = connection.recv(65536)
        except OSError:
            chunk = b""
        if not chunk:
            break
        try:
            output.write(chunk)
            output.flush()
        except OSError:
            client_done.set()  # the client stopped reading
            break

    if not client_done.is_set():
        sys.stderr.write("seers-mcp: the shared server closed the connection\n")
        sys.stderr.flush()
    # Not a normal exit: the other thread may sit in a read on stdin that never returns,
    # and interpreter shutdown would wait for it.
    os._exit(0 if client_done.is_set() else 1)
