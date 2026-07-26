"""Password hashing, session tokens, and a simple in-memory login rate limiter."""
from __future__ import annotations

import secrets
from collections import defaultdict, deque
from typing import Deque, Dict

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHash):
        return False


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


class RateLimiter:
    """Sliding-window limiter, in-memory — resets on process restart (acceptable
    for a two-user app; see Global Constraints)."""

    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._attempts: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float) -> bool:
        attempts = self._attempts[key]
        cutoff = now - self._window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if len(attempts) >= self._max_attempts:
            return False
        attempts.append(now)
        return True
