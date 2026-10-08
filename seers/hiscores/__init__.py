"""Official Old School hiscores.

>>> from seers import hiscores
>>> player = hiscores.lookup("Lynx Titan")
>>> player.mode, player.skills["attack"].xp
>>> hiscores.stats("Lynx Titan", mode="main").bosses

These functions use the default client; ``Client().hiscores`` has the same methods.
"""

from .api import Hiscores, Mode
from .models import BOSSES, Activity, Player, Skill, Stats

__all__ = ["lookup", "stats", "Hiscores", "Player", "Stats", "Skill", "Activity", "BOSSES"]


def _hiscores() -> Hiscores:
    from ..client import default_client
    return default_client().hiscores


def lookup(name: str) -> Player:
    """Every hiscores table the player is on, with account-type detection."""
    return _hiscores().lookup(name)


def stats(name: str, mode: Mode = "main") -> Stats:
    """One hiscores table, without account-type detection."""
    return _hiscores().stats(name, mode)
