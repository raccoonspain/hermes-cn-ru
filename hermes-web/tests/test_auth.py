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


def test_rate_limiter_prune_drops_key_once_its_deque_is_fully_expired():
    # Внутренняя реализация (_attempts, _prune) — сознательный компромисс:
    # это тест на ограничение памяти (finding 5 финального ревью), а не на
    # публичное поведение allow(). allow() сама всегда дописывает свежую
    # попытку сразу после прополки (если не заблокировано), так что снаружи
    # через allow() невозможно застать словарь с уже опустевшим — но ещё не
    # удалённым — deque; проверяем прополку напрямую через _prune().
    limiter = auth.RateLimiter(max_attempts=5, window_seconds=300)
    limiter.allow("1.2.3.4:ghost-user", now=1000.0)
    assert "1.2.3.4:ghost-user" in limiter._attempts

    # Окно истекло, и ключ больше никто не запрашивал (типичная спрей-атака —
    # атакующий не возвращается к уже использованным именам). Прополка должна
    # убрать опустевшую запись из словаря, а не оставить пустой deque висеть
    # там бесконечно.
    limiter._prune("1.2.3.4:ghost-user", now=1301.0)
    assert "1.2.3.4:ghost-user" not in limiter._attempts


def test_rate_limiter_hard_cap_clears_dict_instead_of_growing_unbounded():
    # Реалистичная атака: множество РАЗНЫХ ключей (ip:username), каждый
    # используется ровно один раз — их deque никогда не допрунивается через
    # собственный повторный allow(), поэтому единственная граница памяти —
    # жёсткий потолок числа ключей (defense-in-depth поверх _prune()).
    limiter = auth.RateLimiter(max_attempts=5, window_seconds=300)
    limiter._HARD_CAP_KEYS = 100  # маленький потолок, чтобы не гонять 10k итераций

    for i in range(150):
        limiter.allow(f"1.2.3.4:spray-user-{i}", now=1000.0)

    assert len(limiter._attempts) <= 100
