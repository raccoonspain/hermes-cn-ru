"""aiohttp web application: login/logout, /api/me, quick-chat, chat send/history,
плюс раздача статики. Неавторизованные HTML-страницы (login.html/home.html/
chat.html) отдаются как обычные статические файлы — секретов в них нет,
авторизация проверяется на уровне API (/api/me и т.д.), а фронтенд сам
редиректит на /login.html при 401 (см. static-JS в Task 7)."""
from __future__ import annotations

import asyncio
import json
import time

import aiohttp
from aiohttp import web

from . import auth, hermes_client, quickchat, storage

COOKIE_NAME = "hermes_web_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 дней
RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 300


def _require_user(request: web.Request) -> dict:
    user = request.get("user")
    if user is None:
        raise web.HTTPUnauthorized(text=json.dumps({"error": "not authenticated"}), content_type="application/json")
    return user


@web.middleware
async def auth_middleware(request: web.Request, handler):
    token = request.cookies.get(COOKIE_NAME)
    request["user"] = None
    if token:
        row = storage.get_web_session(request.app["db"], token, now=time.time())
        if row is not None:
            user_row = storage.get_user(request.app["db"], row["username"])
            if user_row is not None:
                request["user"] = {
                    "username": user_row["username"],
                    "role": user_row["role"],
                    "display_name": user_row["display_name"],
                }
    return await handler(request)


async def handle_login(request: web.Request) -> web.Response:
    body = await request.json()
    username = str(body.get("username", ""))
    password = str(body.get("password", ""))

    client_ip = request.remote or "unknown"
    rate_key = f"{client_ip}:{username}"
    if not request.app["rate_limiter"].allow(rate_key, now=time.time()):
        return web.json_response({"error": "too many attempts, try again later"}, status=429)

    user_row = storage.get_user(request.app["db"], username)
    if user_row is None or not auth.verify_password(password, user_row["password_hash"]):
        return web.json_response({"error": "неверный логин или пароль"}, status=401)

    token = auth.generate_session_token()
    storage.create_web_session(request.app["db"], token, username, expires_at=time.time() + SESSION_TTL_SECONDS)

    response = web.json_response({
        "username": user_row["username"],
        "role": user_row["role"],
        "display_name": user_row["display_name"],
    })
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_TTL_SECONDS, httponly=True,
        secure=request.app["cookie_secure"], samesite="Strict",
    )
    return response


async def handle_logout(request: web.Request) -> web.Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        storage.delete_web_session(request.app["db"], token)
    response = web.json_response({"ok": True})
    response.del_cookie(COOKIE_NAME)
    return response


async def handle_me(request: web.Request) -> web.Response:
    user = _require_user(request)
    return web.json_response(user)


async def handle_root(request: web.Request) -> web.Response:
    target = "/home.html" if request.get("user") is not None else "/login.html"
    raise web.HTTPFound(target)


async def handle_quick_chat(request: web.Request) -> web.Response:
    user = _require_user(request)
    result = await quickchat.create_quick_chat(
        request.app["db"], request.app["http_session"], request.app["quickchat_config"], user["username"],
    )
    return web.json_response({
        "chat_session_id": result["chat_session_id"],
        "project_path": result["project_path"],
    })


async def handle_send_message(request: web.Request) -> web.StreamResponse:
    user = _require_user(request)
    chat_session_id = request.match_info["chat_session_id"]
    body = await request.json()
    text = str(body.get("text", ""))
    if not text:
        return web.json_response({"error": "text is required"}, status=400)

    # Только блокируем доступ к чужой существующей сессии. Если сессии с
    # таким id вообще нет — это обрабатывает quickchat.send_message ниже
    # (кидает QuickChatError, который ловится в try/except и уходит SSE-
    # событием "error" — единая точка проверки существования сессии).
    row = storage.get_chat_session(request.app["db"], chat_session_id)
    if row is not None and row["user"] != user["username"]:
        return web.json_response({"error": "not found"}, status=404)

    response = web.StreamResponse(
        status=200,
        headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    await response.prepare(request)
    try:
        async for name, payload in quickchat.send_message(
            request.app["db"], request.app["http_session"], request.app["quickchat_config"], chat_session_id, text,
        ):
            data = json.dumps(payload, ensure_ascii=False)
            await response.write(f"event: {name}\ndata: {data}\n\n".encode("utf-8"))
    except (quickchat.QuickChatError, hermes_client.HermesClientError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
        # response.prepare() выше уже отправил 200 text/event-stream — на этом
        # этапе упасть с необработанным исключением нельзя: клиент останется
        # висеть на незакрытом потоке, а в логе будет трейсбек вместо понятной
        # ошибки. Поэтому любой реалистичный сбой похода в Hermes (шлюз лежит/
        # перезапускается, таймаут, обрыв соединения) конвертируем в тот же
        # "event: error", что и QuickChatError, и следом шлём "done" — тем же
        # {}, что и в успешном потоке (см. hermes_client.stream_chat), чтобы
        # клиент закрыл EventSource по тому же признаку конца потока.
        data = json.dumps({"message": str(exc)}, ensure_ascii=False)
        await response.write(f"event: error\ndata: {data}\n\n".encode("utf-8"))
        await response.write(b"event: done\ndata: {}\n\n")
    return response


async def handle_get_messages(request: web.Request) -> web.Response:
    user = _require_user(request)
    chat_session_id = request.match_info["chat_session_id"]
    row = storage.get_chat_session(request.app["db"], chat_session_id)
    if row is None or row["user"] != user["username"]:
        return web.json_response({"error": "not found"}, status=404)
    messages = await quickchat.get_history(
        request.app["db"], request.app["http_session"], request.app["quickchat_config"], chat_session_id,
    )
    return web.json_response({"data": messages})


async def _on_startup(app: web.Application) -> None:
    # aiohttp.ClientSession() requires a running event loop (aiohttp >= 4-style
    # behaviour, already true in 3.14) — create_app() itself is a plain sync
    # function that may run before any loop exists, so the session is built
    # here in on_startup, which aiohttp always runs inside the app's loop.
    #
    # Explicit timeout: aiohttp's default ClientTimeout(total=300, ...) caps
    # the *entire* request/response duration, including a streamed response —
    # a tool-using Hermes agent turn can legitimately run longer than 5
    # minutes, and the default would kill the stream mid-flight. total=None
    # disables that whole-response cap; sock_read still guards against a
    # truly stalled connection (no bytes at all for 5 minutes), and
    # sock_connect keeps a dead/unreachable Hermes gateway from hanging a
    # request at the TCP-connect stage.
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=300)
    app["http_session"] = aiohttp.ClientSession(timeout=timeout)


async def _on_cleanup(app: web.Application) -> None:
    await app["http_session"].close()


def create_app(*, db_path: str, quickchat_config: quickchat.Config, cookie_secure: bool = True, static_dir: str) -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app["db"] = storage.get_connection(db_path)
    app["quickchat_config"] = quickchat_config
    app["cookie_secure"] = cookie_secure
    app["rate_limiter"] = auth.RateLimiter(RATE_LIMIT_MAX_ATTEMPTS, RATE_LIMIT_WINDOW_SECONDS)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)

    app.router.add_post("/login", handle_login)
    app.router.add_post("/logout", handle_logout)
    app.router.add_get("/api/me", handle_me)
    app.router.add_post("/api/quick-chat", handle_quick_chat)
    app.router.add_post("/api/chat/{chat_session_id}/send", handle_send_message)
    app.router.add_get("/api/chat/{chat_session_id}/messages", handle_get_messages)
    app.router.add_get("/", handle_root)
    app.router.add_static("/", static_dir, show_index=False)
    return app
