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
async def test_create_quick_chat_logs_chat_start_event(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    result = await quickchat.create_quick_chat(conn, http_session=None, config=config, user="dem")

    events = storage.list_events(conn)
    assert len(events) == 1
    assert events[0]["actor"] == "dem"
    assert events[0]["verb"] == "chat.start"
    assert events[0]["detail"] == result["project_path"]


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
async def test_create_quick_chat_creates_agents_and_history_md(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    result = await quickchat.create_quick_chat(conn, http_session=None, config=config, user="dem")

    agents_path = os.path.join(result["project_path"], "AGENTS.md")
    history_path = os.path.join(result["project_path"], "history.md")
    assert os.path.isfile(agents_path)
    assert os.path.isfile(history_path)

    agents_text = open(agents_path, encoding="utf-8").read()
    assert "result/" in agents_text
    assert "history.md" in agents_text

    history_text = open(history_path, encoding="utf-8").read()
    assert "append-only" in history_text


@pytest.mark.asyncio
async def test_create_quick_chat_creates_bucket_folders(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    result = await quickchat.create_quick_chat(conn, http_session=None, config=config, user="dem")

    for bucket in ("source", "outer", "result"):
        assert os.path.isdir(os.path.join(result["project_path"], bucket))


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


def test_agents_md_block_returns_empty_when_file_missing(tmp_path):
    assert quickchat._agents_md_block(str(tmp_path / "nope")) == ""


def test_agents_md_block_returns_content_when_present(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "AGENTS.md").write_text("# Мои правила\nПишем тесты.", encoding="utf-8")

    block = quickchat._agents_md_block(str(project_dir))

    assert "Конвенции проекта (AGENTS.md):" in block
    assert "Мои правила" in block


def test_agents_md_block_truncates_when_too_long(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "AGENTS.md").write_text("x" * (quickchat.AGENTS_MD_MAX_CHARS + 1000), encoding="utf-8")

    block = quickchat._agents_md_block(str(project_dir))

    assert "[...обрезано, полный текст в AGENTS.md]" in block
    assert len(block) < quickchat.AGENTS_MD_MAX_CHARS + 1000


def test_agents_md_block_returns_empty_for_blank_file(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "AGENTS.md").write_text("   \n\n  ", encoding="utf-8")
    assert quickchat._agents_md_block(str(project_dir)) == ""


def test_agents_md_block_logs_and_returns_empty_on_read_error(tmp_path, caplog):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "AGENTS.md").mkdir()  # директория вместо файла → open() кидает OSError

    with caplog.at_level("WARNING", logger="hermes_web.quickchat"):
        block = quickchat._agents_md_block(str(project_dir))

    assert block == ""
    assert "AGENTS.md" in caplog.text


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


def test_is_valid_result_target_rejects_non_string_without_raising():
    assert quickchat._is_valid_result_target(123) is False
    assert quickchat._is_valid_result_target(True) is False
    assert quickchat._is_valid_result_target(["result"]) is False
    assert quickchat._is_valid_result_target(None) is False


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


def test_system_message_appends_agents_md_block_when_provided():
    msg = quickchat._system_message_for("/workspace/dem/ALL/x", agents_md_block="\n\nКонвенции проекта (AGENTS.md):\nМои правила")
    assert "Конвенции проекта (AGENTS.md):" in msg
    assert "Мои правила" in msg


def test_system_message_agents_md_block_defaults_to_empty():
    msg = quickchat._system_message_for("/workspace/dem/ALL/x")
    assert "Конвенции проекта (AGENTS.md):" not in msg


def test_system_message_uses_fallback_conventions_when_agents_md_block_empty():
    msg = quickchat._system_message_for("/workspace/dem/ALL/x")
    assert "подпапку result/" in msg
    assert "проверь ответ инструмента" in msg


def test_system_message_does_not_duplicate_conventions_when_agents_md_block_present():
    msg = quickchat._system_message_for(
        "/workspace/dem/ALL/x", agents_md_block="\n\nКонвенции проекта (AGENTS.md):\nМои правила",
    )
    assert msg.count("подпапку result/") == 0  # fallback text absent — только то, что принёс agents_md_block
    assert msg.count("Мои правила") == 1


def test_system_message_agents_md_block_comes_after_result_target_hint():
    msg = quickchat._system_message_for(
        "/workspace/dem/ALL/x", result_target="result/kirik",
        agents_md_block="\n\nКонвенции проекта (AGENTS.md):\nМои правила",
    )
    assert msg.index("спроси пользователя") < msg.index("Конвенции проекта (AGENTS.md):")


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
async def test_send_message_includes_agents_md_content_when_present(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    host_project_path = tmp_path / "workspace" / "dem" / "ALL" / "2026-07-26_x"
    host_project_path.mkdir(parents=True)
    (host_project_path / "AGENTS.md").write_text("# Мои личные правила\nВсегда пиши по-русски.", encoding="utf-8")
    storage.create_chat_session(conn, "chat1", "dem", str(host_project_path), "web_x", created_at=1.0)

    async def fake_ensure_ownership(project_root):
        pass

    monkeypatch.setattr(quickchat.permissions, "ensure_ownership", fake_ensure_ownership)

    captured = {}

    async def fake_stream_chat(http_session, base_url, api_key, hermes_session_id, message, system_message=None):
        captured["system_message"] = system_message
        yield "done", {}

    monkeypatch.setattr(quickchat.hermes_client, "stream_chat", fake_stream_chat)

    async for _ in quickchat.send_message(conn, http_session=None, config=config, chat_session_id="chat1", text="привет"):
        pass

    assert "Мои личные правила" in captured["system_message"]
    assert "Всегда пиши по-русски." in captured["system_message"]


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
async def test_get_or_open_session_logs_chat_start_only_once(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    session_counter = {"n": 0}

    async def fake_create_session(http_session, base_url, api_key, session_id):
        session_counter["n"] += 1
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    created = await quickchat.create_project(conn, config, "dem", "ALL", "Тест")
    project_path = created["project_path"]

    # create_project не заводит чат-сессию сам — первый get_or_open_session
    # на этот проект должен залогировать ровно одно событие chat.start.
    await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path=project_path)
    await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path=project_path)

    events = [e for e in storage.list_events(conn) if e["verb"] == "chat.start"]
    assert len(events) == 1
    assert events[0]["detail"] == project_path


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
async def test_get_or_open_session_backfills_missing_agents_and_history_md(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )
    # AGENTS.md/history.md намеренно отсутствуют — проект "созданный до этой фичи".

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    assert os.path.isfile(project_dir / "AGENTS.md")
    assert os.path.isfile(project_dir / "history.md")
    assert "append-only" in (project_dir / "history.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_get_or_open_session_backfills_missing_bucket_folders(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )
    # source/outer/result намеренно отсутствуют — проект "созданный до этой фичи".

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    for bucket in ("source", "outer", "result"):
        assert os.path.isdir(project_dir / bucket)


@pytest.mark.asyncio
async def test_get_or_open_session_does_not_touch_existing_bucket_contents(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )
    (project_dir / "source").mkdir()
    (project_dir / "source" / "notes.txt").write_text("не трогать", encoding="utf-8")

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    assert (project_dir / "source" / "notes.txt").read_text(encoding="utf-8") == "не трогать"
    assert os.path.isdir(project_dir / "outer")
    assert os.path.isdir(project_dir / "result")


@pytest.mark.asyncio
async def test_get_or_open_session_logs_and_continues_when_bucket_path_is_a_file(tmp_path, monkeypatch, caplog):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )
    # "source" занят файлом, а не папкой — os.makedirs(..., exist_ok=True)
    # в этом случае бросает FileExistsError (подкласс OSError).
    (project_dir / "source").write_text("не папка", encoding="utf-8")

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    with caplog.at_level("WARNING", logger="hermes_web.quickchat"):
        await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    assert "source" in caplog.text
    # Остальные два бакета создались несмотря на ошибку первого.
    assert os.path.isdir(project_dir / "outer")
    assert os.path.isdir(project_dir / "result")
    # Файл "source" остался нетронутым, а не превратился в директорию силой.
    assert (project_dir / "source").is_file()


@pytest.mark.asyncio
async def test_get_or_open_session_does_not_overwrite_existing_agents_md(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )
    (project_dir / "AGENTS.md").write_text("# Мои личные правила проекта\n", encoding="utf-8")
    (project_dir / "history.md").write_text("# Моя личная история проекта\n", encoding="utf-8")

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    assert (project_dir / "AGENTS.md").read_text(encoding="utf-8") == "# Мои личные правила проекта\n"
    assert (project_dir / "history.md").read_text(encoding="utf-8") == "# Моя личная история проекта\n"


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


@pytest.mark.asyncio
async def test_create_quick_chat_then_get_or_open_session_reuses_same_session(tmp_path, monkeypatch):
    """Regression test for the core invariant: after create_quick_chat creates
    a project, calling get_or_open_session with that project_path must REUSE
    the same chat session, not create a second one.

    This tests the redirect flow: /api/quick-chat returns project_path, which
    gets passed as a URL parameter to project-workspace.html, which then calls
    /api/projects/open, which calls get_or_open_session. The session created
    by create_quick_chat must be found and reused, not discarded.
    """
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    created_sessions = []

    async def fake_create_session(http_session, base_url, api_key, session_id):
        created_sessions.append(session_id)
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    # Step 1: Call create_quick_chat (mocking only Hermes HTTP call)
    create_result = await quickchat.create_quick_chat(conn, http_session=None, config=config, user="dem")
    original_chat_session_id = create_result["chat_session_id"]
    original_hermes_session_id = create_result["hermes_session_id"]
    project_path_absolute = create_result["project_path"]

    # Convert absolute path to relative (what get_or_open_session expects)
    workspace_root = config.workspace_root
    project_path_relative = os.path.relpath(project_path_absolute, workspace_root)

    # Step 2: Call get_or_open_session with the project path from create_quick_chat
    # This simulates what happens when redirecting to project-workspace.html?path=<project_path>
    open_result = await quickchat.get_or_open_session(
        conn, http_session=None, config=config, user="dem", project_path=project_path_relative
    )

    # Step 3: Verify the session was REUSED, not recreated
    assert open_result["chat_session_id"] == original_chat_session_id
    assert open_result["hermes_session_id"] == original_hermes_session_id
    assert open_result["project_path"] == project_path_absolute

    # Step 4: Verify create_session was called exactly once total (only in create_quick_chat)
    # If get_or_open_session had created a new session, we'd have 2 calls here
    assert len(created_sessions) == 1, f"Expected hermes_client.create_session called 1 time, but was called {len(created_sessions)} times"


@pytest.mark.asyncio
async def test_send_message_logs_result_target_and_reinforcement(tmp_path, monkeypatch, caplog):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    host_project_path = str(tmp_path / "workspace" / "dem" / "ALL" / "2026-07-26_x")
    storage.create_chat_session(conn, "chat1", "dem", host_project_path, "web_x", created_at=1.0)

    async def fake_ensure_ownership(project_root):
        pass

    monkeypatch.setattr(quickchat.permissions, "ensure_ownership", fake_ensure_ownership)

    async def fake_stream_chat(http_session, base_url, api_key, hermes_session_id, message, system_message=None):
        yield "done", {}

    monkeypatch.setattr(quickchat.hermes_client, "stream_chat", fake_stream_chat)

    with caplog.at_level("INFO", logger="hermes_web.quickchat"):
        async for _ in quickchat.send_message(
            conn, http_session=None, config=config, chat_session_id="chat1", text="привет",
            result_target="result/kirik",
        ):
            pass

    assert "chat_session_id=chat1" in caplog.text
    assert "result_target='result/kirik'" in caplog.text
    assert "reinforced=True" in caplog.text


@pytest.mark.asyncio
async def test_send_message_logs_missing_result_target_as_not_reinforced(tmp_path, monkeypatch, caplog):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    host_project_path = str(tmp_path / "workspace" / "dem" / "ALL" / "2026-07-26_y")
    storage.create_chat_session(conn, "chat2", "dem", host_project_path, "web_y", created_at=1.0)

    async def fake_ensure_ownership(project_root):
        pass

    monkeypatch.setattr(quickchat.permissions, "ensure_ownership", fake_ensure_ownership)

    async def fake_stream_chat(http_session, base_url, api_key, hermes_session_id, message, system_message=None):
        yield "done", {}

    monkeypatch.setattr(quickchat.hermes_client, "stream_chat", fake_stream_chat)

    with caplog.at_level("INFO", logger="hermes_web.quickchat"):
        async for _ in quickchat.send_message(
            conn, http_session=None, config=config, chat_session_id="chat2", text="привет",
        ):
            pass

    assert "chat_session_id=chat2" in caplog.text
    assert "result_target=None" in caplog.text
    assert "reinforced=False" in caplog.text


@pytest.mark.asyncio
async def test_create_project_in_group_uses_human_readable_slug(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    result = await quickchat.create_project(conn, config, "dem", "1С", "Новый проект")

    expected_leaf = quickchat.projects.slugify("Новый проект")
    assert result["group"] == "1С"
    assert result["project_path"] == str(tmp_path / "workspace" / "dem" / "1С" / expected_leaf)
    assert os.path.isfile(os.path.join(result["project_path"], "about.md"))


@pytest.mark.asyncio
async def test_create_project_in_all_uses_date_prefixed_technical_slug(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    result = await quickchat.create_project(conn, config, "dem", "ALL", "Быстрый разговор про физику")

    leaf = os.path.basename(result["project_path"])
    assert quickchat.project_index_core._DATE_PREFIX_RE.match(leaf)
    assert leaf.split("_", 1)[1].startswith("chat-")


@pytest.mark.asyncio
async def test_create_project_creates_full_scaffold(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    result = await quickchat.create_project(conn, config, "dem", "1С", "Проект")

    for name in ("about.md", "AGENTS.md", "history.md"):
        assert os.path.isfile(os.path.join(result["project_path"], name))
    for bucket in ("source", "outer", "result"):
        assert os.path.isdir(os.path.join(result["project_path"], bucket))


@pytest.mark.asyncio
async def test_create_project_indexes_it(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    result = await quickchat.create_project(conn, config, "dem", "1С", "Учёт материалов")

    indexed = project_index_core.storage.get_project(
        project_index_core.storage.get_connection(config.project_index_db_path),
        result["project_path"],
    )
    assert indexed["title"] == "Учёт материалов"


@pytest.mark.asyncio
async def test_create_project_blank_title_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    with pytest.raises(quickchat.QuickChatError):
        await quickchat.create_project(conn, config, "dem", "ALL", "   ")


@pytest.mark.asyncio
async def test_create_project_collision_raises_and_does_not_touch_disk(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    first = await quickchat.create_project(conn, config, "dem", "1С", "Проект")
    mtime_before = os.path.getmtime(first["project_path"])

    with pytest.raises(quickchat.QuickChatError):
        await quickchat.create_project(conn, config, "dem", "1С", "Проект")

    assert os.path.getmtime(first["project_path"]) == mtime_before


@pytest.mark.asyncio
async def test_create_project_group_traversal_raises_and_does_not_touch_disk(tmp_path):
    """group приходит из HTTP (POST /api/projects) — та же уязвимость, что
    ревью 2026-07-26 нашло в move_project для new_group: без валидации
    итогового пути через resolve_project_path запрос вида
    group="../rost" создал бы папку в чужом пространстве пользователя."""
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    (tmp_path / "workspace" / "rost").mkdir(parents=True)

    with pytest.raises(quickchat.QuickChatError):
        await quickchat.create_project(conn, config, "dem", "../rost", "Угнанный проект")

    assert list((tmp_path / "workspace" / "rost").iterdir()) == []


@pytest.mark.asyncio
async def test_create_project_rejects_hidden_group(tmp_path):
    """group='.trash' не эскейпит пространство пользователя (resolve_project_path
    его пропускает), но создаёт проект в скрытой служебной папке — видимый в
    «везде»-поиске и невидимый в сайдбаре (list_groups прячет dot-папки)."""
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    with pytest.raises(quickchat.QuickChatError):
        await quickchat.create_project(conn, config, "dem", ".trash", "Скрытый проект")


@pytest.mark.asyncio
async def test_create_project_rejects_nested_group(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    with pytest.raises(quickchat.QuickChatError):
        await quickchat.create_project(conn, config, "dem", "ALL/deep/deeper", "Вложенный проект")


@pytest.mark.asyncio
async def test_create_project_rejects_empty_group(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    with pytest.raises(quickchat.QuickChatError):
        await quickchat.create_project(conn, config, "dem", "", "Проект без группы")
