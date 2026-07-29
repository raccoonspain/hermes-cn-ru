import asyncio
import os
import sys
import threading
import time

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
async def test_create_quick_chat_leaves_no_orphan_project_when_hermes_session_fails(tmp_path, monkeypatch):
    # finding 7 финального ревью: раньше каталог проекта + about.md +
    # запись в project_index заводились ДО hermes_client.create_session —
    # падение (Hermes лежит, самый реалистичный сценарий сбоя) оставляло
    # "призрачный" проект без чата, и каждый ретрай в даунтайм добавлял ещё
    # один. create_session должен идти первым.
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    async def failing_create_session(http_session, base_url, api_key, session_id):
        raise hermes_client.HermesClientError("create_session failed: 503 Service Unavailable")

    monkeypatch.setattr(quickchat.hermes_client, "create_session", failing_create_session)

    with pytest.raises(hermes_client.HermesClientError):
        await quickchat.create_quick_chat(conn, http_session=None, config=config, user="dem")

    all_dir = os.path.join(str(tmp_path / "workspace"), "dem", "ALL")
    assert not os.path.isdir(all_dir) or os.listdir(all_dir) == []


@pytest.mark.asyncio
async def test_create_quick_chat_runs_index_update_without_blocking_event_loop(tmp_path, monkeypatch):
    # finding 4 финального ревью: project_index_core.index_update может
    # дойти до синхронного requests.post (эмбеддинг через wormsoft.ru, до
    # ~44с в худшем случае) прямо внутри однопоточного event loop aiohttp —
    # это замораживает ВЕСЬ процесс, а не только этот запрос. Проверяем два
    # свойства: (1) index_update реально выполняется в другом потоке, и
    # (2) пока он "блокируется" (тут — sleep), event loop остаётся
    # отзывчивым — параллельная корутина продолжает тикать.
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    call_thread_name = {}

    def fake_index_update(user, project_path, **kwargs):
        call_thread_name["name"] = threading.current_thread().name
        time.sleep(0.2)  # имитирует блокирующий HTTP-вызов эмбеддинга
        return {"path": project_path, "indexed": False, "message": "ok"}

    monkeypatch.setattr(quickchat.project_index_core, "index_update", fake_index_update)

    ticks = []

    async def ticker():
        for i in range(10):
            await asyncio.sleep(0.02)
            ticks.append(i)

    ticker_task = asyncio.create_task(ticker())
    await quickchat.create_quick_chat(conn, http_session=None, config=config, user="dem")
    await ticker_task

    assert call_thread_name["name"] != threading.current_thread().name
    # Если бы index_update блокировал event loop напрямую, ticker не успел
    # бы сделать почти ни одного тика за те же 0.2с — он получил бы
    # управление только после того, как index_update целиком завершится.
    assert len(ticks) >= 5


@pytest.mark.asyncio
async def test_send_message_forwards_project_path_as_system_message(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    host_project_path = str(tmp_path / "workspace" / "dem" / "ALL" / "2026-07-26_x")
    storage.create_chat_session(conn, "chat1", "dem", host_project_path, "web_x", created_at=1.0)

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
    assert host_project_path not in captured["system_message"]

    row = storage.get_chat_session(conn, "chat1")
    assert row["last_message_at"] is not None


@pytest.mark.asyncio
async def test_send_message_ensures_ownership_before_dispatch(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    host_project_path = str(tmp_path / "workspace" / "dem" / "ALL" / "2026-07-26_x")
    storage.create_chat_session(conn, "chat1", "dem", host_project_path, "web_x", created_at=1.0)

    calls = []

    async def fake_ensure_ownership(project_root):
        calls.append(project_root)

    monkeypatch.setattr(quickchat.permissions, "ensure_ownership", fake_ensure_ownership)

    async def fake_stream_chat(http_session, base_url, api_key, hermes_session_id, message, system_message=None):
        # На момент вызова стриминга самопочинка уже должна была отработать.
        assert calls == [host_project_path]
        yield "done", {}

    monkeypatch.setattr(quickchat.hermes_client, "stream_chat", fake_stream_chat)

    events = []
    async for name, payload in quickchat.send_message(conn, http_session=None, config=config, chat_session_id="chat1", text="привет"):
        events.append((name, payload))

    assert calls == [host_project_path]


def test_sandbox_project_path_replaces_workspace_root_with_container_mount(tmp_path):
    config = _config(tmp_path)
    host_path = str(tmp_path / "workspace" / "dem" / "ALL" / "2026-07-26_x")
    assert quickchat._sandbox_project_path(config, host_path) == "/workspace/dem/ALL/2026-07-26_x"


def test_sandbox_project_path_leaves_non_matching_path_untouched(tmp_path):
    config = _config(tmp_path)
    # Путь, не лежащий под workspace_root — не трогаем (защитный случай,
    # не должен встречаться в реальности, но конвертер не должен упасть
    # или вернуть мусор).
    assert quickchat._sandbox_project_path(config, "/some/other/path") == "/some/other/path"


def test_system_message_requires_absolute_sandbox_path():
    msg = quickchat._system_message_for("/workspace/dem/ALL/2026-07-26_x")
    assert "write_file" in msg or "read_file" in msg
    assert "/workspace/dem/ALL/2026-07-26_x" in msg
    assert "абсолютн" in msg.lower()
    assert "относительн" not in msg.lower()


def test_system_message_points_deliverables_to_result_bucket():
    msg = quickchat._system_message_for("/workspace/dem/ALL/2026-07-26_x")
    assert "result/" in msg


def test_is_valid_result_target_accepts_root_and_nested():
    assert quickchat._is_valid_result_target("result") is True
    assert quickchat._is_valid_result_target("result/kirik") is True
    assert quickchat._is_valid_result_target("result/kirik/3-23-29") is True


def test_is_valid_result_target_rejects_traversal_and_other_buckets():
    assert quickchat._is_valid_result_target("result/..") is False
    assert quickchat._is_valid_result_target("../etc") is False
    assert quickchat._is_valid_result_target("source/x") is False
    assert quickchat._is_valid_result_target("resultx") is False
    assert quickchat._is_valid_result_target("result/") is False
    assert quickchat._is_valid_result_target("") is False


def test_system_message_adds_result_target_instruction_when_valid():
    msg = quickchat._system_message_for("/workspace/dem/ALL/x", result_target="result/kirik")
    assert "/workspace/dem/ALL/x/result/kirik" in msg
    assert "спроси пользователя" in msg


def test_system_message_ignores_invalid_result_target():
    msg = quickchat._system_message_for("/workspace/dem/ALL/x", result_target="../etc")
    assert "спроси пользователя" not in msg
    assert "../etc" not in msg


def test_system_message_without_result_target_unchanged():
    msg = quickchat._system_message_for("/workspace/dem/ALL/x")
    assert "спроси пользователя" not in msg


@pytest.mark.asyncio
async def test_send_message_forwards_result_target_to_system_message(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    host_project_path = str(tmp_path / "workspace" / "dem" / "ALL" / "2026-07-26_x")
    storage.create_chat_session(conn, "chat1", "dem", host_project_path, "web_x", created_at=1.0)

    captured = {}

    async def fake_stream_chat(http_session, base_url, api_key, hermes_session_id, message, system_message=None):
        captured["system_message"] = system_message
        yield "done", {}

    monkeypatch.setattr(quickchat.hermes_client, "stream_chat", fake_stream_chat)

    async for _ in quickchat.send_message(
        conn, http_session=None, config=config, chat_session_id="chat1", text="привет", result_target="result/kirik",
    ):
        pass

    assert "/workspace/dem/ALL/2026-07-26_x/result/kirik" in captured["system_message"]


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


@pytest.mark.asyncio
async def test_get_or_open_session_creates_new_session_for_existing_project(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )

    created_sessions = []

    async def fake_create_session(http_session, base_url, api_key, session_id):
        created_sessions.append(session_id)
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    result = await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    assert result["hermes_session_id"] == created_sessions[0]
    row = storage.get_chat_session(conn, result["chat_session_id"])
    assert row["project_path"] == str(project_dir)


@pytest.mark.asyncio
async def test_get_or_open_session_reuses_existing_session(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )
    storage.create_chat_session(conn, "chat1", "dem", str(project_dir), "web_existing", created_at=1.0)

    async def failing_create_session(*args, **kwargs):
        raise AssertionError("не должно вызываться повторно для уже открытого проекта")

    monkeypatch.setattr(quickchat.hermes_client, "create_session", failing_create_session)

    result = await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    assert result["chat_session_id"] == "chat1"
    assert result["hermes_session_id"] == "web_existing"


@pytest.mark.asyncio
async def test_get_or_open_session_unknown_project_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    with pytest.raises(quickchat.project_index_core.ProjectIndexError):
        await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/nope")


@pytest.mark.asyncio
async def test_get_or_open_session_leaves_no_orphan_when_hermes_fails(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )

    async def failing_create_session(http_session, base_url, api_key, session_id):
        raise hermes_client.HermesClientError("create_session failed: 503")

    monkeypatch.setattr(quickchat.hermes_client, "create_session", failing_create_session)

    with pytest.raises(hermes_client.HermesClientError):
        await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    assert storage.get_chat_session_for_project(conn, "dem", str(project_dir)) is None
