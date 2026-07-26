import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from hermes_web import hermes_client


def _make_fake_hermes_app(*, sessions_created: list, chat_calls: list):
    app = web.Application()

    async def create_session(request):
        body = await request.json()
        sessions_created.append(body)
        assert request.headers.get("Authorization") == "Bearer fake-key"
        return web.json_response(
            {"object": "hermes.session", "session": {"id": body["id"]}}, status=201
        )

    async def chat_stream(request):
        body = await request.json()
        chat_calls.append(body)
        response = web.StreamResponse(
            status=200, headers={"Content-Type": "text/event-stream"}
        )
        await response.prepare(request)
        await response.write(b": keepalive\n\n")
        await response.write(
            f"event: assistant.delta\ndata: {json.dumps({'delta': 'Привет'})}\n\n".encode()
        )
        await response.write(
            f"event: assistant.delta\ndata: {json.dumps({'delta': ', мир'})}\n\n".encode()
        )
        await response.write(
            f"event: assistant.completed\ndata: {json.dumps({'content': 'Привет, мир'})}\n\n".encode()
        )
        await response.write(f"event: done\ndata: {json.dumps({})}\n\n".encode())
        return response

    async def messages(request):
        return web.json_response(
            {
                "object": "list",
                "session_id": request.match_info["session_id"],
                "data": [
                    {"role": "user", "content": "привет"},
                    {"role": "assistant", "content": "Привет, мир"},
                ],
            }
        )

    app.router.add_post("/api/sessions", create_session)
    app.router.add_post("/api/sessions/{session_id}/chat/stream", chat_stream)
    app.router.add_get("/api/sessions/{session_id}/messages", messages)
    return app


@pytest.mark.asyncio
async def test_create_session_sends_id_and_auth_header(aiohttp_client):
    sessions_created = []
    server = TestServer(_make_fake_hermes_app(sessions_created=sessions_created, chat_calls=[]))
    client = await aiohttp_client(server)
    base_url = str(server.make_url(""))

    result = await hermes_client.create_session(client.session, base_url, "fake-key", "web_abc")
    assert result["session"]["id"] == "web_abc"
    assert sessions_created == [{"id": "web_abc"}]


@pytest.mark.asyncio
async def test_stream_chat_yields_parsed_events(aiohttp_client):
    chat_calls = []
    server = TestServer(_make_fake_hermes_app(sessions_created=[], chat_calls=chat_calls))
    client = await aiohttp_client(server)
    base_url = str(server.make_url(""))

    events = []
    async for name, payload in hermes_client.stream_chat(
        client.session, base_url, "fake-key", "web_abc", "привет", system_message="контекст проекта"
    ):
        events.append((name, payload))

    assert events == [
        ("assistant.delta", {"delta": "Привет"}),
        ("assistant.delta", {"delta": ", мир"}),
        ("assistant.completed", {"content": "Привет, мир"}),
        ("done", {}),
    ]
    assert chat_calls == [{"message": "привет", "system_message": "контекст проекта"}]


@pytest.mark.asyncio
async def test_get_messages_returns_data_list(aiohttp_client):
    server = TestServer(_make_fake_hermes_app(sessions_created=[], chat_calls=[]))
    client = await aiohttp_client(server)
    base_url = str(server.make_url(""))

    messages = await hermes_client.get_messages(client.session, base_url, "fake-key", "web_abc")
    assert messages == [
        {"role": "user", "content": "привет"},
        {"role": "assistant", "content": "Привет, мир"},
    ]


@pytest.mark.asyncio
async def test_create_session_error_status_raises(aiohttp_client):
    async def failing(request):
        return web.json_response({"error": {"message": "boom"}}, status=500)

    app = web.Application()
    app.router.add_post("/api/sessions", failing)
    client = await aiohttp_client(app)
    base_url = str(client.make_url(""))

    with pytest.raises(hermes_client.HermesClientError):
        await hermes_client.create_session(client.session, base_url, "fake-key", "web_abc")
