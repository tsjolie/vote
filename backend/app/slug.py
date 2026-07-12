"""Base62 slug generation for poll URLs (non-sequential, non-guessable)."""

from __future__ import annotations

import secrets

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def new_slug(length: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
