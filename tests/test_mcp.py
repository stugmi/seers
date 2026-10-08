"""The MCP server over a real stdio session, using only the bundled data."""

import asyncio
import json
import sys

import pytest

mcp = pytest.importorskip("mcp")
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

TOOLS = {
    "wiki_search", "wiki_page", "wiki_page_info", "ge_search", "ge_price", "ge_history",
    "player_lookup", "definition_search", "definition_get", "data_files",
    "data_file_search", "data_file_details",
}


async def session_calls():
    params = StdioServerParameters(command=sys.executable, args=["-m", "seers"])
    async with stdio_client(params) as (reader, writer):
        async with mcp.ClientSession(reader, writer) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}

            async def call(name, **arguments):
                result = await session.call_tool(name, arguments)
                return result.isError, (None if result.isError else json.loads(result.content[0].text))

            return tools, {
                "first": await call("definition_search", kind="items", query="bandos chestplate", limit=1),
                "second": await call("definition_search", kind="items", query="bandos chestplate", offset=1, limit=1),
                "blowpipe": await call("definition_get", kind="items", id="12924"),
                "files": await call("data_files", file_type="txt"),
                "details": await call("data_file_details", filename="npctypes.txt"),
                "vorkath": await call("data_file_search", filename="npctypes.txt", query="vorkath"),
                "bad_kind": await call("definition_search", kind="bank_pins", query="1234"),
                "bad_limit": await call("definition_search", kind="items", query="shark", limit=0),
                "escape": await call("data_file_search", filename="../pyproject.toml", query="seers"),
            }


@pytest.fixture(scope="module")
def server():
    return asyncio.run(session_calls())


def test_every_tool_is_listed(server):
    tools, _ = server
    assert tools == TOOLS


def test_definition_tools_return_dataclasses_as_json(server):
    _, calls = server
    failed, first = calls["first"]
    assert not failed
    assert first["items"] == [{"id": "11832", "name": "bandos_chestplate", "line": 11833}]
    assert first["query"] == "bandos chestplate" and first["total"] > 1
    assert calls["second"][1]["items"][0]["id"] == "11833"
    assert calls["blowpipe"][1]["name"] == "toxic_blowpipe"


def test_data_file_tools(server):
    _, calls = server
    assert "objtypes.txt" in calls["files"][1]["files"]
    assert calls["details"][1]["exists"] and calls["details"][1]["definitions"] > 1000
    assert "vorkath" in {npc["name"] for npc in calls["vorkath"][1]["items"]}


@pytest.mark.parametrize("call", ["bad_kind", "bad_limit", "escape"])
def test_bad_calls_are_errors_without_ending_the_session(server, call):
    _, calls = server
    assert calls[call] == (True, None)
