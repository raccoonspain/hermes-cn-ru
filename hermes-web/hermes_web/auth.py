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

    # Верхняя граница на число различных ключей одновременно в памяти —
    # защита в глубину сверх обычной очистки пустых записей ниже (см.
    # allow()): если она всё же переполнится (аномальный шторм из множества
    # разных IP/имён), сбрасываем всё разом, а не растим словарь бесконечно.
    _HARD_CAP_KEYS = 10_000

    def _prune(self, key: str, now: float) -> Deque[float]:
        """Удаляет протухшие попытки для key; если после этого deque пуст —
        убирает саму запись из словаря, а не оставляет пустой deque висеть
        в памяти навсегда. Ключ на публичном /login контролирует атакующий
        (ip:username), а неизвестные логины всё равно попадают сюда до
        проверки пароля — без этой очистки словарь растёт без предела
        (спрей из множества разных username = memory exhaustion на
        небольшом VPS). Возвращает актуальный deque (может быть новым,
        если запись пришлось пересоздать)."""
        attempts = self._attempts[key]
        cutoff = now - self._window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            del self._attempts[key]
        return self._attempts[key] if key in self._attempts else attempts

    def allow(self, key: str, now: float) -> bool:
        attempts = self._prune(key, now)
        if len(attempts) >= self._max_attempts:
            return False
        if len(self._attempts) >= self._HARD_CAP_KEYS:
            # Защита в глубину сверх _prune(): если число различных ключей
            # всё же переполнится (аномальный шторм из множества разных
            # IP/имён, каждый из которых используется лишь раз и потому
            # никогда не допрунится через свой собственный повторный
            # вызов), сбрасываем всё разом, а не растим словарь бесконечно.
            self._attempts.clear()
        self._attempts[key].append(now)
        return True
