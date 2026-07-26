import json

import aiohttp
import pytest

from hermes_web import auth, hermes_client, quickchat, storage
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
