"""The client that owns HTTP settings and exposes every service."""

import math
from pathlib import Path
from typing import Any

import httpx

from .data import Definitions
from .errors import OSRSError, PlayerNotFoundError
from .ge import GrandExchange
from .hiscores import Hiscores
from .validation import string
from .version import USER_AGENT
from .wiki import Wiki


class Client:
    """Wiki, Grand Exchange, hiscores and game definitions behind one HTTP client.

    >>> with Client(user_agent="my-app/1.0 (me@example.com)") as client:
    ...     page = client.wiki.page("Abyssal whip")

    An injected ``http_client`` stays owned by the caller. ``user_agent`` and
    ``timeout`` can be changed at any time and apply to the next request.
    """

    def __init__(
        self,
        *,
        user_agent: str = USER_AGENT,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
        data_dir: str | Path | None = None,
        cache_dir: str | Path | None = None,
        auto_update: bool = False,
        max_age: float = 86400,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self._owns_http = http_client is None
        self._http = http_client if http_client is not None else httpx.Client()
        self.data = Definitions(data_dir, cache_dir=cache_dir, auto_update=auto_update, max_age=max_age)
        self.wiki = Wiki(self)
        self.ge = GrandExchange(self)
        self.hiscores = Hiscores(self)

    @property
    def user_agent(self) -> str:
        return self._user_agent

    @user_agent.setter
    def user_agent(self, value: str) -> None:
        string(value, "user_agent")
        self._user_agent = value

    @property
    def timeout(self) -> float:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("timeout must be a finite positive number of seconds")
        self._timeout = float(value)

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP client, unless it was injected by the caller."""
        if self._owns_http:
            self._http.close()

    def get(self, url: str, params: dict[str, Any] | None = None, *, player: str | None = None) -> httpx.Response:
        """GET ``url``; a 404 raises PlayerNotFoundError when ``player`` is given."""
        try:
            response = self._http.get(url, params=params, headers={"User-Agent": self._user_agent},
                                      timeout=self._timeout, follow_redirects=True)
            if response.status_code == 404 and player is not None:
                raise PlayerNotFoundError(f"Player not found: {player}")
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise OSRSError(f"OSRS request failed (HTTP {error.response.status_code}): {url}") from error
        except httpx.RequestError as error:
            raise OSRSError(f"OSRS request failed: {url}: {error}") from error
        return response

    def get_json(self, url: str, params: dict[str, Any] | None = None, *, player: str | None = None) -> Any:
        response = self.get(url, params, player=player)
        try:
            return response.json()
        except ValueError as error:
            raise OSRSError(f"Invalid JSON response from {url}") from error


_default: Client | None = None


def default_client() -> Client:
    """The shared client behind ``seers.wiki``, ``seers.ge``, ``seers.hiscores`` and ``seers.data``."""
    global _default
    if _default is None:
        _default = Client()
    return _default


def configure(*, user_agent: str | None = None, timeout: float | None = None) -> Client:
    """Change the default client's request settings, e.g. a User-Agent with contact info."""
    client = default_client()
    if user_agent is not None:
        client.user_agent = user_agent
    if timeout is not None:
        client.timeout = timeout
    return client
