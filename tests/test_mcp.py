"""The MCP extension: tools through the SDK's in-memory client, sharing and lifetime over real processes."""

import json
import socket
import subprocess
import sys
import time

import pytest

pytest.importorskip("mcp")
import httpx
from mcp import Client

from seers import AsyncClient
from seers.mcp import SeersMCP

TOOLS = {
    "cache_search", "cache_get", "wiki_search", "wiki_page", "ge_search", "ge_price",
    "ge_history", "player_lookup", "player_stats",
}


@pytest.fixture
async def mcp(tmp_path):
    """The server on the bundled cache; every upstream HTTP request answers 404."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(404)))
    seers = AsyncClient(cache_dir=tmp_path, http_client=http)
    async with Client(SeersMCP(seers), raise_exceptions=True) as client:
        yield client
    await http.aclose()


@pytest.mark.anyio
async def test_every_tool_is_listed(mcp):
    assert {tool.name for tool in (await mcp.list_tools()).tools} == TOOLS


@pytest.mark.anyio
async def test_cache_search_pages_through_structured_results(mcp):
    first = await mcp.call_tool("cache_search", {"kind": "items", "query": "bandos chestplate", "limit": 1})
    page = first.structured_content["result"]  # the SDK wraps generic result types
    assert page["items"] == [{"id": "11832", "name": "bandos_chestplate", "line": 11833}]
    assert page["query"] == "bandos chestplate" and page["total"] > 1

    second = await mcp.call_tool(
        "cache_search", {"kind": "items", "query": "bandos chestplate", "limit": 1, "offset": 1}
    )
    assert second.structured_content["result"]["items"][0]["id"] == "11833"

    vorkath = await mcp.call_tool("cache_search", {"kind": "npcs", "query": "vorkath"})
    assert "vorkath" in {npc["name"] for npc in vorkath.structured_content["result"]["items"]}


@pytest.mark.anyio
async def test_cache_get_returns_the_entry(mcp):
    result = await mcp.call_tool("cache_get", {"kind": "items", "id": "12924"})
    assert result.structured_content == {"id": "12924", "name": "toxic_blowpipe", "line": 12925}


@pytest.mark.anyio
@pytest.mark.parametrize(("tool", "arguments", "message"), [
    ("cache_get", {"kind": "items", "id": "999999999"}, "No objtypes entry with id 999999999"),
    ("player_lookup", {"name": "Bank Stander"}, "Player not found: Bank Stander"),
])
async def test_library_failures_reach_the_model_as_readable_errors(mcp, tool, arguments, message):
    result = await mcp.call_tool(tool, arguments)
    assert result.is_error
    assert message in result.content[0].text


@pytest.mark.anyio
@pytest.mark.parametrize("arguments", [
    {"kind": "bank_pins", "query": "1234"},
    {"kind": "items", "query": "shark", "limit": 0},
])
async def test_bad_arguments_are_rejected_before_the_tool_runs(mcp, arguments):
    assert (await mcp.call_tool("cache_search", arguments)).is_error


# Lifetime

def _listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.25)
        return probe.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture
def port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture
def shared(tmp_path, port) -> list[str]:
    """Options for a shared server of this test's own: offline, on a free port, gone 1s after its last client."""
    return ["--no-sync", "--cache-dir", str(tmp_path), "--shared-port", str(port), "--idle-timeout", "1"]


class StdioSession:
    """What an MCP client does with ``seers-mcp``: launch it and talk JSON-RPC over its pipes."""

    def __init__(self, options: list[str]) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-m", "seers.mcp", *options],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self._id = 0

    def _send(self, message: dict) -> None:
        self.process.stdin.write((json.dumps({"jsonrpc": "2.0", **message}) + "\n").encode())
        self.process.stdin.flush()

    def _request(self, method: str, params: dict) -> dict:
        self._id += 1
        self._send({"id": self._id, "method": method, "params": params})
        while line := self.process.stdout.readline():
            reply = json.loads(line)
            if reply.get("id") == self._id:
                return reply["result"]
        pytest.fail(f"seers-mcp exited: {self.process.stderr.read().decode()}")

    def start(self) -> "StdioSession":
        self._request("initialize", {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        })
        self._send({"method": "notifications/initialized"})
        return self

    def lookup(self) -> dict:
        arguments = {"kind": "items", "id": "12924"}
        return self._request("tools/call", {"name": "cache_get", "arguments": arguments})["structuredContent"]

    def close(self) -> int:
        """Close stdin, as a client does when its session ends; returns the exit code."""
        self.process.stdin.close()
        return self.process.wait(timeout=10)

    def kill(self) -> None:
        self.process.kill()
        self.process.wait()


def test_stdio_clients_share_a_server_that_outlives_its_starter_and_exits_once_unused(shared, port):
    blowpipe = {"id": "12924", "name": "toxic_blowpipe", "line": 12925}
    assert not _listening(port)
    first = StdioSession(shared).start()  # nothing was running: this session starts the server
    second = StdioSession(shared)
    try:
        assert second.start().lookup() == first.lookup() == blowpipe
        assert first.close() == 0
        assert second.lookup() == blowpipe
        assert second.close() == 0

        deadline = time.monotonic() + 10
        while _listening(port) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _listening(port)
    finally:
        first.kill()
        second.kill()


def test_a_client_asking_for_another_cache_is_refused_instead_of_served_the_running_one(shared, tmp_path):
    running = StdioSession(shared).start()
    try:
        other = [*shared[:2], str(tmp_path / "other"), *shared[3:]]
        refused = subprocess.run(
            [sys.executable, "-m", "seers.mcp", *other],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
        )
        assert refused.returncode != 0
        assert str(tmp_path) in refused.stderr.decode()  # names what the running server uses
        assert running.lookup()["name"] == "toxic_blowpipe"
    finally:
        running.kill()


def test_a_server_left_running_from_another_version_is_refused_by_name(shared, port):
    import threading

    def old_server(listener: socket.socket) -> None:
        connection, _ = listener.accept()
        with connection:
            connection.recv(4096)
            connection.sendall(json.dumps({"seers-mcp": [], "version": "0.0.1"}).encode() + b"\n")

    with socket.create_server(("127.0.0.1", port)) as listener:
        threading.Thread(target=old_server, args=(listener,), daemon=True).start()
        refused = subprocess.run(
            [sys.executable, "-m", "seers.mcp", *shared],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
        )
    assert refused.returncode != 0
    assert "is still seers 0.0.1" in refused.stderr.decode()


def test_install_corrects_a_stale_entry_and_keeps_everything_else(tmp_path):
    from seers.mcp.install import entry, install

    config = tmp_path / "mcp.json"
    stale = {"type": "http", "url": "http://127.0.0.1:8765/mcp", "env": {"KEEP": "1"}}
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}, "seers": stale}, "theme": "dark"}))
    commented = tmp_path / "commented.json"
    commented.write_text('{ // mine\n "mcpServers": {"seers": {}} }')

    install([config, commented])

    assert json.loads(config.read_text()) == {
        "mcpServers": {"other": {"command": "x"}, "seers": {**entry(), "env": {"KEEP": "1"}}},
        "theme": "dark",
    }
    assert commented.read_text() == '{ // mine\n "mcpServers": {"seers": {}} }'


@pytest.mark.anyio
async def test_one_http_server_serves_concurrent_clients_and_refuses_a_duplicate(tmp_path):
    import socket

    from mcp.client.streamable_http import streamable_http_client

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    command = [sys.executable, "-m", "seers.mcp", "--no-sync", "--cache-dir", str(tmp_path), "--port", str(port)]
    server = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        else:
            pytest.fail("the HTTP server never listened")

        async def lookup() -> dict:
            async with Client(streamable_http_client(f"http://127.0.0.1:{port}/mcp")) as client:
                result = await client.call_tool("cache_get", {"kind": "items", "id": "12924"})
                return result.structured_content

        import anyio

        results: list[dict] = []

        async def collect() -> None:
            results.append(await lookup())

        async with anyio.create_task_group() as tg:
            tg.start_soon(collect)
            tg.start_soon(collect)
        assert results == [{"id": "12924", "name": "toxic_blowpipe", "line": 12925}] * 2

        duplicate = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        assert duplicate.returncode != 0
        assert server.poll() is None
    finally:
        server.kill()
        server.wait()
