"""Backports for Python 3.10: ``enum.StrEnum`` and ``datetime.fromisoformat`` with ``Z``."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum

    fromisoformat = datetime.fromisoformat
else:

    class StrEnum(str, Enum):
        """String enum whose ``str()`` and ``format()`` give the value, as in Python 3.11."""

        def __str__(self) -> str:
            return str.__str__(self)

        def __format__(self, format_spec: str) -> str:
            return str.__format__(self, format_spec)

    def fromisoformat(value: str) -> datetime:
        """Parse ISO 8601, accepting a trailing ``Z`` like Python 3.11."""
        return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)

__all__ = ["StrEnum", "fromisoformat"]
