import pytest

from hermes_web import auth


def test_hash_password_and_verify_roundtrip():
    hashed = auth.hash_password("correct-horse-battery-staple")
    assert hashed != "correct-horse-battery-staple"
    assert auth.verify_password("correct-horse-battery-staple", hashed) is True


def test_verify_password_wrong_password_returns_false():
    hashed = auth.hash_password("correct-horse-battery-staple")
    assert auth.verify_password("wrong-password", hashed) is False


def test_verify_password_garbage_hash_returns_false():
    assert auth.verify_password("anything", "not-a-real-hash") is False


def test_generate_session_token_is_random_and_long():
    tokens = {auth.generate_session_token() for _ in range(20)}
    assert len(tokens) == 20
    assert all(len(t) >= 32 for t in tokens)


def test_rate_limiter_allows_up_to_limit_then_blocks():
    limiter = auth.RateLimiter(max_attempts=5, window_seconds=300)
    key = "1.2.3.4:dem"
    for _ in range(5):
        assert limiter.allow(key, now=1000.0) is True
    assert limiter.allow(key, now=1000.0) is False


def test_rate_limiter_resets_after_window():
    limiter = auth.RateLimiter(max_attempts=2, window_seconds=300)
    key = "1.2.3.4:dem"
    assert limiter.allow(key, now=1000.0) is True
    assert limiter.allow(key, now=1001.0) is True
    assert limiter.allow(key, now=1001.0) is False
    assert limiter.allow(key, now=1302.0) is True


def test_rate_limiter_keys_are_independent():
    limiter = auth.RateLimiter(max_attempts=1, window_seconds=300)
    assert limiter.allow("user-a", now=1000.0) is True
    assert limiter.allow("user-b", now=1000.0) is True
    assert limiter.allow("user-a", now=1000.0) is False
