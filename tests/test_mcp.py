"""The MCP extension: tools through the SDK's in-memory client, lifetime over real stdio."""

import os
import subprocess
import sys
import textwrap
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

_ORPHANING_CLIENT = textwrap.dedent(
    """
    import json, os, subprocess, sys

    # A client whose stdin pipe for the server leaks into a long-lived process:
    # after the client dies the pipe stays open, so the server never sees EOF.
    read, write = os.pipe()
    os.set_inheritable(write, True)
    server = subprocess.Popen([sys.executable, "-m", "seers.mcp"], stdin=read, stdout=subprocess.PIPE)
    leaker = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        close_fds=False, **({} if os.name == "nt" else {"pass_fds": (write,)}),
    )
    hello = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {},
        "clientInfo": {"name": "orphaning-client", "version": "0"}}}
    os.write(write, (json.dumps(hello) + "\\n").encode())
    server.stdout.readline()  # the server is up and serving
    with open(sys.argv[1], "w") as pids:
        pids.write(f"{server.pid} {leaker.pid}")
    os._exit(0)
    """
)


def _running(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32")
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x102  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _kill(pid: int) -> None:
    if _running(pid):
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False)
        else:
            os.kill(pid, 9)


def test_server_exits_with_its_client_even_when_the_pipe_stays_open(tmp_path):
    pid_file = tmp_path / "pids"
    subprocess.run(
        [sys.executable, "-c", _ORPHANING_CLIENT, str(pid_file)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, timeout=60, check=True,
    )
    server_pid, leaker_pid = map(int, pid_file.read_text().split())
    try:
        deadline = time.monotonic() + 5
        while _running(server_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert _running(leaker_pid), "the leaked pipe must still be open for this to test anything"
        assert not _running(server_pid)
    finally:
        _kill(server_pid)
        _kill(leaker_pid)
