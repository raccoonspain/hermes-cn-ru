import os
import sys

import pytest

sys.path.insert(0, os.environ["PROJECT_INDEX_PLUGIN_DIR"])
from project_index import core as project_index_core  # noqa: E402

from hermes_web import hermes_client, storage
from hermes_web import quickchat


def _config(tmp_path):
    return quickchat.Config(
        workspace_root=str(tmp_path / "workspace"),
        project_index_db_path=str(tmp_path / "project_index.db"),
        hermes_base_url="http://fake-hermes.invalid",
        hermes_api_key="fake-key",
        wormsoft_api_key=None,
    )


@pytest.mark.asyncio
async def test_create_quick_chat_creates_project_and_hermes_session(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    created_sessions = []

    async def fake_create_session(http_session, base_url, api_key, session_id):
        created_sessions.append(session_id)
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    result = await quickchat.create_quick_chat(conn, http_session=None, config=config, user="dem")

    assert result["chat_session_id"]
    assert result["project_path"].startswith(str(tmp_path / "workspace" / "dem" / "ALL"))
    assert result["hermes_session_id"] == created_sessions[0]

    about_path = os.path.join(result["project_path"], "about.md")
    assert os.path.isfile(about_path)

    row = storage.get_chat_session(conn, result["chat_session_id"])
    assert row["user"] == "dem"
    assert row["project_path"] == result["project_path"]
    assert row["hermes_session_id"] == result["hermes_session_id"]

    indexed = project_index_core.storage.get_project(
        project_index_core.storage.get_connection(config.project_index_db_path),
        result["project_path"],
    )
    assert indexed["title"].startswith("Новый разговор")


@pytest.mark.asyncio
async def test_send_message_forwards_project_path_as_system_message(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    storage.create_chat_session(conn, "chat1", "dem", "/workspace/dem/ALL/2026-07-26_x", "web_x", created_at=1.0)

    captured = {}

    async def fake_stream_chat(http_session, base_url, api_key, hermes_session_id, message, system_message=None):
        captured["hermes_session_id"] = hermes_session_id
        captured["message"] = message
        captured["system_message"] = system_message
        yield "assistant.delta", {"delta": "ok"}
        yield "done", {}

    monkeypatch.setattr(quickchat.hermes_client, "stream_chat", fake_stream_chat)

    events = []
    async for name, payload in quickchat.send_message(conn, http_session=None, config=config, chat_session_id="chat1", text="привет"):
        events.append((name, payload))

    assert events == [("assistant.delta", {"delta": "ok"}), ("done", {})]
    assert captured["hermes_session_id"] == "web_x"
    assert captured["message"] == "привет"
    assert "/workspace/dem/ALL/2026-07-26_x" in captured["system_message"]

    row = storage.get_chat_session(conn, "chat1")
    assert row["last_message_at"] is not None


@pytest.mark.asyncio
async def test_send_message_unknown_chat_session_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    with pytest.raises(quickchat.QuickChatError):
        async for _ in quickchat.send_message(conn, http_session=None, config=config, chat_session_id="nope", text="hi"):
            pass


@pytest.mark.asyncio
async def test_get_history_delegates_to_hermes_client(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    storage.create_chat_session(conn, "chat1", "dem", "/p", "web_x", created_at=1.0)

    async def fake_get_messages(http_session, base_url, api_key, hermes_session_id):
        assert hermes_session_id == "web_x"
        return [{"role": "user", "content": "hi"}]

    monkeypatch.setattr(quickchat.hermes_client, "get_messages", fake_get_messages)

    history = await quickchat.get_history(conn, http_session=None, config=config, chat_session_id="chat1")
    assert history == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_get_history_unknown_chat_session_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    with pytest.raises(quickchat.QuickChatError):
        await quickchat.get_history(conn, http_session=None, config=config, chat_session_id="nope")
