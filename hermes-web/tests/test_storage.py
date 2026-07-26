import pytest

from hermes_web import storage


def test_create_and_get_user_roundtrip(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_user(conn, "dem", "hash123", "owner", "Дмитрий")
    row = storage.get_user(conn, "dem")
    assert row["username"] == "dem"
    assert row["password_hash"] == "hash123"
    assert row["role"] == "owner"
    assert row["display_name"] == "Дмитрий"


def test_get_user_missing_returns_none(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    assert storage.get_user(conn, "nobody") is None


def test_create_user_duplicate_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_user(conn, "dem", "hash123", "owner", "Дмитрий")
    with pytest.raises(Exception):
        storage.create_user(conn, "dem", "other", "owner", "Дмитрий 2")


def test_web_session_roundtrip_and_expiry(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_web_session(conn, "tok1", "dem", expires_at=1000.0)
    row = storage.get_web_session(conn, "tok1", now=500.0)
    assert row["username"] == "dem"
    assert storage.get_web_session(conn, "tok1", now=1500.0) is None
    assert storage.get_web_session(conn, "missing", now=500.0) is None


def test_delete_web_session_removes_it(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_web_session(conn, "tok1", "dem", expires_at=1000.0)
    storage.delete_web_session(conn, "tok1")
    assert storage.get_web_session(conn, "tok1", now=500.0) is None


def test_chat_session_roundtrip(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(
        conn, "chat1", "dem", "/workspace/dem/ALL/2026-07-26_chat-abc",
        "web_abc123", created_at=100.0,
    )
    row = storage.get_chat_session(conn, "chat1")
    assert row["user"] == "dem"
    assert row["project_path"] == "/workspace/dem/ALL/2026-07-26_chat-abc"
    assert row["hermes_session_id"] == "web_abc123"
    assert row["created_at"] == 100.0
    assert row["last_message_at"] is None


def test_get_chat_session_missing_returns_none(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    assert storage.get_chat_session(conn, "nope") is None


def test_touch_chat_session_updates_last_message_at(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/p", "web_1", created_at=100.0)
    storage.touch_chat_session(conn, "chat1", last_message_at=200.0)
    row = storage.get_chat_session(conn, "chat1")
    assert row["last_message_at"] == 200.0
