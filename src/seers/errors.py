"""Exceptions raised for upstream failures."""

from __future__ import annotations


class OSRSError(Exception):
    """An OSRS upstream request failed or returned unusable data."""


class PlayerNotFoundError(OSRSError):
    """The requested player has no entry on the selected hiscores."""
