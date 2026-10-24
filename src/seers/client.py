"""The sync ``Client`` and async ``AsyncClient``: one HTTP connection plus every service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from seers import __version__
from seers._http import Call, Request, T, checked, transport_error
from seers.data.cache import Cache
from seers.errors import OSRSError
from seers.ge.api import AsyncGrandExchange, GrandExchange
from seers.hiscores.api import AsyncHiscores, Hiscores
from seers.validation import validate_duration, validate_str
from seers.wiki.api import AsyncWiki, Wiki

REPOSITORY = "https://github.com/stugmi/seers"
USER_AGENT = f"seers/{__version__} (+{REPOSITORY})"


class _Settings:
    """Request settings and the offline cache, shared by both clients."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout: float,
        cache_path: str | Path | None,
        cache_dir: str | Path | None,
        auto_update: bool,
        max_age: float,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.data = Cache(cache_path, cache_dir=cache_dir, auto_update=auto_update, max_age=max_age)

    @property
    def user_agent(self) -> str:
        return self._user_agent

    @user_agent.setter
    def user_agent(self, value: str) -> None:
        self._user_agent = validate_str(value, "user_agent")

    @property
    def timeout(self) -> float:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        self._timeout = validate_duration(value, "timeout", positive=True)

    def _request_options(self) -> dict[str, Any]:
        return {
            "headers": {"User-Agent": self._user_agent},
            "timeout": self._timeout,
            "follow_redirects": True,
        }


class Client(_Settings):
    """Wiki, Grand Exchange, hiscores and the game cache behind one blocking HTTP client.

    >>> with Client(user_agent="my-app/1.0 (me@example.com)") as client:
    ...     page = client.wiki.page("Abyssal whip")

    An injected ``http_client`` stays owned by the caller. ``user_agent`` and
    ``timeout`` can be changed at any time and apply to subsequent requests.
    """

    def __init__(
        self,
        *,
        user_agent: str = USER_AGENT,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
        cache_path: str | Path | None = None,
        cache_dir: str | Path | None = None,
        auto_update: bool = False,
        max_age: float = 86400,
    ) -> None:
        super().__init__(
            user_agent=user_agent,
            timeout=timeout,
            cache_path=cache_path,
            cache_dir=cache_dir,
            auto_update=auto_update,
            max_age=max_age,
        )
        self._owns_http = http_client is None
        self._http = http_client if http_client is not None else httpx.Client()
        self.wiki = Wiki(self)
        self.ge = GrandExchange(self)
        self.hiscores = Hiscores(self)

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP client unless it was injected by the caller."""
        if self._owns_http:
            self._http.close()

    def _send(self, request: Request) -> httpx.Response:
        try:
            response = self._http.get(request.url, params=request.params, **self._request_options())
        except httpx.RequestError as error:
            raise transport_error(request, error) from error
        return checked(request, response)

    def _run(self, call: Call[T]) -> T:
        try:
            request = next(call)
            while True:
                try:
                    response = self._send(request)
                except OSRSError as error:
                    request = call.throw(error)
                else:
                    request = call.send(response)
        except StopIteration as done:
            return done.value


class AsyncClient(_Settings):
    """The async ``Client``: same services, awaitable, on any anyio backend (asyncio or trio).

    >>> async with AsyncClient() as client:
    ...     price = await client.ge.price("Abyssal whip")

    ``data`` (the offline cache) is the same synchronous ``Cache`` as on ``Client``;
    its reads are local and fast.
    """

    def __init__(
        self,
        *,
        user_agent: str = USER_AGENT,
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
        cache_path: str | Path | None = None,
        cache_dir: str | Path | None = None,
        auto_update: bool = False,
        max_age: float = 86400,
    ) -> None:
        super().__init__(
            user_agent=user_agent,
            timeout=timeout,
            cache_path=cache_path,
            cache_dir=cache_dir,
            auto_update=auto_update,
            max_age=max_age,
        )
        self._owns_http = http_client is None
        self._http = http_client if http_client is not None else httpx.AsyncClient()
        self.wiki = AsyncWiki(self)
        self.ge = AsyncGrandExchange(self)
        self.hiscores = AsyncHiscores(self)

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client unless it was injected by the caller."""
        if self._owns_http:
            await self._http.aclose()

    async def _send(self, request: Request) -> httpx.Response:
        try:
            response = await self._http.get(request.url, params=request.params, **self._request_options())
        except httpx.RequestError as error:
            raise transport_error(request, error) from error
        return checked(request, response)

    async def _run(self, call: Call[T]) -> T:
        try:
            request = next(call)
            while True:
                try:
                    response = await self._send(request)
                except OSRSError as error:
                    request = call.throw(error)
                else:
                    request = call.send(response)
        except StopIteration as done:
            return done.value


_default_client: Client | None = None


def default_client() -> Client:
    """Return the shared client backing ``seers.wiki``, ``seers.ge``, ``seers.hiscores`` and ``seers.data``."""
    global _default_client
    if _default_client is None:
        _default_client = Client()
    return _default_client


def configure(*, user_agent: str | None = None, timeout: float | None = None) -> Client:
    """Update request settings on the shared default client."""
    client = default_client()
    if user_agent is not None:
        client.user_agent = user_agent
    if timeout is not None:
        client.timeout = timeout
    return client
