"""Exceptions raised for upstream failures."""


class OSRSError(Exception):
    """An OSRS upstream request failed or returned unusable data."""


class PlayerNotFoundError(OSRSError):
    """The requested player has no entry on the selected hiscores."""
