from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from seers import Client

Handler = Callable[[httpx.Request], httpx.Response]


def reply(payload: Any = None, *, status: int = 200, text: str | None = None) -> Handler:
    """A handler that answers every request the same way."""
    if text is not None:
        return lambda request: httpx.Response(status, text=text)
    return lambda request: httpx.Response(status, json=payload)


@pytest.fixture
def make_client(tmp_path) -> Iterator[Callable[..., Client]]:
    """Build a Client whose HTTP traffic goes to ``handler`` instead of the network."""
    transports: list[httpx.Client] = []

    def make(handler: Handler, **options: Any) -> Client:
        http = httpx.Client(transport=httpx.MockTransport(handler))
        transports.append(http)
        return Client(data_dir=tmp_path, http_client=http, **options)

    yield make
    for http in transports:
        http.close()
