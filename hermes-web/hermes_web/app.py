"""aiohttp web application: login/logout, /api/me, quick-chat, chat send/history,
плюс раздача статики. Неавторизованные HTML-страницы (login.html/home.html/
project-selector.html/project-workspace.html) отдаются как обычные статические файлы — секретов
в них нет, авторизация проверяется на уровне API (/api/me и т.д.), а
фронтенд сам редиректит на /login.html при 401 (см. static-JS в Task 7)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.parse

import aiohttp
from aiohttp import web

from . import admin_metrics, auth, hermes_client, projects, quickchat, storage, workspace

logger = logging.getLogger(__name__)

COOKIE_NAME = "hermes_web_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 дней
RATE_LIMIT_MAX_ATTEMPTS = 5
RATE_LIMIT_WINDOW_SECONDS = 300
# SSE-заглушка (": ping\n\n" — RFC-комментарий, клиент его игнорирует, см.
# app.js readSSE) во время тихих пауз агента (докер, ожидание wormsoft.ru) —
# без неё простаивающее соединение рвёт прокси/браузер раньше, чем агент
# реально закончит (инцидент 2026-07-28: ответ пришёл, клиент уже отвалился).
HEARTBEAT_INTERVAL = 15.0


def _require_user(request: web.Request) -> dict:
    user = request.get("user")
    if user is None:
        raise web.HTTPUnauthorized(text=json.dumps({"error": "not authenticated"}), content_type="application/json")
    return user


USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")


def _require_owner(request: web.Request) -> dict:
    user = _require_user(request)
    if user["role"] != "owner":
        raise web.HTTPForbidden(text=json.dumps({"error": "forbidden"}), content_type="application/json")
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
    storage.log_event(request.app["db"], user_row["username"], "login", "")

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

    result_target = body.get("result_target")

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
        send_kwargs = {"result_target": result_target} if result_target is not None else {}
        agen = quickchat.send_message(
            request.app["db"], request.app["http_session"], request.app["quickchat_config"], chat_session_id, text,
            **send_kwargs,
        ).__aiter__()
        # asyncio.wait(timeout=...) над одной и той же pending-задачей, а не
        # asyncio.wait_for — таймаут не должен отменять agen.__anext__(): async
        # generator плохо переживает CancelledError в момент, когда сам ждёт
        # сетевого ответа от Hermes API, и это оборвало бы реальный запрос
        # ради заглушки. При таймауте просто шлём ping и ждём ту же задачу снова.
        pending = asyncio.ensure_future(agen.__anext__())
        try:
            while True:
                done, _ = await asyncio.wait({pending}, timeout=HEARTBEAT_INTERVAL)
                if not done:
                    await response.write(b": ping\n\n")
                    continue
                try:
                    name, payload = pending.result()
                except StopAsyncIteration:
                    break
                data = json.dumps(payload, ensure_ascii=False)
                await response.write(f"event: {name}\ndata: {data}\n\n".encode("utf-8"))
                # Следующий __anext__() планируем ТОЛЬКО после успешной записи
                # текущего payload. Если планировать его раньше и запись упадёт
                # (клиент уже отвалился), уже стартовавшая фоновая задача всё
                # равно доведёт генератор (и реальный запрос к Hermes внутри
                # него) до следующего yield — никем не дожидаемая утечка.
                pending = asyncio.ensure_future(agen.__anext__())
        finally:
            if not pending.done():
                pending.cancel()
                try:
                    await pending
                except BaseException:
                    pass
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


async def handle_list_groups(request: web.Request) -> web.Response:
    user = _require_user(request)
    groups = projects.list_groups(user["username"], request.app["db"], request.app["quickchat_config"])
    return web.json_response({"groups": groups})


async def handle_create_group(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    name = str(body.get("name", "")).strip()
    emoji = str(body.get("emoji", ""))
    if not name:
        return web.json_response({"error": "name is required"}, status=400)
    result = projects.create_group(user["username"], name, emoji, request.app["db"], request.app["quickchat_config"])
    return web.json_response(result)


async def handle_update_group(request: web.Request) -> web.Response:
    user = _require_user(request)
    slug = request.match_info["slug"]
    body = await request.json()
    try:
        result = projects.update_group(
            user["username"], slug, request.app["db"], request.app["quickchat_config"],
            display_name=body.get("display_name"), emoji=body.get("emoji"), pinned=body.get("pinned"),
        )
    except projects.ProjectsError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    return web.json_response(result)


async def handle_create_project(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    group = str(body.get("group", "ALL"))
    title = str(body.get("title", ""))
    try:
        result = await quickchat.create_project(request.app["db"], request.app["quickchat_config"], user["username"], group, title)
    except quickchat.QuickChatError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    storage.log_event(request.app["db"], user["username"], "project.create", result["project_path"])
    return web.json_response(result)


async def handle_list_projects(request: web.Request) -> web.Response:
    user = _require_user(request)
    group = request.query.get("group", "*")
    since = request.query.get("since", "month")
    status = request.query.get("status", "active")
    try:
        result = projects.list_projects(
            user["username"], request.app["db"], request.app["quickchat_config"],
            group=group, since=since, status=status,
        )
    except projects.ProjectsError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"projects": result})


async def handle_project_detail(request: web.Request) -> web.Response:
    user = _require_user(request)
    path = request.query.get("path", "")
    try:
        detail = projects.get_project_detail(user["username"], path, request.app["quickchat_config"])
    except projects.project_index_core.ProjectIndexError:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(detail)


async def handle_search_projects(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    query = str(body.get("query", ""))
    try:
        result = await projects.search_projects(user["username"], query, request.app["quickchat_config"])
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)


async def handle_move_project(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    path = str(body.get("path", ""))
    new_group = body.get("new_group")
    new_name = body.get("new_name")
    try:
        result = await projects.move_project(
            user["username"], path, request.app["quickchat_config"], request.app["db"],
            new_group=new_group, new_name=new_name,
        )
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)


async def handle_delete_project(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    path = str(body.get("path", ""))
    try:
        result = await projects.delete_project(user["username"], path, request.app["quickchat_config"], request.app["db"])
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    storage.log_event(request.app["db"], user["username"], "project.delete", result["old_path"])
    return web.json_response(result)


async def handle_update_project_metadata(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    path = str(body.get("path", ""))
    tags = body.get("tags")
    status = body.get("status")
    if tags is not None and (not isinstance(tags, list) or not all(isinstance(t, str) for t in tags)):
        return web.json_response({"error": "tags должен быть списком строк"}, status=400)
    if status is not None and status not in ("active", "archived"):
        return web.json_response({"error": "status должен быть 'active' или 'archived'"}, status=400)
    try:
        result = await projects.update_project_metadata(user["username"], path, request.app["quickchat_config"], tags=tags, status=status)
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)


async def handle_open_project(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    path = str(body.get("path", ""))
    try:
        result = await quickchat.get_or_open_session(
            request.app["db"], request.app["http_session"], request.app["quickchat_config"], user["username"], path,
        )
    except quickchat.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    return web.json_response({"chat_session_id": result["chat_session_id"], "project_path": result["project_path"]})


async def handle_project_tree(request: web.Request) -> web.Response:
    user = _require_user(request)
    path = request.query.get("path", "")
    try:
        tree = workspace.list_tree(user["username"], path, request.app["quickchat_config"])
    except (projects.project_index_core.ProjectIndexError, workspace.WorkspaceError):
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response(tree)


async def handle_project_file_get(request: web.Request) -> web.Response:
    user = _require_user(request)
    path = request.query.get("path", "")
    file_param = request.query.get("file", "")
    download = request.query.get("download") == "1"
    try:
        _, candidate = workspace.resolve_file_path(user["username"], path, file_param, request.app["quickchat_config"])
        if not os.path.isfile(candidate):
            raise workspace.WorkspaceError(f"файл не найден: {file_param}")
    except (projects.project_index_core.ProjectIndexError, workspace.WorkspaceError):
        return web.json_response({"error": "not found"}, status=404)

    name = os.path.basename(candidate)
    headers: dict[str, str] = {}
    if download:
        # aiohttp.helpers.content_disposition_header вместо ручного f-string:
        # правильно квотирует " (иначе имя файла с кавычкой ломает заголовок
        # и позволяет подмешать произвольные параметры) и percent-encodes
        # \r\n (голый f-string с CR/LF в имени файла роняет aiohttp
        # необработанным ValueError и рвёт соединение). Для 'filename' этот
        # хелпер по историческим причинам (см. RFC 7578, multipart/form-data)
        # всегда отдаёт percent-encoded ASCII внутри filename="...", а не
        # RFC 5987 filename* — но именно filename* браузеры реально
        # декодируют обратно в UTF-8; голый filename="%D0%98..." они не
        # раскодируют и сохранят файл с процентами в имени. Поэтому кириллицу
        # (реальный кейс проекта — "Иванов" и т.п.) выражаем ещё и через
        # filename* по RFC 6266 §5: 'filename' остаётся ASCII-safe фолбэком
        # для старых клиентов, 'filename*' берёт приоритет в современных.
        disposition = aiohttp.helpers.content_disposition_header("attachment", filename=name)
        if not name.isascii():
            disposition += f"; filename*=UTF-8''{urllib.parse.quote(name, safe='')}"
        headers["Content-Disposition"] = disposition
    elif os.path.splitext(name)[1].lower() in (".md", ".txt"):
        headers["Content-Type"] = "text/plain; charset=utf-8"

    # web.FileResponse стримит файл через sendfile вместо синхронного
    # open().read() всего содержимого в память — важно, потому что файлы в
    # result/outer пишет сам агент и их размер ничем не ограничен (в отличие
    # от upload, теперь капнутого на UPLOAD_MAX_SIZE); синхронное чтение
    # большого файла блокирует единственный event loop aiohttp сразу для
    # всех пользователей, не только для этого запроса.
    return web.FileResponse(candidate, headers=headers)


async def handle_project_file_post(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    path = str(body.get("path", ""))
    file_param = str(body.get("file", ""))
    content = str(body.get("content", ""))
    try:
        result = await workspace.save_file(user["username"], path, file_param, content, request.app["quickchat_config"])
    except workspace.WorkspaceError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    return web.json_response(result)


async def handle_project_mkdir(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    path = str(body.get("path", ""))
    parent = str(body.get("parent", ""))
    name = str(body.get("name", ""))
    try:
        result = workspace.make_dir(user["username"], path, parent, name, request.app["quickchat_config"])
    except workspace.WorkspaceCollisionError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    except workspace.WorkspaceError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    return web.json_response(result)


async def handle_project_move_entry(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    path = str(body.get("path", ""))
    source = str(body.get("source", ""))
    dest_dir = str(body.get("dest_dir", ""))
    new_name = body.get("new_name")
    new_name = str(new_name) if new_name is not None else None
    try:
        result = workspace.move_entry(
            user["username"], path, source, dest_dir, new_name, request.app["quickchat_config"],
        )
    except workspace.WorkspaceCollisionError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    except workspace.WorkspaceError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    return web.json_response(result)


async def handle_project_delete_entry(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    path = str(body.get("path", ""))
    relative_path = str(body.get("relative_path", ""))
    try:
        result = workspace.delete_entry(user["username"], path, relative_path, request.app["quickchat_config"])
    except workspace.WorkspaceError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    return web.json_response(result)


async def handle_project_upload(request: web.Request) -> web.Response:
    user = _require_user(request)
    reader = await request.multipart()
    path = None
    target_dir = None
    filename = None
    content = b""
    async for field in reader:
        if field.name == "path":
            path = (await field.read()).decode("utf-8")
        elif field.name == "target_dir":
            target_dir = (await field.read()).decode("utf-8")
        elif field.name == "file":
            filename = field.filename
            content = await field.read()

    if not path or not target_dir or not filename:
        return web.json_response({"error": "path, target_dir и file обязательны"}, status=400)

    try:
        result = workspace.save_upload(user["username"], path, target_dir, filename, content, request.app["quickchat_config"])
    except workspace.WorkspaceCollisionError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    except workspace.WorkspaceError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    return web.json_response(result)


async def handle_admin_overview(request: web.Request) -> web.Response:
    _require_owner(request)
    config = request.app["quickchat_config"]
    workspace_root = config.workspace_root or projects.project_index_core.WORKSPACE_ROOT
    # На свежем деплое workspace_root ещё может не существовать на диске —
    # каталог создаётся лениво при первом создании группы/проекта
    # (см. projects.create_group). shutil.disk_usage (внутри
    # admin_metrics.disk_usage) требует существующий путь, а овнер может
    # открыть админ-панель раньше, чем кто-либо создаст первый проект.
    #
    # Каждая метрика собирается независимо и в своём try/except: это
    # единственный экран для диагностики здоровья сервера, поэтому один
    # упавший источник (нечитаемый /proc, недоступный для записи путь,
    # неожиданный формат /proc/meminfo) не должен превращать весь ответ
    # в 500 с телом-не-JSON и молча вешать фронтенд на "…" навсегда —
    # см. финальное ревью под-проекта C, Important #1.
    errors: dict = {}

    try:
        os.makedirs(workspace_root, exist_ok=True)
    except OSError:
        logger.warning("не удалось создать workspace_root %s", workspace_root, exc_info=True)
        errors["disk"] = "workspace_root недоступен"

    cpu = None
    try:
        cpu = await admin_metrics.cpu_percent()
    except Exception:
        logger.warning("не удалось собрать метрику CPU", exc_info=True)
        errors["cpu"] = "не удалось прочитать /proc/stat"

    ram = None
    try:
        ram = admin_metrics.ram_usage()
    except Exception:
        logger.warning("не удалось собрать метрику RAM", exc_info=True)
        errors["ram"] = "не удалось прочитать /proc/meminfo"

    disk = None
    if "disk" not in errors:
        try:
            disk = admin_metrics.disk_usage(workspace_root)
        except Exception:
            logger.warning("не удалось собрать метрику диска для %s", workspace_root, exc_info=True)
            errors["disk"] = "не удалось прочитать диск"

    active_sessions = None
    active_users = None
    try:
        active = storage.count_active_sessions(request.app["db"], now=time.time())
        active_sessions = active["sessions"]
        active_users = active["users"]
    except Exception:
        logger.warning("не удалось посчитать активные сессии", exc_info=True)
        errors["sessions"] = "не удалось посчитать активные сессии"

    payload = {
        "cpu_percent": cpu,
        "ram": ram,
        "disk": disk,
        "active_sessions": active_sessions,
        "active_users": active_users,
    }
    if errors:
        payload["errors"] = errors
    return web.json_response(payload)


async def handle_admin_list_users(request: web.Request) -> web.Response:
    _require_owner(request)
    config = request.app["quickchat_config"]
    db = request.app["db"]
    result = []
    for row in storage.list_users(db):
        username = row["username"]
        project_count = projects.count_projects(username, config)
        result.append({
            "username": username,
            "display_name": row["display_name"],
            "role": row["role"],
            "project_count": project_count,
            "last_active": storage.get_last_activity(db, username),
        })
    return web.json_response({"users": result})


async def handle_admin_create_user(request: web.Request) -> web.Response:
    admin_user = _require_owner(request)
    body = await request.json()
    username = str(body.get("username", ""))
    display_name = str(body.get("display_name", "")).strip()
    role = str(body.get("role", ""))
    password = str(body.get("password", ""))

    if not USERNAME_RE.match(username):
        return web.json_response(
            {"error": "логин должен состоять из строчных латинских букв, цифр, '_' и '-' (2-32 символа)"},
            status=400,
        )
    if role not in ("owner", "participant"):
        return web.json_response({"error": "role должен быть 'owner' или 'participant'"}, status=400)
    if not display_name:
        return web.json_response({"error": "имя не может быть пустым"}, status=400)
    if not password:
        return web.json_response({"error": "пароль не может быть пустым"}, status=400)
    if storage.get_user(request.app["db"], username) is not None:
        return web.json_response({"error": f"пользователь '{username}' уже существует"}, status=409)

    storage.create_user(request.app["db"], username, auth.hash_password(password), role, display_name)
    storage.log_event(request.app["db"], admin_user["username"], "user.create", username)
    return web.json_response({"username": username, "display_name": display_name, "role": role})


async def handle_admin_update_user(request: web.Request) -> web.Response:
    admin_user = _require_owner(request)
    username = request.match_info["username"]
    body = await request.json()
    display_name = str(body.get("display_name", "")).strip()
    role = str(body.get("role", ""))

    if storage.get_user(request.app["db"], username) is None:
        return web.json_response({"error": "пользователь не найден"}, status=404)
    if role not in ("owner", "participant"):
        return web.json_response({"error": "role должен быть 'owner' или 'participant'"}, status=400)
    if not display_name:
        return web.json_response({"error": "имя не может быть пустым"}, status=400)
    if username == admin_user["username"] and role != "owner":
        return web.json_response({"error": "нельзя понизить роль самому себе"}, status=400)

    storage.update_user(request.app["db"], username, display_name, role)
    storage.log_event(request.app["db"], admin_user["username"], "user.update", username)
    return web.json_response({"username": username, "display_name": display_name, "role": role})


async def handle_admin_reset_password(request: web.Request) -> web.Response:
    admin_user = _require_owner(request)
    username = request.match_info["username"]
    body = await request.json()
    password = str(body.get("password", ""))

    if storage.get_user(request.app["db"], username) is None:
        return web.json_response({"error": "пользователь не найден"}, status=404)
    if not password:
        return web.json_response({"error": "пароль не может быть пустым"}, status=400)

    storage.update_user_password(request.app["db"], username, auth.hash_password(password))
    storage.log_event(request.app["db"], admin_user["username"], "user.reset_password", username)
    return web.json_response({"ok": True})


async def handle_admin_events(request: web.Request) -> web.Response:
    _require_owner(request)
    limit = int(request.query.get("limit", "50"))
    events = storage.list_events(request.app["db"], limit=limit)
    return web.json_response({"events": events})


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


UPLOAD_MAX_SIZE = 64 * 1024 * 1024  # 64 MiB — сканы учебников/PDF/скриншоты


def create_app(*, db_path: str, quickchat_config: quickchat.Config, cookie_secure: bool = True, static_dir: str) -> web.Application:
    # aiohttp по умолчанию режет тело запроса на 1 MiB (client_max_size) — для
    # /api/projects/upload этого достаточно только для мелких скриншотов;
    # реальный кейс проекта (сканы книг, PDF) регулярно больше. Лимит общий
    # на всё приложение (aiohttp не даёт настроить его per-route без ручного
    # чтения тела самому), но остальные эндпоинты — небольшие JSON-запросы,
    # так что поднятие лимита им не вредит.
    app = web.Application(middlewares=[auth_middleware], client_max_size=UPLOAD_MAX_SIZE)
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
    app.router.add_get("/api/groups", handle_list_groups)
    app.router.add_post("/api/groups", handle_create_group)
    app.router.add_put("/api/groups/{slug}", handle_update_group)
    app.router.add_get("/api/projects", handle_list_projects)
    app.router.add_post("/api/projects", handle_create_project)
    app.router.add_get("/api/projects/detail", handle_project_detail)
    app.router.add_post("/api/projects/search", handle_search_projects)
    app.router.add_post("/api/projects/move", handle_move_project)
    app.router.add_post("/api/projects/delete", handle_delete_project)
    app.router.add_post("/api/projects/metadata", handle_update_project_metadata)
    app.router.add_post("/api/projects/open", handle_open_project)
    app.router.add_get("/api/projects/tree", handle_project_tree)
    app.router.add_get("/api/projects/file", handle_project_file_get)
    app.router.add_post("/api/projects/file", handle_project_file_post)
    app.router.add_post("/api/projects/mkdir", handle_project_mkdir)
    app.router.add_post("/api/projects/move-entry", handle_project_move_entry)
    app.router.add_post("/api/projects/delete-entry", handle_project_delete_entry)
    app.router.add_post("/api/projects/upload", handle_project_upload)
    app.router.add_get("/api/admin/overview", handle_admin_overview)
    app.router.add_get("/api/admin/users", handle_admin_list_users)
    app.router.add_post("/api/admin/users", handle_admin_create_user)
    app.router.add_post("/api/admin/users/{username}", handle_admin_update_user)
    app.router.add_post("/api/admin/users/{username}/reset-password", handle_admin_reset_password)
    app.router.add_get("/api/admin/events", handle_admin_events)
    app.router.add_get("/", handle_root)
    app.router.add_static("/", static_dir, show_index=False)
    return app
