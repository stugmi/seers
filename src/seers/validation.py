"""Shared argument validation helpers."""

from __future__ import annotations

import math
from urllib.parse import urlsplit


def validate_int(value: int, name: str, *, min_value: int = 1, max_value: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < min_value or (max_value is not None and value > max_value):
        bounds = f"{min_value}..{max_value}" if max_value is not None else f">= {min_value}"
        raise ValueError(f"{name} must be {bounds}")
    return value


def validate_str(value: str, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        kind = "string" if allow_empty else "nonempty string"
        raise ValueError(f"{name} must be a {kind}")
    return value


def validate_duration(value: float, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        bound = "positive" if positive else "nonnegative"
        raise ValueError(f"{name} must be finite and {bound}")
    return number


def validate_base_url(url: str, name: str = "source_url") -> str:
    if not isinstance(url, str) or any(ch.isspace() for ch in url):
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    try:
        parts = urlsplit(url)
        _ = parts.port
    except ValueError as error:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL") from error
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError(f"{name} must be an absolute HTTP(S) URL without credentials, query, or fragment")
    return url.rstrip("/")
