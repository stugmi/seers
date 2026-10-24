import httpx
import pytest

from conftest import reply
import seers
from seers import REPOSITORY, AsyncClient, Client, OSRSError, __version__


def test_requests_identify_as_seers_until_user_agent_changes(make_client):
    agents = []

    def handler(request):
        agents.append(request.headers["User-Agent"])
        return httpx.Response(200, json={"data": {}})

    client = make_client(handler)
    client.ge.price(385)
    client.user_agent = "fletching-calc/2.1 (me@example.com)"
    client.ge.price(385)

    assert agents == [f"seers/{__version__} (+{REPOSITORY})", "fletching-calc/2.1 (me@example.com)"]


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), None, True, "30"])
def test_rejects_unusable_timeouts(tmp_path, timeout):
    with pytest.raises(ValueError):
        Client(cache_path=tmp_path, timeout=timeout)


@pytest.mark.parametrize("agent", ["", "   ", None])
def test_rejects_blank_user_agents(tmp_path, agent):
    with pytest.raises(ValueError):
        Client(cache_path=tmp_path, user_agent=agent)


def test_injected_http_client_is_never_closed(tmp_path):
    http = httpx.Client(transport=httpx.MockTransport(reply({"data": {}})))
    with Client(cache_path=tmp_path, http_client=http) as client:
        client.ge.price(385)
    client.close()

    assert not http.is_closed
    assert client.ge.price(385).high is None


@pytest.mark.anyio
async def test_async_client_never_closes_an_injected_http_client(tmp_path):
    http = httpx.AsyncClient(transport=httpx.MockTransport(reply({"data": {}})))
    async with AsyncClient(cache_path=tmp_path, http_client=http) as client:
        await client.ge.price(385)

    assert not http.is_closed
    assert (await client.ge.price(385)).high is None
    await http.aclose()


def test_owned_http_client_closes_even_when_the_block_raises(tmp_path):
    with pytest.raises(RuntimeError):
        with Client(cache_path=tmp_path) as client:
            raise RuntimeError("bank pin forgotten")
    assert client._http.is_closed


@pytest.mark.anyio
async def test_async_owned_http_client_closes_even_when_the_block_raises(tmp_path):
    with pytest.raises(RuntimeError):
        async with AsyncClient(cache_path=tmp_path) as client:
            raise RuntimeError("bank pin forgotten")
    assert client._http.is_closed


@pytest.mark.parametrize(("handler", "message"), [
    (reply(status=503, text="down for maintenance"), "HTTP 503"),
    (reply(text="<html>not json</html>"), "Invalid JSON"),
])
def test_upstream_failures_become_osrs_errors(make_client, handler, message):
    with pytest.raises(OSRSError, match=message):
        make_client(handler).ge.price(385)


def test_transport_errors_keep_their_message(make_client):
    def timeout(request):
        raise httpx.ReadTimeout("lagging like world 302", request=request)

    with pytest.raises(OSRSError, match="lagging like world 302"):
        make_client(timeout).ge.price(385)


def test_configure_updates_the_shared_default_client():
    client = seers.default_client()
    original = client.user_agent, client.timeout
    try:
        assert seers.configure(user_agent="clue-helper/0.1", timeout=5) is client
        assert (client.user_agent, client.timeout) == ("clue-helper/0.1", 5.0)
        assert seers.default_client().wiki is client.wiki
    finally:
        client.user_agent, client.timeout = original
