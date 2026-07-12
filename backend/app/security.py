"""Password hashing (argon2id) and session token helpers."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()  # argon2id is the argon2-cffi default


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_session_token() -> str:
    """Opaque, random 256-bit token as hex."""
    return secrets.token_hex(32)


def session_expiry(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)
