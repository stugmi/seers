"""Official Old School hiscores.

>>> from seers import hiscores
>>> player = hiscores.lookup("Lynx Titan")
>>> player.mode, player.skills["attack"].xp
>>> hiscores.stats("Lynx Titan", mode="main").bosses

These functions use the default client; ``Client().hiscores`` exposes the same methods and
``AsyncClient().hiscores`` awaitable versions of them.
"""

from seers import client as _client
from seers.hiscores.api import AsyncHiscores, Hiscores
from seers.hiscores.models import BOSSES, Activity, Mode, Player, Skill, Stats

__all__ = [
    "BOSSES",
    "Activity",
    "AsyncHiscores",
    "Hiscores",
    "Mode",
    "Player",
    "Skill",
    "Stats",
    "lookup",
    "stats",
]


def lookup(name: str) -> Player:
    """Look up every hiscores table the player is on and detect their account type."""
    return _client.default_client().hiscores.lookup(name)


def stats(name: str, mode: Mode | str = Mode.MAIN) -> Stats:
    """Look up one hiscores table without account-type detection."""
    return _client.default_client().hiscores.stats(name, mode)
