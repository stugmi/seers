"""Sans-IO requests shared by the sync ``Client`` and the async ``AsyncClient``.

Service logic (building requests, parsing responses) is written once as a generator
that yields a ``Request`` and receives the ``httpx.Response``. Each client drives it
with its own transport, so ``Wiki`` and ``AsyncWiki`` cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Generator, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx

from seers.errors import OSRSError, PlayerNotFoundError

T = TypeVar("T")

Call = Generator["Request", httpx.Response, T]
"""A request sequence that yields ``Request`` objects and returns ``T``."""


@dataclass(frozen=True, slots=True)
class Request:
    url: str
    params: Mapping[str, Any] | None = None
    player: str | None = None
    """If set, a 404 means this player is not on the hiscores."""


def checked(request: Request, response: httpx.Response) -> httpx.Response:
    """Turn an unsuccessful response into ``OSRSError`` / ``PlayerNotFoundError``."""
    if response.status_code == 404 and request.player is not None:
        raise PlayerNotFoundError(f"Player not found: {request.player}")
    if response.is_error:
        raise OSRSError(f"OSRS request failed (HTTP {response.status_code}): {request.url}")
    return response


def transport_error(request: Request, error: httpx.RequestError) -> OSRSError:
    return OSRSError(f"OSRS request failed: {request.url}: {error}")


def get(url: str, params: Mapping[str, Any] | None = None, *, player: str | None = None) -> Call[httpx.Response]:
    return (yield Request(url, params, player))


def get_json(url: str, params: Mapping[str, Any] | None = None, *, player: str | None = None) -> Call[Any]:
    response = yield Request(url, params, player)
    try:
        return response.json()
    except ValueError as error:
        raise OSRSError(f"Invalid JSON response from {url}") from error
