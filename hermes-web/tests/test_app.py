import asyncio
import json

import aiohttp
import pytest
from aiohttp import web

from hermes_web import auth, hermes_client, projects, quickchat, storage
from hermes_web.app import create_app


@pytest.fixture
def app_and_conn(tmp_path, monkeypatch):
    db_path = str(tmp_path / "hermes-web.db")
    conn = storage.get_connection(db_path)
    storage.create_user(conn, "dem", auth.hash_password("secret123"), "owner", "Дмитрий")
    # Второй пользователь — как в проде (см. docs/state.md): нужен, чтобы
    # тестировать межпользовательскую изоляцию (finding 6 финального ревью).
    storage.create_user(conn, "rost", auth.hash_password("secret456"), "participant", "Ростислав")
    conn.close()

    config = quickchat.Config(
        hermes_base_url="http://fake-hermes.invalid",
        hermes_api_key="fake-key",
        workspace_root=str(tmp_path / "workspace"),
        project_index_db_path=str(tmp_path / "project_index.db"),
    )
    # aiohttp's add_static() requires the directory to exist at app-creation
    # time (it resolves and stat()s the path immediately) — Task 7 is what
    # populates hermes-web/static/ for real, so tests use an empty tmp dir.
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    app = create_app(db_path=db_path, quickchat_config=config, cookie_secure=False, static_dir=str(static_dir))
    return app


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.post("/login", json={"username": "dem", "password": "wrong"})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_login_success_sets_cookie_and_returns_role(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.post("/login", json={"username": "dem", "password": "secret123"})
    assert resp.status == 200
    body = await resp.json()
    assert body == {"username": "dem", "role": "owner", "display_name": "Дмитрий"}
    assert "hermes_web_session" in [c.key for c in client.session.cookie_jar]


@pytest.mark.asyncio
async def test_me_without_cookie_returns_401(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.get("/api/me")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_me_after_login_returns_user(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.get("/api/me")
    assert resp.status == 200
    body = await resp.json()
    assert body["username"] == "dem"
    assert body["role"] == "owner"


@pytest.mark.asyncio
async def test_logout_clears_session(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/logout")
    assert resp.status == 200
    resp = await client.get("/api/me")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_quick_chat_requires_auth(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.post("/api/quick-chat")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_quick_chat_creates_project_when_authed(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_create_quick_chat(db_conn, http_session, config, user):
        return {"chat_session_id": "chat1", "project_path": "/w/dem/ALL/x", "hermes_session_id": "web_x"}

    monkeypatch.setattr("hermes_web.app.quickchat.create_quick_chat", fake_create_quick_chat)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/quick-chat")
    assert resp.status == 200
    body = await resp.json()
    assert body == {"chat_session_id": "chat1", "project_path": "/w/dem/ALL/x"}


@pytest.mark.asyncio
async def test_send_message_streams_sse_events(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_send_message(db_conn, http_session, config, chat_session_id, text):
        assert chat_session_id == "chat1"
        assert text == "привет"
        yield "assistant.delta", {"delta": "ok"}
        yield "done", {}

    monkeypatch.setattr("hermes_web.app.quickchat.send_message", fake_send_message)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/chat/chat1/send", json={"text": "привет"})
    assert resp.status == 200
    body = (await resp.read()).decode("utf-8")
    assert 'event: assistant.delta\ndata: {"delta": "ok"}' in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_send_message_forwards_result_target(aiohttp_client, app_and_conn, monkeypatch):
    captured = {}

    async def fake_send_message(db_conn, http_session, config, chat_session_id, text, result_target=None):
        captured["result_target"] = result_target
        yield "done", {}

    monkeypatch.setattr("hermes_web.app.quickchat.send_message", fake_send_message)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/chat/chat1/send", json={"text": "привет", "result_target": "result/kirik"})
    assert resp.status == 200
    await resp.read()
    assert captured["result_target"] == "result/kirik"


@pytest.mark.asyncio
async def test_send_message_omits_result_target_when_absent(aiohttp_client, app_and_conn, monkeypatch):
    # Существующие клиенты (и большинство текущих тестов этого файла) не
    # шлют result_target вовсе — fake_send_message без этого параметра
    # должен продолжать работать без TypeError по неожиданному kwarg.
    async def fake_send_message(db_conn, http_session, config, chat_session_id, text):
        yield "done", {}

    monkeypatch.setattr("hermes_web.app.quickchat.send_message", fake_send_message)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/chat/chat1/send", json={"text": "привет"})
    assert resp.status == 200
    body = (await resp.read()).decode("utf-8")
    assert "event: error" not in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_send_message_non_string_result_target_does_not_crash_sse_stream(
    aiohttp_client, app_and_conn, monkeypatch, tmp_path,
):
    # Финальное ревью, finding "Important": result_target из тела запроса не
    # приводится к str (в отличие от text), а _is_valid_result_target раньше
    # предполагал, что аргумент всегда str, и падал с AttributeError на
    # .startswith для нестроковых значений (например {"result_target": 123}).
    # Падение происходило внутри async-генератора уже после response.prepare()
    # — клиент получал оборванный SSE-поток вместо event: error/event: done.
    # Здесь используется настоящий quickchat.send_message (без подмены), чтобы
    # доказать фикс на том же уровне, где баг наблюдался изначально — подменён
    # только hermes_client.stream_chat, самый нижний уровень.
    conn = app_and_conn["db"]
    host_project_path = str(tmp_path / "workspace" / "dem" / "ALL" / "x")
    storage.create_chat_session(conn, "chat1", "dem", host_project_path, "web_x", created_at=1.0)

    async def fake_stream_chat(http_session, base_url, api_key, hermes_session_id, message, system_message=None):
        yield "assistant.delta", {"delta": "ok"}
        yield "done", {}

    monkeypatch.setattr("hermes_web.app.quickchat.hermes_client.stream_chat", fake_stream_chat)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/chat/chat1/send", json={"text": "hi", "result_target": 123})
    assert resp.status == 200
    body = (await resp.read()).decode("utf-8")
    assert "event: error" not in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_send_message_emits_heartbeat_during_silent_gap(aiohttp_client, app_and_conn, monkeypatch):
    # Держим SSE-соединение живым во время долгих тихих пауз агента (ждёт
    # ответа wormsoft.ru, гоняет докер) — иначе прокси/браузер обрывают
    # простаивающее соединение раньше, чем агент реально закончит (см.
    # инцидент 2026-07-28: ответ пришёл, но клиент уже отвалился и не
    # переспросил историю).
    monkeypatch.setattr("hermes_web.app.HEARTBEAT_INTERVAL", 0.05)

    async def fake_send_message(db_conn, http_session, config, chat_session_id, text):
        await asyncio.sleep(0.3)
        yield "assistant.delta", {"delta": "ok"}
        yield "done", {}

    monkeypatch.setattr("hermes_web.app.quickchat.send_message", fake_send_message)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/chat/chat1/send", json={"text": "привет"})
    assert resp.status == 200
    body = (await resp.read()).decode("utf-8")
    assert body.count(": ping\n\n") >= 3
    ping_pos = body.index(": ping")
    delta_pos = body.index("event: assistant.delta")
    assert ping_pos < delta_pos
    assert "event: done" in body


@pytest.mark.asyncio
async def test_send_message_stops_advancing_generator_after_write_failure(aiohttp_client, app_and_conn, monkeypatch):
    # Регрессия: раньше следующий agen.__anext__() планировался ДО записи
    # текущего payload — если клиент уже отвалился (write бросает), уже
    # запущенная фоновая задача всё равно доводила генератор (и реальный
    # запрос к Hermes внутри него) до следующего yield, никем не дожидаемая.
    advanced = []

    async def fake_send_message(db_conn, http_session, config, chat_session_id, text):
        advanced.append("a")
        yield "assistant.delta", {"delta": "one"}
        advanced.append("b")
        yield "assistant.delta", {"delta": "two"}
        advanced.append("c")
        yield "done", {}

    monkeypatch.setattr("hermes_web.app.quickchat.send_message", fake_send_message)

    original_write = web.StreamResponse.write
    calls = {"n": 0}

    async def flaky_write(self, data):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionResetError("simulated client disconnect on first write")
        return await original_write(self, data)

    monkeypatch.setattr(web.StreamResponse, "write", flaky_write)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    try:
        await client.post("/api/chat/chat1/send", json={"text": "привет"})
    except Exception:
        pass  # обрыв записи на сервере может выглядеть с этой стороны по-разному — важен только advanced ниже

    # Дать шанс возможной утечённой фоновой задаче продвинуть генератор дальше.
    await asyncio.sleep(0.05)
    assert advanced == ["a"]


@pytest.mark.asyncio
async def test_send_message_no_heartbeat_noise_when_events_arrive_promptly(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_send_message(db_conn, http_session, config, chat_session_id, text):
        yield "assistant.delta", {"delta": "ok"}
        yield "done", {}

    monkeypatch.setattr("hermes_web.app.quickchat.send_message", fake_send_message)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/chat/chat1/send", json={"text": "привет"})
    body = (await resp.read()).decode("utf-8")
    assert ": ping" not in body


@pytest.mark.asyncio
async def test_login_rate_limited_after_five_failures(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    for _ in range(5):
        resp = await client.post("/login", json={"username": "dem", "password": "wrong"})
        assert resp.status == 401
    resp = await client.post("/login", json={"username": "dem", "password": "secret123"})
    assert resp.status == 429


@pytest.mark.asyncio
async def test_root_redirects_to_login_when_unauthenticated(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.get("/", allow_redirects=False)
    assert resp.status in (302, 303, 307)
    assert resp.headers["Location"] == "/login.html"


@pytest.mark.asyncio
async def test_root_redirects_to_home_when_authenticated(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.get("/", allow_redirects=False)
    assert resp.status in (302, 303, 307)
    assert resp.headers["Location"] == "/home.html"


@pytest.mark.asyncio
async def test_send_message_hermes_client_error_sends_error_and_done_events(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_send_message(db_conn, http_session, config, chat_session_id, text):
        # Реалистичный сбой: Hermes-шлюз лежит/перезапускается — это происходит
        # ПОСЛЕ того, как handle_send_message уже вызвал response.prepare()
        # и отдал 200 text/event-stream, поэтому единственный способ сообщить
        # об ошибке клиенту — SSE-событие "error", а не HTTP-статус.
        yield "assistant.delta", {"delta": "част"}
        raise hermes_client.HermesClientError("stream_chat failed: 503 Service Unavailable")

    monkeypatch.setattr("hermes_web.app.quickchat.send_message", fake_send_message)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/chat/chat1/send", json={"text": "привет"})
    assert resp.status == 200
    body = (await resp.read()).decode("utf-8")
    assert "event: assistant.delta" in body
    assert "event: error" in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_send_message_client_error_sends_error_and_done_events(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_send_message(db_conn, http_session, config, chat_session_id, text):
        raise aiohttp.ClientConnectionError("connection reset")
        yield  # pragma: no cover — делает функцию async-генератором

    monkeypatch.setattr("hermes_web.app.quickchat.send_message", fake_send_message)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/chat/chat1/send", json={"text": "привет"})
    assert resp.status == 200
    body = (await resp.read()).decode("utf-8")
    assert "event: error" in body
    assert "event: done" in body


@pytest.mark.asyncio
async def test_send_message_cross_user_returns_404(aiohttp_client, app_and_conn):
    conn = app_and_conn["db"]
    storage.create_chat_session(conn, "dem-chat", "dem", "/w/dem/ALL/x", "web_dem", created_at=1.0)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})
    resp = await client.post("/api/chat/dem-chat/send", json={"text": "привет"})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_get_messages_cross_user_returns_404(aiohttp_client, app_and_conn):
    conn = app_and_conn["db"]
    storage.create_chat_session(conn, "dem-chat", "dem", "/w/dem/ALL/x", "web_dem", created_at=1.0)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})
    resp = await client.get("/api/chat/dem-chat/messages")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_list_groups_requires_auth(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.get("/api/groups")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_list_groups_returns_groups_from_projects_module(aiohttp_client, app_and_conn, monkeypatch):
    def fake_list_groups(user, db_conn, config):
        assert user == "dem"
        return [{"slug": "ALL", "display_name": "ALL", "emoji": "", "pinned": False, "project_count": 0}]

    monkeypatch.setattr("hermes_web.app.projects.list_groups", fake_list_groups)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.get("/api/groups")
    assert resp.status == 200
    body = await resp.json()
    assert body == {"groups": [{"slug": "ALL", "display_name": "ALL", "emoji": "", "pinned": False, "project_count": 0}]}


@pytest.mark.asyncio
async def test_create_group_requires_name(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/groups", json={"name": "", "emoji": "🏠"})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_create_group_delegates_to_projects_module(aiohttp_client, app_and_conn, monkeypatch):
    def fake_create_group(user, name, emoji, db_conn, config):
        return {"slug": "dom-i-remont", "display_name": name, "emoji": emoji, "pinned": False, "project_count": 0}

    monkeypatch.setattr("hermes_web.app.projects.create_group", fake_create_group)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/groups", json={"name": "Дом и ремонт", "emoji": "🏠"})
    assert resp.status == 200
    body = await resp.json()
    assert body["slug"] == "dom-i-remont"


@pytest.mark.asyncio
async def test_update_group_unknown_slug_returns_404(aiohttp_client, app_and_conn, monkeypatch):
    def fake_update_group(user, slug, db_conn, config, display_name=None, emoji=None, pinned=None):
        raise projects.ProjectsError("неизвестная группа: nope")

    monkeypatch.setattr("hermes_web.app.projects.update_group", fake_update_group)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.put("/api/groups/nope", json={"display_name": "x"})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_list_projects_uses_default_filters_when_no_query_params(aiohttp_client, app_and_conn, monkeypatch):
    captured = {}

    def fake_list_projects(user, db_conn, config, group="*", since="month", status="active"):
        captured.update(user=user, group=group, since=since, status=status)
        return []

    monkeypatch.setattr("hermes_web.app.projects.list_projects", fake_list_projects)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.get("/api/projects")
    assert resp.status == 200
    assert captured == {"user": "dem", "group": "*", "since": "month", "status": "active"}


@pytest.mark.asyncio
async def test_list_projects_forwards_explicit_query_params(aiohttp_client, app_and_conn, monkeypatch):
    captured = {}

    def fake_list_projects(user, db_conn, config, group="*", since="month", status="active"):
        captured.update(group=group, since=since, status=status)
        return []

    monkeypatch.setattr("hermes_web.app.projects.list_projects", fake_list_projects)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    await client.get("/api/projects?group=ALL&since=year&status=all")
    assert captured == {"group": "ALL", "since": "year", "status": "all"}


@pytest.mark.asyncio
async def test_list_projects_unknown_since_returns_400(aiohttp_client, app_and_conn, monkeypatch):
    def fake_list_projects(user, db_conn, config, group="*", since="month", status="active"):
        raise projects.ProjectsError("неизвестный диапазон времени: decade")

    monkeypatch.setattr("hermes_web.app.projects.list_projects", fake_list_projects)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.get("/api/projects?since=decade")
    assert resp.status == 400


@pytest.mark.asyncio
async def test_project_detail_not_found_returns_404(aiohttp_client, app_and_conn, monkeypatch):
    def fake_get_project_detail(user, path, config):
        raise projects.project_index_core.ProjectIndexError("not found")

    monkeypatch.setattr("hermes_web.app.projects.get_project_detail", fake_get_project_detail)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.get("/api/projects/detail?path=dem/ALL/x")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_search_projects_returns_results(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_search_projects(user, query, config):
        assert query == "гараж"
        return {"results": [{"path": "/p"}], "message": ""}

    monkeypatch.setattr("hermes_web.app.projects.search_projects", fake_search_projects)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/search", json={"query": "гараж"})
    assert resp.status == 200
    body = await resp.json()
    assert body["results"] == [{"path": "/p"}]


@pytest.mark.asyncio
async def test_move_project_success(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_move_project(user, path, config, db_conn, new_group=None, new_name=None):
        assert new_group == "1С"
        return {"old_path": "/old", "new_path": "/new", "indexed": True, "session_restart_required": True}

    monkeypatch.setattr("hermes_web.app.projects.move_project", fake_move_project)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/move", json={"path": "dem/ALL/a", "new_group": "1С"})
    assert resp.status == 200
    body = await resp.json()
    assert body["new_path"] == "/new"


_ABOUT_MD = """---
tags: []
status: active
---

# Название проекта
Секрет Дмитрия

# Краткое описание
Не должно быть видно Ростиславу

# Опорные точки

# На чём остановились
"""


def _seed_project(tmp_path, rel_dir):
    """Кладёт реальный проект на диск в workspace фикстуры app_and_conn
    (тот же tmp_path — pytest отдаёт один и тот же каталог фикстуре и тесту)."""
    project_dir = tmp_path / "workspace" / rel_dir
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(_ABOUT_MD, encoding="utf-8")
    return project_dir


@pytest.mark.asyncio
async def test_project_detail_cross_user_returns_404_and_leaks_nothing(aiohttp_client, app_and_conn, tmp_path):
    """Ростислав не должен вытащить проект Дмитрия по прямому пути.
    Пиним гарантию на границе HTTP-маршрута — до этого её не проверял никто."""
    _seed_project(tmp_path, "dem/ALL/x")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})
    resp = await client.get("/api/projects/detail?path=dem/ALL/x")

    assert resp.status == 404
    body = await resp.text()
    assert "Секрет Дмитрия" not in body
    assert "Не должно быть видно" not in body


@pytest.mark.asyncio
async def test_project_detail_traversal_path_returns_404(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/x")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})
    resp = await client.get("/api/projects/detail?path=rost/../dem/ALL/x")

    assert resp.status == 404
    assert "Секрет Дмитрия" not in await resp.text()


@pytest.mark.asyncio
async def test_move_project_traversal_new_group_returns_400(aiohttp_client, app_and_conn, tmp_path):
    """POST /api/projects/move с new_group='../rost' обязан вернуть 400
    и не тронуть проект — сквозная проверка маршрута поверх фикса в плагине."""
    _seed_project(tmp_path, "dem/ALL/a")
    (tmp_path / "workspace" / "rost").mkdir()

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/move", json={"path": "dem/ALL/a", "new_group": "../rost"})

    assert resp.status == 400
    assert (tmp_path / "workspace" / "dem" / "ALL" / "a").is_dir()
    assert list((tmp_path / "workspace" / "rost").iterdir()) == []


@pytest.mark.asyncio
async def test_move_project_cross_user_source_path_returns_400(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/a")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})
    resp = await client.post("/api/projects/move", json={"path": "dem/ALL/a", "new_group": "ALL"})

    assert resp.status == 400
    assert (tmp_path / "workspace" / "dem" / "ALL" / "a").is_dir()


@pytest.mark.asyncio
async def test_move_project_collision_returns_400(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_move_project(user, path, config, db_conn, new_group=None, new_name=None):
        raise projects.project_index_core.ProjectIndexError("в группе уже есть проект с таким именем")

    monkeypatch.setattr("hermes_web.app.projects.move_project", fake_move_project)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/move", json={"path": "dem/ALL/a", "new_group": "1С"})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_open_project_creates_session_when_authed(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_get_or_open_session(db_conn, http_session, config, user, project_path):
        assert user == "dem"
        assert project_path == "dem/ALL/a"
        return {"chat_session_id": "chat1", "project_path": "/w/dem/ALL/a", "hermes_session_id": "web_1"}

    monkeypatch.setattr("hermes_web.app.quickchat.get_or_open_session", fake_get_or_open_session)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/open", json={"path": "dem/ALL/a"})
    assert resp.status == 200
    body = await resp.json()
    assert body == {"chat_session_id": "chat1", "project_path": "/w/dem/ALL/a"}


@pytest.mark.asyncio
async def test_open_project_unknown_returns_404(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_get_or_open_session(db_conn, http_session, config, user, project_path):
        raise projects.project_index_core.ProjectIndexError("about.md не найден")

    monkeypatch.setattr("hermes_web.app.quickchat.get_or_open_session", fake_get_or_open_session)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/open", json={"path": "dem/ALL/nope"})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_open_project_requires_auth(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.post("/api/projects/open", json={"path": "dem/ALL/a"})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_project_tree_returns_tree(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.get("/api/projects/tree?path=dem/ALL/a")
    assert resp.status == 200
    body = await resp.json()
    assert body["root_files"][0]["name"] == "about.md"
    assert body["source"] == []


@pytest.mark.asyncio
async def test_project_tree_cross_user_returns_404(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})
    resp = await client.get("/api/projects/tree?path=dem/ALL/a")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_project_file_get_returns_content(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("привет", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.get("/api/projects/file?path=dem/ALL/a&file=source/note.txt")
    assert resp.status == 200
    assert (await resp.text()) == "привет"


@pytest.mark.asyncio
async def test_project_file_get_download_sets_content_disposition(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "result").mkdir()
    (project_dir / "result" / "out.pdf").write_bytes(b"pdf-bytes")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.get("/api/projects/file?path=dem/ALL/a&file=result/out.pdf&download=1")
    assert resp.status == 200
    assert "attachment" in resp.headers["Content-Disposition"]
    assert (await resp.read()) == b"pdf-bytes"


@pytest.mark.asyncio
async def test_project_file_get_download_quotes_and_encodes_filename(aiohttp_client, app_and_conn, tmp_path):
    """Finding 3 (важное, финальное ревью): раньше Content-Disposition
    собирался f-строкой 'attachment; filename="{name}"' — кавычка в имени
    файла ломала заголовок (можно было подмешать произвольные параметры), а
    сырая кириллица в заголовке технически некорректна по RFC 6266 и в
    части браузеров превращалась в кракозябры. Кладём файл с кириллическим
    именем (реальный кейс проекта — "Иванов" и т.п.) прямо на диск (upload
    сам добавил бы дату/basename — здесь важно только имя, которое отдаёт
    сервер) и проверяем, что заголовок остаётся валидным одним значением и
    несёт RFC 5987 filename*=UTF-8''..."""
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "Иванов.txt").write_text("текст", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.get("/api/projects/file?path=dem/ALL/a&file=source/Иванов.txt&download=1")
    assert resp.status == 200
    disposition = resp.headers["Content-Disposition"]
    assert "attachment" in disposition
    assert "filename*=UTF-8''" in disposition


@pytest.mark.asyncio
async def test_project_upload_accepts_payload_over_default_1mib_limit(aiohttp_client, app_and_conn, tmp_path):
    """Finding 2 (важное, финальное ревью): aiohttp по умолчанию режет тело
    запроса на 1 MiB — реальный кейс проекта (сканы книг, PDF, скриншоты)
    регулярно больше. create_app теперь передаёт client_max_size=64 MiB."""
    _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})

    big_content = b"x" * (2 * 1024 * 1024)  # 2 MiB — больше дефолтного лимита aiohttp
    form = aiohttp.FormData()
    form.add_field("path", "dem/ALL/a")
    form.add_field("target_dir", "source")
    form.add_field("file", big_content, filename="big-scan.jpg", content_type="image/jpeg")
    resp = await client.post("/api/projects/upload", data=form)
    assert resp.status == 200


@pytest.mark.asyncio
async def test_project_file_get_cross_user_returns_404(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})
    resp = await client.get("/api/projects/file?path=dem/ALL/a&file=about.md")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_project_file_get_traversal_returns_404(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.get("/api/projects/file?path=dem/ALL/a&file=../../../etc/passwd")
    assert resp.status == 404


@pytest.mark.asyncio
async def test_project_file_post_cross_user_returns_404(aiohttp_client, app_and_conn, tmp_path):
    """Finding 7 (важное, финальное ревью): GET-эндпоинты уже пинили
    межпользовательскую изоляцию тестами, POST-эндпоинты — нет. Ростислав
    не должен мочь дописать в about.md проекта Дмитрия."""
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    original = (project_dir / "about.md").read_text(encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})
    resp = await client.post("/api/projects/file", json={"path": "dem/ALL/a", "file": "about.md", "content": "pwned"})

    assert resp.status == 404
    assert (project_dir / "about.md").read_text(encoding="utf-8") == original


@pytest.mark.asyncio
async def test_project_mkdir_cross_user_returns_404(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})
    resp = await client.post("/api/projects/mkdir", json={"path": "dem/ALL/a", "parent": "source", "name": "pwned"})

    assert resp.status == 404
    assert not (project_dir / "source").exists()


@pytest.mark.asyncio
async def test_project_upload_cross_user_returns_404(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})

    form = aiohttp.FormData()
    form.add_field("path", "dem/ALL/a")
    form.add_field("target_dir", "source")
    form.add_field("file", b"pwned-bytes", filename="pwn.jpg", content_type="image/jpeg")
    resp = await client.post("/api/projects/upload", data=form)

    assert resp.status == 404
    assert not (project_dir / "source").exists()


@pytest.mark.asyncio
async def test_project_file_post_saves_content(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/file", json={"path": "dem/ALL/a", "file": "source/note.txt", "content": "текст"})
    assert resp.status == 200
    assert (project_dir / "source" / "note.txt").read_text(encoding="utf-8") == "текст"


@pytest.mark.asyncio
async def test_project_file_post_bad_extension_returns_400(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/file", json={"path": "dem/ALL/a", "file": "source/data.bin", "content": "x"})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_project_mkdir_creates_folder(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/mkdir", json={"path": "dem/ALL/a", "parent": "source", "name": "Иванов"})
    assert resp.status == 200
    assert (project_dir / "source" / "Иванов").is_dir()


@pytest.mark.asyncio
async def test_project_mkdir_collision_returns_409(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    await client.post("/api/projects/mkdir", json={"path": "dem/ALL/a", "parent": "source", "name": "Иванов"})
    resp = await client.post("/api/projects/mkdir", json={"path": "dem/ALL/a", "parent": "source", "name": "Иванов"})
    assert resp.status == 409


@pytest.mark.asyncio
async def test_project_mkdir_outside_buckets_returns_400(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/mkdir", json={"path": "dem/ALL/a", "parent": ".", "name": "x"})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_project_move_entry_moves_file(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/move-entry", json={
        "path": "dem/ALL/a", "source": "source/note.txt", "dest_dir": "result", "new_name": None,
    })
    assert resp.status == 200
    body = await resp.json()
    assert body["relative_path"] == "result/note.txt"
    assert (project_dir / "result" / "note.txt").exists()


@pytest.mark.asyncio
async def test_project_move_entry_renames(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/move-entry", json={
        "path": "dem/ALL/a", "source": "source/note.txt", "dest_dir": "source", "new_name": "renamed.txt",
    })
    assert resp.status == 200
    assert (project_dir / "source" / "renamed.txt").exists()


@pytest.mark.asyncio
async def test_project_move_entry_collision_returns_409(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("1", encoding="utf-8")
    (project_dir / "result").mkdir()
    (project_dir / "result" / "note.txt").write_text("2", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/move-entry", json={
        "path": "dem/ALL/a", "source": "source/note.txt", "dest_dir": "result", "new_name": None,
    })
    assert resp.status == 409


@pytest.mark.asyncio
async def test_project_move_entry_missing_source_returns_400(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/move-entry", json={
        "path": "dem/ALL/a", "source": "source/nope.txt", "dest_dir": "result", "new_name": None,
    })
    assert resp.status == 400


@pytest.mark.asyncio
async def test_project_move_entry_cross_user_returns_404(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})
    resp = await client.post("/api/projects/move-entry", json={
        "path": "dem/ALL/a", "source": "source/note.txt", "dest_dir": "result", "new_name": None,
    })
    assert resp.status == 404
    assert (project_dir / "source" / "note.txt").exists()


@pytest.mark.asyncio
async def test_project_move_entry_requires_auth(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.post("/api/projects/move-entry", json={
        "path": "dem/ALL/a", "source": "source/note.txt", "dest_dir": "result", "new_name": None,
    })
    assert resp.status == 401


@pytest.mark.asyncio
async def test_project_upload_saves_file_with_date_prefix(aiohttp_client, app_and_conn, tmp_path):
    import datetime as _dt
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})

    form = aiohttp.FormData()
    form.add_field("path", "dem/ALL/a")
    form.add_field("target_dir", "source")
    form.add_field("file", b"jpeg-bytes", filename="scan.jpg", content_type="image/jpeg")
    resp = await client.post("/api/projects/upload", data=form)
    assert resp.status == 200
    body = await resp.json()
    today = _dt.date.today().isoformat()
    assert body["relative_path"] == f"source/{today}_scan.jpg"
    assert (project_dir / "source" / f"{today}_scan.jpg").read_bytes() == b"jpeg-bytes"


@pytest.mark.asyncio
async def test_project_upload_collision_returns_409(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})

    async def upload():
        form = aiohttp.FormData()
        form.add_field("path", "dem/ALL/a")
        form.add_field("target_dir", "source")
        form.add_field("file", b"x", filename="2026-01-01_dup.jpg")
        return await client.post("/api/projects/upload", data=form)

    assert (await upload()).status == 200
    assert (await upload()).status == 409
