from collections.abc import Callable, Iterator
import functools
import inspect
from typing import Any

import anyio
import httpx
import pytest

from seers import AsyncClient, Client

Handler = Callable[[httpx.Request], httpx.Response]


def reply(payload: Any = None, *, status: int = 200, text: str | None = None) -> Handler:
    """A handler that answers every request the same way."""
    if text is not None:
        return lambda request: httpx.Response(status, text=text)
    return lambda request: httpx.Response(status, json=payload)


class Blocking:
    """Calls an ``AsyncClient`` service through ``anyio.run`` on one backend, so a test written
    against the sync API also exercises the async one."""

    def __init__(self, target: Any, backend: str) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_backend", backend)

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._target, name)
        if inspect.iscoroutinefunction(value):
            return lambda *args, **kwargs: anyio.run(
                functools.partial(value, *args, **kwargs), backend=self._backend
            )
        if name in ("wiki", "ge", "hiscores"):
            return Blocking(value, self._backend)
        return value

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._target, name, value)


@pytest.fixture(params=["asyncio", "trio"])
def anyio_backend(request) -> str:
    """Run every ``@pytest.mark.anyio`` test on both anyio backends."""
    return request.param


@pytest.fixture(params=["sync", "asyncio", "trio"])
def make_client(request, tmp_path) -> Iterator[Callable[..., Any]]:
    """Build a client whose HTTP traffic goes to ``handler`` instead of the network.

    Runs each test with ``Client``, and with ``AsyncClient`` on asyncio and on trio.
    """
    closers: list[Callable[[], None]] = []

    def make(handler: Handler, **options: Any) -> Any:
        transport = httpx.MockTransport(handler)
        if request.param == "sync":
            http = httpx.Client(transport=transport)
            closers.append(http.close)
            return Client(cache_path=tmp_path, http_client=http, **options)
        async_http = httpx.AsyncClient(transport=transport)
        closers.append(lambda: anyio.run(async_http.aclose, backend=request.param))
        client = AsyncClient(cache_path=tmp_path, http_client=async_http, **options)
        return Blocking(client, request.param)

    yield make
    for close in closers:
        close()
