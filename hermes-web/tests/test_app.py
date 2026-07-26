import json

import aiohttp
import pytest

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


@pytest.mark.asyncio
async def test_move_project_collision_returns_400(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_move_project(user, path, config, db_conn, new_group=None, new_name=None):
        raise projects.project_index_core.ProjectIndexError("в группе уже есть проект с таким именем")

    monkeypatch.setattr("hermes_web.app.projects.move_project", fake_move_project)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/move", json={"path": "dem/ALL/a", "new_group": "1С"})
    assert resp.status == 400
