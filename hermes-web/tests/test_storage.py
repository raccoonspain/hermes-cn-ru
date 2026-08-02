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


def test_group_meta_missing_returns_none(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    assert storage.get_group_meta(conn, "dem", "dom-i-remont") is None


def test_group_meta_roundtrip(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.upsert_group_meta(conn, "dem", "dom-i-remont", "Дом и ремонт", "🏠", True, created_at="2026-07-26T10:00:00")
    row = storage.get_group_meta(conn, "dem", "dom-i-remont")
    assert row["display_name"] == "Дом и ремонт"
    assert row["emoji"] == "🏠"
    assert bool(row["pinned"]) is True


def test_upsert_group_meta_updates_existing_row(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.upsert_group_meta(conn, "dem", "it", "IT", "🖥️", False, created_at="2026-07-26T10:00:00")
    storage.upsert_group_meta(conn, "dem", "it", "IT / DevOps", "🖥️", True, created_at="2026-07-26T10:00:00")
    row = storage.get_group_meta(conn, "dem", "it")
    assert row["display_name"] == "IT / DevOps"
    assert bool(row["pinned"]) is True


def test_upsert_group_meta_preserves_created_at_on_conflict(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.upsert_group_meta(conn, "dem", "it", "IT", "🖥️", False, created_at="2026-01-01T00:00:00")
    storage.upsert_group_meta(conn, "dem", "it", "IT / DevOps", "🖥️", True, created_at="2099-01-01T00:00:00")
    row = storage.get_group_meta(conn, "dem", "it")
    assert row["created_at"] == "2026-01-01T00:00:00"


def test_list_group_meta_scoped_to_user(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.upsert_group_meta(conn, "dem", "it", "IT", "🖥️", False, created_at="t")
    storage.upsert_group_meta(conn, "rost", "eng", "Английский", "🇬🇧", False, created_at="t")
    rows = storage.list_group_meta(conn, "dem")
    assert [r["slug"] for r in rows] == ["it"]


def test_update_chat_session_project_path_moves_reference(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/old/path", "web_1", created_at=1.0)
    storage.update_chat_session_project_path(conn, "/old/path", "/new/path")
    row = storage.get_chat_session(conn, "chat1")
    assert row["project_path"] == "/new/path"


def test_update_chat_session_project_path_noop_when_no_match(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/old/path", "web_1", created_at=1.0)
    storage.update_chat_session_project_path(conn, "/other/path", "/new/path")
    row = storage.get_chat_session(conn, "chat1")
    assert row["project_path"] == "/old/path"


def test_get_chat_session_for_project_returns_latest(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/p/a", "web_1", created_at=100.0)
    storage.create_chat_session(conn, "chat2", "dem", "/p/a", "web_2", created_at=200.0)
    row = storage.get_chat_session_for_project(conn, "dem", "/p/a")
    assert row["id"] == "chat2"


def test_get_chat_session_for_project_scoped_to_user(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/p/a", "web_1", created_at=100.0)
    assert storage.get_chat_session_for_project(conn, "rost", "/p/a") is None


def test_get_chat_session_for_project_missing_returns_none(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    assert storage.get_chat_session_for_project(conn, "dem", "/nope") is None


def test_list_users_returns_all_without_password_hash(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_user(conn, "dem", "hash1", "owner", "Дмитрий")
    storage.create_user(conn, "rost", "hash2", "participant", "Ростислав")
    users = storage.list_users(conn)
    assert {u["username"] for u in users} == {"dem", "rost"}
    dem = next(u for u in users if u["username"] == "dem")
    assert dem == {"username": "dem", "role": "owner", "display_name": "Дмитрий"}


def test_update_user_changes_display_name_and_role(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_user(conn, "rost", "hash2", "participant", "Ростислав")
    storage.update_user(conn, "rost", "Ростислав Н.", "owner")
    row = storage.get_user(conn, "rost")
    assert row["display_name"] == "Ростислав Н."
    assert row["role"] == "owner"
    assert row["username"] == "rost"


def test_update_user_password_changes_hash(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_user(conn, "dem", "oldhash", "owner", "Дмитрий")
    storage.update_user_password(conn, "dem", "newhash")
    row = storage.get_user(conn, "dem")
    assert row["password_hash"] == "newhash"


def test_count_active_sessions_counts_unexpired_only(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_web_session(conn, "tok1", "dem", expires_at=1000.0)
    storage.create_web_session(conn, "tok2", "dem", expires_at=1000.0)
    storage.create_web_session(conn, "tok3", "rost", expires_at=1000.0)
    storage.create_web_session(conn, "tok4", "rost", expires_at=10.0)  # уже истёк
    result = storage.count_active_sessions(conn, now=500.0)
    assert result == {"sessions": 3, "users": 2}


def test_get_last_activity_prefers_last_message_at_over_created_at(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/p/a", "web_1", created_at=100.0)
    storage.touch_chat_session(conn, "chat1", last_message_at=250.0)
    assert storage.get_last_activity(conn, "dem") == 250.0


def test_get_last_activity_falls_back_to_created_at_without_messages(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/p/a", "web_1", created_at=100.0)
    assert storage.get_last_activity(conn, "dem") == 100.0


def test_get_last_activity_returns_none_without_sessions(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    assert storage.get_last_activity(conn, "dem") is None


def test_log_event_and_list_events_newest_first(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.log_event(conn, "dem", "login", "")
    storage.log_event(conn, "dem", "project.create", "ALL/2026-08-02_x")
    events = storage.list_events(conn)
    assert [e["verb"] for e in events] == ["project.create", "login"]
    assert events[0]["actor"] == "dem"
    assert events[0]["detail"] == "ALL/2026-08-02_x"


def test_list_events_respects_limit(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    for i in range(5):
        storage.log_event(conn, "dem", "login", str(i))
    events = storage.list_events(conn, limit=2)
    assert len(events) == 2
    assert events[0]["detail"] == "4"
