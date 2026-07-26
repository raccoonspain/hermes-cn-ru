# Веб-бэкенд Hermes — авторизация + «Быстрый чат» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать и выкатить на реальный VPS веб-бэкенд `hermes-web` — вход по логину/паролю на `hermes.blackboxbegin.space` и «Быстрый чат» с Hermes через браузер (замена Matrix для этого сценария), с полной интеграцией с уже задеплоенным плагином `project_index`.

**Architecture:** Пакет `hermes-web/hermes_web/` (Python, `aiohttp`) разбит на слой хранения (`storage.py` — SQLite: `users`/`web_sessions`/`chat_sessions`), слой аутентификации (`auth.py` — хэш паролей `argon2`, куки-сессии, rate limit на `/login`), клиент Hermes API-сервера (`hermes_client.py` — HTTP до `127.0.0.1:8642`, SSE-парсинг), бизнес-логику «быстрого чата» (`quickchat.py` — создаёт проект в `ALL` через `project_index.core` напрямую, создаёт Hermes-сессию, проксирует сообщения) и веб-приложение (`app.py` — маршруты, auth-middleware, раздача статики). Статика — доработанные существующие макеты `login.html`/`home.html` из `/result/` плюс новая минимальная `chat.html` (проектное дерево/лог активности — вне этого среза, см. спек).

**Tech Stack:** Python 3.11 (венв Hermes на сервере) / 3.12 (локальная разработка), `aiohttp` (тот же стек, что и у самого Hermes API-сервера), `argon2-cffi` (хэш паролей), `pytest` + `pytest-aiohttp` (только тесты, не деплоится).

## Global Constraints

Точные значения — копия из спека (`docs/superpowers/specs/2026-07-26-web-backend-auth-chat-design.md`), обязательны для всех задач ниже:

- Hermes API server слушает `127.0.0.1:8642` (уже так на сервере по умолчанию, `DEFAULT_HOST`/`DEFAULT_PORT` в `gateway/platforms/api_server.py`), включается наличием `API_SERVER_KEY` в `~/.hermes/.env` (без записи в `config.yaml` — та же модель, что у Matrix).
- Реальный контракт Hermes API server (проверено чтением `gateway/platforms/api_server.py` на сервере):
  - `POST /api/sessions` body `{"id": "<session_id>"}` (опц. `title`/`model`/`system_prompt`), заголовок `Authorization: Bearer <API_SERVER_KEY>` → `201 {"object": "hermes.session", "session": {...}}`, `409` если `id` уже занят.
  - `POST /api/sessions/{id}/chat/stream` body `{"message": "<text>", "system_message": "<optional>"}` → `200 text/event-stream`, формат `event: <name>\ndata: <json>\n\n`. События: `run.started`, `message.started`, `assistant.delta` (`{message_id, delta}`), `tool.progress`/`tool.started`/`tool.completed`/`tool.failed`, `assistant.completed` (`{content, completed, ...}`), `run.completed`, `error` (`{message}`), `done` (`{}`). Строки, начинающиеся с `:`, — keepalive-комментарии, игнорировать.
  - `GET /api/sessions/{id}/messages` → `{"object": "list", "session_id": ..., "data": [{"role", "content", "timestamp", ...}, ...]}`.
- `hermes-web` слушает `127.0.0.1:8643` (не торчит наружу напрямую).
- Публичный домен `hermes.blackboxbegin.space` → Caddy (авто-TLS) → `127.0.0.1:8643`. DNS уже указывает на `212.115.55.116`.
- SQLite `hermes-web.db`: таблицы `users` (username, password_hash, role, display_name), `web_sessions` (token, username, expires_at — куки-сессии входа), `chat_sessions` (id, user, project_path, hermes_session_id, created_at, last_message_at).
- Пароли — `argon2` (`argon2-cffi`), не bcrypt/plaintext. Куки-сессии — случайный токен в SQLite, не JWT (нужен мгновенный отзыв при логауте).
- Без самостоятельной регистрации — только `seed_users.py`, создаёт `dem` (role=`owner`) и `rost` (role=`participant`).
- «Быстрый чат» всегда создаёт проект в `workspace/<user>/ALL/<слаг>/` с placeholder `about.md`, вызывает `project_index.core.index_update(user, project_path)` напрямую (импорт модуля, не через LLM/агента).
- `project_index.core` подключается через `sys.path` на путь, заданный `PROJECT_INDEX_PLUGIN_DIR` (на сервере — `/home/hermes/.hermes/plugins`, локально в тестах — `hermes-plugins/` этого репозитория).
- Логин/пароль не палит, какой из двух неверный — всегда одно сообщение об ошибке. Rate limit на `/login` — 5 попыток / 5 минут на ключ `ip+username`, в памяти процесса (не в SQLite — рестарт сбрасывающий счётчик приемлем для 2-пользовательского приложения).
- Деплой — `rsync`, без `git` на проде (как и `project_index`). Systemd user-юнит `hermes-web.service` под `hermes`, `EnvironmentFile=~/.hermes/.env` (общие секреты с самим Hermes: `WORMSOFT_API_KEY`, теперь плюс `API_SERVER_KEY`).

---

## Task 0: Локальное окружение, структура пакета

**Files:**
- Create: `/home/deploy/hermes-cn-ru/.gitignore` (дополнить)
- Create: `/home/deploy/hermes-cn-ru/hermes-web/` — структура каталогов
- Create: (вне репозитория) `/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/` — локальный venv для тестов

**Interfaces:** нет (инфраструктурная задача).

- [ ] **Step 1: Создать структуру каталогов**

```bash
mkdir -p /home/deploy/hermes-cn-ru/hermes-web/hermes_web
mkdir -p /home/deploy/hermes-cn-ru/hermes-web/tests
mkdir -p /home/deploy/hermes-cn-ru/hermes-web/static
```

- [ ] **Step 2: Создать локальный venv и поставить зависимости**

```bash
python3 -m venv /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pip install --quiet aiohttp==3.14.1 argon2-cffi==25.1.0 pytest==9.0.2 pytest-aiohttp==1.1.0
```

Expected: устанавливается без ошибок. Версия `aiohttp` (3.14.1) намеренно совпадает с уже установленной в венве Hermes на сервере (`~/.hermes/hermes-agent/venv`, проверено `pip show aiohttp` — это зависимость самого `hermes-agent`) — на сервере `hermes-web` будет работать в **том же общем венве**, переустановка `aiohttp` другой версии там понизила бы версию, от которой зависит сам гейтвей/API-сервер (см. Task 8, Step 3 — там `aiohttp` намеренно не трогается).

- [ ] **Step 3: Дополнить `.gitignore`**

Добавить в конец `/home/deploy/hermes-cn-ru/.gitignore`:

```
# hermes-web: локальная SQLite-база (только на сервере/в тестах)
hermes-web/*.db
hermes-web/**/*.db
```

- [ ] **Step 4: Создать `hermes-web/hermes_web/__init__.py`** (пустой пакет-плейсхолдер)

```python
"""hermes-web: авторизация + «Быстрый чат» поверх Hermes API server и project_index."""
```

- [ ] **Step 5: Создать `hermes-web/tests/conftest.py`**

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Локально project_index лежит в hermes-plugins/ этого же репозитория —
# hermes_web.quickchat читает PROJECT_INDEX_PLUGIN_DIR из окружения, чтобы
# найти пакет project_index на sys.path (на сервере это /home/hermes/.hermes/plugins).
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
os.environ.setdefault(
    "PROJECT_INDEX_PLUGIN_DIR",
    os.path.abspath(os.path.join(_REPO_ROOT, "hermes-plugins")),
)
```

- [ ] **Step 6: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add .gitignore hermes-web/
git commit -m "chore(hermes-web): каркас пакета, локальный venv, .gitignore"
```

(Пустые каталоги `static/` git не коммитит — файлы появятся в Task 7.)

---

## Task 1: Слой хранения — `storage.py`

**Files:**
- Create: `hermes-web/hermes_web/storage.py`
- Test: `hermes-web/tests/test_storage.py`

**Interfaces:**
- Produces: `get_connection(db_path: str) -> sqlite3.Connection`, `init_db(conn)`, `create_user(conn, username, password_hash, role, display_name)`, `get_user(conn, username) -> dict | None`, `create_web_session(conn, token, username, expires_at: float)`, `get_web_session(conn, token, now: float) -> dict | None`, `delete_web_session(conn, token)`, `create_chat_session(conn, id, user, project_path, hermes_session_id, created_at: float)`, `get_chat_session(conn, id) -> dict | None`, `touch_chat_session(conn, id, last_message_at: float)`. Используются в Task 2 (`web_sessions`) и Task 4/5 (`chat_sessions`) — не менять сигнатуры без синхронной правки там.

- [ ] **Step 1: Написать падающий тест `test_storage.py`**

```python
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
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_storage.py -v
```

Expected: `ModuleNotFoundError: No module named 'hermes_web.storage'`.

- [ ] **Step 3: Написать `hermes-web/hermes_web/storage.py`**

```python
"""SQLite-backed storage for hermes-web: users, web-login sessions, chat sessions."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            display_name TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS web_sessions (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            user TEXT NOT NULL,
            project_path TEXT NOT NULL,
            hermes_session_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            last_message_at REAL
        )
        """
    )
    conn.commit()


def create_user(conn: sqlite3.Connection, username: str, password_hash: str, role: str, display_name: str) -> None:
    conn.execute(
        "INSERT INTO users (username, password_hash, role, display_name) VALUES (?, ?, ?, ?)",
        (username, password_hash, role, display_name),
    )
    conn.commit()


def get_user(conn: sqlite3.Connection, username: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def create_web_session(conn: sqlite3.Connection, token: str, username: str, expires_at: float) -> None:
    conn.execute(
        "INSERT INTO web_sessions (token, username, expires_at) VALUES (?, ?, ?)",
        (token, username, expires_at),
    )
    conn.commit()


def get_web_session(conn: sqlite3.Connection, token: str, now: float) -> Optional[dict]:
    row = conn.execute("SELECT * FROM web_sessions WHERE token = ?", (token,)).fetchone()
    if row is None or row["expires_at"] <= now:
        return None
    return dict(row)


def delete_web_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM web_sessions WHERE token = ?", (token,))
    conn.commit()


def create_chat_session(
    conn: sqlite3.Connection, id: str, user: str, project_path: str, hermes_session_id: str, created_at: float,
) -> None:
    conn.execute(
        """
        INSERT INTO chat_sessions (id, user, project_path, hermes_session_id, created_at, last_message_at)
        VALUES (?, ?, ?, ?, ?, NULL)
        """,
        (id, user, project_path, hermes_session_id, created_at),
    )
    conn.commit()


def get_chat_session(conn: sqlite3.Connection, id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (id,)).fetchone()
    return dict(row) if row else None


def touch_chat_session(conn: sqlite3.Connection, id: str, last_message_at: float) -> None:
    conn.execute("UPDATE chat_sessions SET last_message_at = ? WHERE id = ?", (last_message_at, id))
    conn.commit()
```

- [ ] **Step 4: Запустить тесты — все должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_storage.py -v
```

Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/
git commit -m "feat(hermes-web): слой хранения — users/web_sessions/chat_sessions"
```

---

## Task 2: Аутентификация — `auth.py`

**Files:**
- Create: `hermes-web/hermes_web/auth.py`
- Test: `hermes-web/tests/test_auth.py`

**Interfaces:**
- Consumes: ничего из Task 1 напрямую (чистые функции — `app.py` в Task 5 сам передаёт результаты в `storage`).
- Produces: `hash_password(password: str) -> str`, `verify_password(password: str, password_hash: str) -> bool`, `generate_session_token() -> str`, `RateLimiter` (класс с методом `allow(self, key: str, now: float) -> bool`). Используются в Task 5.

- [ ] **Step 1: Написать падающий тест `test_auth.py`**

```python
import pytest

from hermes_web import auth


def test_hash_password_and_verify_roundtrip():
    hashed = auth.hash_password("correct-horse-battery-staple")
    assert hashed != "correct-horse-battery-staple"
    assert auth.verify_password("correct-horse-battery-staple", hashed) is True


def test_verify_password_wrong_password_returns_false():
    hashed = auth.hash_password("correct-horse-battery-staple")
    assert auth.verify_password("wrong-password", hashed) is False


def test_verify_password_garbage_hash_returns_false():
    assert auth.verify_password("anything", "not-a-real-hash") is False


def test_generate_session_token_is_random_and_long():
    tokens = {auth.generate_session_token() for _ in range(20)}
    assert len(tokens) == 20
    assert all(len(t) >= 32 for t in tokens)


def test_rate_limiter_allows_up_to_limit_then_blocks():
    limiter = auth.RateLimiter(max_attempts=5, window_seconds=300)
    key = "1.2.3.4:dem"
    for _ in range(5):
        assert limiter.allow(key, now=1000.0) is True
    assert limiter.allow(key, now=1000.0) is False


def test_rate_limiter_resets_after_window():
    limiter = auth.RateLimiter(max_attempts=2, window_seconds=300)
    key = "1.2.3.4:dem"
    assert limiter.allow(key, now=1000.0) is True
    assert limiter.allow(key, now=1001.0) is True
    assert limiter.allow(key, now=1001.0) is False
    assert limiter.allow(key, now=1302.0) is True


def test_rate_limiter_keys_are_independent():
    limiter = auth.RateLimiter(max_attempts=1, window_seconds=300)
    assert limiter.allow("user-a", now=1000.0) is True
    assert limiter.allow("user-b", now=1000.0) is True
    assert limiter.allow("user-a", now=1000.0) is False
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_auth.py -v
```

Expected: `ModuleNotFoundError: No module named 'hermes_web.auth'`.

- [ ] **Step 3: Написать `hermes-web/hermes_web/auth.py`**

```python
"""Password hashing, session tokens, and a simple in-memory login rate limiter."""
from __future__ import annotations

import secrets
from collections import defaultdict, deque
from typing import Deque, Dict

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHash):
        return False


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


class RateLimiter:
    """Sliding-window limiter, in-memory — resets on process restart (acceptable
    for a two-user app; see Global Constraints)."""

    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._attempts: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str, now: float) -> bool:
        attempts = self._attempts[key]
        cutoff = now - self._window_seconds
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if len(attempts) >= self._max_attempts:
            return False
        attempts.append(now)
        return True
```

- [ ] **Step 4: Запустить тесты — все должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_auth.py -v
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/
git commit -m "feat(hermes-web): аутентификация — argon2, куки-токены, rate limiter"
```

---

## Task 3: Клиент Hermes API server — `hermes_client.py`

**Files:**
- Create: `hermes-web/hermes_web/hermes_client.py`
- Test: `hermes-web/tests/test_hermes_client.py`

**Interfaces:**
- Consumes: ничего из Task 1/2.
- Produces: `HermesClientError(Exception)`, `async create_session(http_session, base_url, api_key, session_id: str) -> dict`, `async stream_chat(http_session, base_url, api_key, hermes_session_id: str, message: str, system_message: str | None = None) -> AsyncIterator[tuple[str, dict]]`, `async get_messages(http_session, base_url, api_key, hermes_session_id: str) -> list[dict]`. Используются в Task 4.

- [ ] **Step 1: Написать падающий тест `test_hermes_client.py`**

Тест поднимает настоящий `aiohttp`-сервер в процессе (`aiohttp.test_utils.TestServer`), который отвечает в точности как реальный Hermes API server (см. Global Constraints), и проверяет, что `hermes_client` правильно шлёт запросы и разбирает SSE.

```python
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
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_hermes_client.py -v
```

Expected: `ModuleNotFoundError: No module named 'hermes_web.hermes_client'`.

- [ ] **Step 3: Написать `hermes-web/hermes_web/hermes_client.py`**

```python
"""Thin async client for the Hermes API server (gateway/platforms/api_server.py).

Contract verified by reading the real handler code on the deployed VPS —
see Global Constraints in the implementation plan. No third-party SDK:
this is three small HTTP calls plus an SSE line parser.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional


class HermesClientError(Exception):
    """Raised when the Hermes API server returns a non-2xx status."""


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


async def create_session(http_session, base_url: str, api_key: str, session_id: str) -> dict:
    url = f"{base_url.rstrip('/')}/api/sessions"
    async with http_session.post(url, json={"id": session_id}, headers=_headers(api_key)) as resp:
        if resp.status >= 300:
            text = await resp.text()
            raise HermesClientError(f"create_session failed: {resp.status} {text}")
        return await resp.json()


async def stream_chat(
    http_session,
    base_url: str,
    api_key: str,
    hermes_session_id: str,
    message: str,
    system_message: Optional[str] = None,
) -> AsyncIterator[tuple[str, dict]]:
    url = f"{base_url.rstrip('/')}/api/sessions/{hermes_session_id}/chat/stream"
    body: dict[str, Any] = {"message": message}
    if system_message:
        body["system_message"] = system_message

    async with http_session.post(url, json=body, headers=_headers(api_key)) as resp:
        if resp.status >= 300:
            text = await resp.text()
            raise HermesClientError(f"stream_chat failed: {resp.status} {text}")

        event_name: Optional[str] = None
        data_lines: list[str] = []
        async for raw_line in resp.content:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if line.startswith(":"):
                continue
            if line == "":
                if event_name is not None:
                    payload = json.loads("\n".join(data_lines)) if data_lines else {}
                    yield event_name, payload
                event_name = None
                data_lines = []
                continue
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())


async def get_messages(http_session, base_url: str, api_key: str, hermes_session_id: str) -> list:
    url = f"{base_url.rstrip('/')}/api/sessions/{hermes_session_id}/messages"
    async with http_session.get(url, headers=_headers(api_key)) as resp:
        if resp.status >= 300:
            text = await resp.text()
            raise HermesClientError(f"get_messages failed: {resp.status} {text}")
        data = await resp.json()
        return data["data"]
```

- [ ] **Step 4: Запустить тесты — все должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_hermes_client.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/
git commit -m "feat(hermes-web): клиент Hermes API server — сессии, SSE-чат, история"
```

---

## Task 4: Бизнес-логика «Быстрого чата» — `quickchat.py`

**Files:**
- Create: `hermes-web/hermes_web/quickchat.py`
- Test: `hermes-web/tests/test_quickchat.py`

**Interfaces:**
- Consumes: `storage.get_connection/create_chat_session/get_chat_session/touch_chat_session` (Task 1), `hermes_client.create_session/stream_chat/get_messages` (Task 3), `project_index.core.index_update` (уже задеплоенный плагин, импортируется через `PROJECT_INDEX_PLUGIN_DIR`).
- Produces: `Config` (dataclass, in field order: `hermes_base_url: str`, `hermes_api_key: str`, `workspace_root: str | None = None`, `project_index_db_path: str | None = None`, `wormsoft_api_key: str | None = None` — required fields first since the optional ones default to `None`; all call sites in this plan use keyword arguments, so the order is informational, not load-bearing), `QuickChatError(Exception)`, `async create_quick_chat(db_conn, http_session, config, user: str) -> dict` (keys: `chat_session_id`, `project_path`, `hermes_session_id`), `async send_message(db_conn, http_session, config, chat_session_id: str, text: str) -> AsyncIterator[tuple[str, dict]]`, `async get_history(db_conn, http_session, config, chat_session_id: str) -> list`. Используются в Task 5.

- [ ] **Step 1: Написать падающий тест `test_quickchat.py`**

```python
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
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_quickchat.py -v
```

Expected: `ModuleNotFoundError: No module named 'hermes_web.quickchat'`.

- [ ] **Step 3: Написать `hermes-web/hermes_web/quickchat.py`**

```python
"""«Быстрый чат»: создаёт проект в ALL (через project_index.core напрямую,
без похода через LLM), заводит Hermes-сессию, проксирует сообщения.

project_index — уже задеплоенный Hermes-плагин (см.
docs/superpowers/specs/2026-07-25-project-index-plugin-design.md). Мы
импортируем его core-модуль напрямую: тот спроектирован именно для этого
("future caller — the planned web backend — can load this module
directly"). PROJECT_INDEX_PLUGIN_DIR добавляется на sys.path тем, кто
собирает Config (см. run.py в Task 5 / conftest.py в тестах), не этим
модулем — чтобы quickchat.py не был жёстко привязан к переменным
окружения на верхнем уровне импорта.
"""
from __future__ import annotations

import datetime
import os
import sys
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from . import hermes_client, storage

_PROJECT_INDEX_DIR = os.environ.get("PROJECT_INDEX_PLUGIN_DIR")
if _PROJECT_INDEX_DIR and _PROJECT_INDEX_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_INDEX_DIR)

from project_index import core as project_index_core  # noqa: E402


class QuickChatError(Exception):
    """Raised for expected, user-facing failures (unknown chat session, etc.)."""


@dataclass
class Config:
    hermes_base_url: str
    hermes_api_key: str
    workspace_root: Optional[str] = None
    project_index_db_path: Optional[str] = None
    wormsoft_api_key: Optional[str] = None


ABOUT_MD_PLACEHOLDER = """---
tags: []
status: active
---

# Название проекта
{title}

# Краткое описание
Ждёт первого сообщения

# Опорные точки

# На чём остановились
"""


def _project_index_kwargs(config: Config) -> dict:
    kwargs = {}
    if config.workspace_root is not None:
        kwargs["workspace_root"] = config.workspace_root
    if config.project_index_db_path is not None:
        kwargs["db_path"] = config.project_index_db_path
    if config.wormsoft_api_key is not None:
        kwargs["api_key"] = config.wormsoft_api_key
    return kwargs


def _workspace_root(config: Config) -> str:
    return config.workspace_root or project_index_core.WORKSPACE_ROOT


async def create_quick_chat(db_conn, http_session, config: Config, user: str) -> dict:
    today = datetime.date.today().isoformat()
    slug = f"{today}_chat-{uuid.uuid4().hex[:8]}"
    project_rel_path = os.path.join(user, "ALL", slug)
    project_abs_path = os.path.join(_workspace_root(config), user, "ALL", slug)

    os.makedirs(project_abs_path, exist_ok=True)
    now_label = datetime.datetime.now().strftime("%H:%M")
    with open(os.path.join(project_abs_path, "about.md"), "w", encoding="utf-8") as fh:
        fh.write(ABOUT_MD_PLACEHOLDER.format(title=f"Новый разговор {now_label}"))

    index_result = project_index_core.index_update(user, project_rel_path, **_project_index_kwargs(config))

    hermes_session_id = f"web_{uuid.uuid4().hex}"
    await hermes_client.create_session(http_session, config.hermes_base_url, config.hermes_api_key, hermes_session_id)

    chat_session_id = uuid.uuid4().hex
    storage.create_chat_session(
        db_conn, chat_session_id, user, index_result["path"], hermes_session_id, created_at=time.time(),
    )

    return {
        "chat_session_id": chat_session_id,
        "project_path": index_result["path"],
        "hermes_session_id": hermes_session_id,
    }


def _system_message_for(project_path: str) -> str:
    return (
        f"Текущий проект: {project_path}. Все файлы для этого разговора клади "
        "в подпапки внутри этого пути (см. правило про подпапки на задачу и "
        "project_index в SOUL.md)."
    )


async def send_message(db_conn, http_session, config: Config, chat_session_id: str, text: str) -> AsyncIterator[tuple[str, dict]]:
    row = storage.get_chat_session(db_conn, chat_session_id)
    if row is None:
        raise QuickChatError(f"неизвестная сессия чата: {chat_session_id}")

    async for name, payload in hermes_client.stream_chat(
        http_session,
        config.hermes_base_url,
        config.hermes_api_key,
        row["hermes_session_id"],
        text,
        system_message=_system_message_for(row["project_path"]),
    ):
        yield name, payload

    storage.touch_chat_session(db_conn, chat_session_id, last_message_at=time.time())


async def get_history(db_conn, http_session, config: Config, chat_session_id: str) -> list:
    row = storage.get_chat_session(db_conn, chat_session_id)
    if row is None:
        raise QuickChatError(f"неизвестная сессия чата: {chat_session_id}")
    return await hermes_client.get_messages(http_session, config.hermes_base_url, config.hermes_api_key, row["hermes_session_id"])
```

- [ ] **Step 4: Запустить тесты — все должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_quickchat.py -v
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/
git commit -m "feat(hermes-web): quickchat — создание проекта в ALL + Hermes-сессия + прокси сообщений"
```

---

## Task 5: Веб-приложение — `app.py`

**Files:**
- Create: `hermes-web/hermes_web/app.py`
- Test: `hermes-web/tests/test_app.py`

**Interfaces:**
- Consumes: `auth.hash_password/verify_password/generate_session_token/RateLimiter` (Task 2), `storage.*` (Task 1), `quickchat.Config/create_quick_chat/send_message/get_history` (Task 4).
- Produces: `create_app(*, db_path: str, quickchat_config, cookie_secure: bool = True, static_dir: str) -> aiohttp.web.Application`. Используется в Task 6 (`run.py`, деплой) — не меняется дальше в этом плане.

- [ ] **Step 1: Написать падающий тест `test_app.py`**

```python
import json

import pytest

from hermes_web import auth, quickchat, storage
from hermes_web.app import create_app


@pytest.fixture
def app_and_conn(tmp_path, monkeypatch):
    db_path = str(tmp_path / "hermes-web.db")
    conn = storage.get_connection(db_path)
    storage.create_user(conn, "dem", auth.hash_password("secret123"), "owner", "Дмитрий")
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
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_app.py -v
```

Expected: `ModuleNotFoundError: No module named 'hermes_web.app'`.

- [ ] **Step 3: Написать `hermes-web/hermes_web/app.py`**

```python
"""aiohttp web application: login/logout, /api/me, quick-chat, chat send/history,
плюс раздача статики. Неавторизованные HTML-страницы (login.html/home.html/
chat.html) отдаются как обычные статические файлы — секретов в них нет,
авторизация проверяется на уровне API (/api/me и т.д.), а фронтенд сам
редиректит на /login.html при 401 (см. static-JS в Task 7)."""
from __future__ import annotations

import json
import time

import aiohttp
from aiohttp import web

from . import auth, quickchat, storage

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

    row = storage.get_chat_session(request.app["db"], chat_session_id)
    if row is None or row["user"] != user["username"]:
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
    except quickchat.QuickChatError as exc:
        data = json.dumps({"message": str(exc)}, ensure_ascii=False)
        await response.write(f"event: error\ndata: {data}\n\n".encode("utf-8"))
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


async def _on_cleanup(app: web.Application) -> None:
    await app["http_session"].close()


def create_app(*, db_path: str, quickchat_config: quickchat.Config, cookie_secure: bool, static_dir: str) -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app["db"] = storage.get_connection(db_path)
    app["quickchat_config"] = quickchat_config
    app["cookie_secure"] = cookie_secure
    app["rate_limiter"] = auth.RateLimiter(RATE_LIMIT_MAX_ATTEMPTS, RATE_LIMIT_WINDOW_SECONDS)
    app["http_session"] = aiohttp.ClientSession()
    app.on_cleanup.append(_on_cleanup)

    app.router.add_post("/login", handle_login)
    app.router.add_post("/logout", handle_logout)
    app.router.add_get("/api/me", handle_me)
    app.router.add_post("/api/quick-chat", handle_quick_chat)
    app.router.add_post("/api/chat/{chat_session_id}/send", handle_send_message)
    app.router.add_get("/api/chat/{chat_session_id}/messages", handle_get_messages)
    app.router.add_static("/", static_dir, show_index=False)
    return app
```

- [ ] **Step 4: Запустить тесты — все должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_app.py -v
```

Expected: `9 passed`.

- [ ] **Step 5: Прогнать весь набор тестов вместе**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/ -v
```

Expected: `33 passed` (8 storage + 7 auth + 4 hermes_client + 5 quickchat + 9 app).

- [ ] **Step 6: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/
git commit -m "feat(hermes-web): веб-приложение — login/logout/me/quick-chat/send/messages"
```

---

## Task 6: Сид пользователей и entrypoint — `seed_users.py`, `run.py`

**Files:**
- Create: `hermes-web/hermes_web/seed_users.py`
- Create: `hermes-web/run.py`
- Test: `hermes-web/tests/test_seed_users.py`

**Interfaces:**
- Consumes: `storage.get_connection/create_user/get_user` (Task 1), `auth.hash_password` (Task 2).
- Produces: `seed_user(conn, username, password, role, display_name) -> None` (используется CLI-обёрткой `main()`, тестируется напрямую). `run.py` ничего не экспортирует — это entrypoint для systemd (Task 8).

- [ ] **Step 1: Написать падающий тест `test_seed_users.py`**

```python
import pytest

from hermes_web import auth, storage
from hermes_web.seed_users import seed_user


def test_seed_user_creates_user_with_hashed_password(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    seed_user(conn, "dem", "secret123", "owner", "Дмитрий")

    row = storage.get_user(conn, "dem")
    assert row["role"] == "owner"
    assert row["display_name"] == "Дмитрий"
    assert row["password_hash"] != "secret123"
    assert auth.verify_password("secret123", row["password_hash"]) is True


def test_seed_user_duplicate_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    seed_user(conn, "dem", "secret123", "owner", "Дмитрий")
    with pytest.raises(Exception):
        seed_user(conn, "dem", "other", "owner", "Дмитрий 2")
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_seed_users.py -v
```

Expected: `ModuleNotFoundError: No module named 'hermes_web.seed_users'`.

- [ ] **Step 3: Написать `hermes-web/hermes_web/seed_users.py`**

```python
"""Разовый ручной сид пользователей — без UI в этом срезе (см. спек,
управление пользователями — отдельный срез 4, admin.html).

Запуск на сервере:
    cd ~/hermes-web
    venv/bin/python3 -m hermes_web.seed_users dem owner "Дмитрий"
(пароль запрашивается интерактивно, не передаётся аргументом — не
светится в истории шелла/логах процессов)
"""
from __future__ import annotations

import argparse
import getpass
import sys

from . import auth, storage

DEFAULT_DB_PATH = "hermes-web.db"


def seed_user(conn, username: str, password: str, role: str, display_name: str) -> None:
    storage.create_user(conn, username, auth.hash_password(password), role, display_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("role", choices=["owner", "participant"])
    parser.add_argument("display_name")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    password = getpass.getpass(f"Пароль для {args.username}: ")
    password_confirm = getpass.getpass("Повторите пароль: ")
    if password != password_confirm:
        print("Пароли не совпадают", file=sys.stderr)
        return 1

    conn = storage.get_connection(args.db_path)
    seed_user(conn, args.username, password, args.role, args.display_name)
    print(f"Пользователь {args.username} ({args.role}) создан")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Запустить тесты — все должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_seed_users.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Написать `hermes-web/run.py`** (entrypoint для systemd, Task 8)

```python
"""Entrypoint запускаемый systemd-юнитом hermes-web.service.

Все настройки — из окружения (EnvironmentFile=~/.hermes/.env в systemd-юните,
общий с самим Hermes — см. Task 8):
  API_SERVER_KEY          — bearer-ключ Hermes API server (обязателен)
  WORMSOFT_API_KEY         — для project_index.core.index_update (опционален,
                              index_update сам деградирует без него)
  PROJECT_INDEX_PLUGIN_DIR — путь к каталогу с пакетом project_index
                              (на сервере: /home/hermes/.hermes/plugins)
  HERMES_WEB_DB_PATH       — путь к hermes-web.db (по умолчанию рядом с этим файлом)
  HERMES_WEB_HOST/PORT     — адрес прослушивания (по умолчанию 127.0.0.1:8643)
  HERMES_WEB_COOKIE_SECURE — "true"/"false" (по умолчанию true; false — только
                              для локальной разработки по http)
"""
from __future__ import annotations

import os
from pathlib import Path

from aiohttp import web

from hermes_web.app import create_app
from hermes_web.quickchat import Config

_HERE = Path(__file__).resolve().parent


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes"}


def main() -> None:
    api_server_key = os.environ["API_SERVER_KEY"]
    db_path = os.environ.get("HERMES_WEB_DB_PATH", str(_HERE / "hermes-web.db"))
    host = os.environ.get("HERMES_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("HERMES_WEB_PORT", "8643"))

    config = Config(
        hermes_base_url=os.environ.get("HERMES_API_BASE_URL", "http://127.0.0.1:8642"),
        hermes_api_key=api_server_key,
        wormsoft_api_key=os.environ.get("WORMSOFT_API_KEY"),
    )
    app = create_app(
        db_path=db_path,
        quickchat_config=config,
        cookie_secure=_bool_env("HERMES_WEB_COOKIE_SECURE", True),
        static_dir=str(_HERE / "static"),
    )
    web.run_app(app, host=host, port=port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/
git commit -m "feat(hermes-web): сид пользователей + entrypoint для systemd"
```

---

## Task 7: Фронтенд — доработка макетов + новая `chat.html`

**Files:**
- Create: `hermes-web/static/login.html` (копия `result/login.html` с правками)
- Create: `hermes-web/static/home.html` (копия `result/home.html` с правками)
- Create: `hermes-web/static/chat.html` (новый минимальный экран чата)
- Create: `hermes-web/static/app.js` (общие JS-хелперы: запросы к API, SSE-парсер)

**Interfaces:** нет для дальнейших задач кода — Task 8 работает с уже собранной статикой как есть.

- [ ] **Step 1: Создать `hermes-web/static/app.js`**

```javascript
// Общие хелперы для login.html/home.html/chat.html — без сборщика, обычный <script src="app.js">.

async function apiFetch(url, options = {}) {
  const resp = await fetch(url, { credentials: 'same-origin', ...options });
  return resp;
}

async function requireAuth() {
  const resp = await apiFetch('/api/me');
  if (resp.status === 401) {
    location.href = 'login.html';
    return null;
  }
  return resp.json();
}

async function logout() {
  await apiFetch('/logout', { method: 'POST' });
  location.href = 'login.html';
}

// Читает text/event-stream тело fetch-ответа построчно и зовёт onEvent(name, payload)
// для каждого события. Формат идентичен Hermes API server: "event: X\ndata: Y\n\n".
async function readSSE(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let eventName = null;
  let dataLines = [];

  function flush() {
    if (eventName !== null) {
      const payload = dataLines.length ? JSON.parse(dataLines.join('\n')) : {};
      onEvent(eventName, payload);
    }
    eventName = null;
    dataLines = [];
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const rawLine of lines) {
      const line = rawLine.replace(/\r$/, '');
      if (line.startsWith(':')) continue;
      if (line === '') { flush(); continue; }
      if (line.startsWith('event:')) eventName = line.slice('event:'.length).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice('data:'.length).trim());
    }
  }
  flush();
}
```

- [ ] **Step 2: Создать `hermes-web/static/login.html`**

Взять `/home/deploy/hermes-cn-ru/result/login.html` за основу (тот же стиль «Созвездие»), заменить нижний колонтитул на `hermes.blackboxbegin.space` и заменить демо-скрипт входа на реальный вызов `/login`:

```html
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes — вход</title>
<style>
  :root{
    --sky:#12172b; --sky-deep:#0b0e1c; --panel:#1a2038; --panel-2:#212949;
    --panel-line:#3c4568; --text:#f8f6ef; --text-dim:#aeb7dc; --gold:#f0bb5c;
    --violet:#ad9fe6; --teal:#7fc4b2; --dim-star:#727bab;
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0;height:100%}
  body{
    background:radial-gradient(ellipse at 50% 30%, #1b2245, var(--sky-deep) 70%);
    color:var(--text);
    font-family:Georgia,"Iowan Old Style",serif;
    height:100vh;
    display:flex;align-items:center;justify-content:center;
    position:relative;
    overflow:hidden;
  }
  #stars{position:fixed;inset:0;pointer-events:none}
  .star{position:absolute;border-radius:50%;background:#fff;animation:twinkle 3.5s ease-in-out infinite}
  @keyframes twinkle{0%,100%{opacity:.15}50%{opacity:.95}}
  svg.lines{position:fixed;inset:0;pointer-events:none}
  svg.lines line{stroke:var(--violet);stroke-width:.6;opacity:.28}
  .stage{position:relative;z-index:2;width:380px;max-width:92vw}
  .brandmark{text-align:center;margin-bottom:34px}
  .brandmark .glyph{font-size:34px;display:inline-block;margin-bottom:8px;filter:drop-shadow(0 0 10px rgba(240,187,92,.5))}
  .brandmark h1{margin:0;font-size:28px;font-weight:400;font-style:italic;letter-spacing:.5px}
  .brandmark p{margin:6px 0 0;font-family:ui-monospace,Consolas,monospace;font-size:11px;letter-spacing:1px;color:var(--text-dim)}
  .card{background:rgba(26,32,56,.75);backdrop-filter:blur(6px);border:1px solid var(--panel-line);border-radius:18px;padding:30px 28px}
  label{display:block;font-family:ui-monospace,Consolas,monospace;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--text-dim);margin:0 0 7px}
  label:not(:first-child){margin-top:16px}
  input[type=password],input[type=text]{width:100%;background:var(--sky-deep);border:1px solid var(--panel-line);border-radius:8px;padding:11px 13px;color:var(--text);font-family:Georgia,serif;font-size:14px;outline:none}
  input[type=password]:focus,input[type=text]:focus{border-color:var(--violet)}
  .submit-btn{width:100%;margin-top:20px;background:var(--gold);color:var(--sky-deep);border:none;padding:12px;border-radius:9px;cursor:pointer;font-family:ui-monospace,Consolas,monospace;font-size:12.5px;letter-spacing:.5px}
  .submit-btn:hover{filter:brightness(1.06)}
  .submit-btn:disabled{opacity:.6;cursor:default}
  .error{margin-top:14px;font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:#e88980;text-align:center;min-height:14px}
  .footnote{text-align:center;margin-top:22px;font-family:ui-monospace,Consolas,monospace;font-size:10.5px;color:var(--dim-star)}
</style>
</head>
<body>

<div id="stars"></div>
<svg class="lines" id="lines"></svg>

<div class="stage">
  <div class="brandmark">
    <div class="glyph">✦</div>
    <h1>Hermes</h1>
    <p>личный ИИ-агент · растёт вместе с вами</p>
  </div>

  <div class="card">
    <label>Логин</label>
    <input type="text" id="loginInput" placeholder="логин" autocomplete="username" autofocus>
    <label>Пароль</label>
    <input type="password" id="pwInput" placeholder="••••••••" autocomplete="current-password">
    <button class="submit-btn" id="submitBtn">Войти →</button>
    <div class="error" id="errorMsg"></div>
  </div>

  <div class="footnote">hermes.blackboxbegin.space</div>
</div>

<script src="app.js"></script>
<script>
const starsEl = document.getElementById('stars');
const linesEl = document.getElementById('lines');
const pts = [];
for(let i=0;i<50;i++){
  const x = Math.random()*100, y = Math.random()*100;
  const size = Math.random()*2.4 + 0.6;
  const el = document.createElement('div');
  el.className = 'star';
  el.style.left = x+'vw'; el.style.top = y+'vh';
  el.style.width = size+'px'; el.style.height = size+'px';
  el.style.animationDelay = (Math.random()*3.5)+'s';
  starsEl.appendChild(el);
  pts.push([x,y]);
}
for(let i=0;i<9;i++){
  const a = pts[Math.floor(Math.random()*pts.length)];
  const b = pts[Math.floor(Math.random()*pts.length)];
  const line = document.createElementNS('http://www.w3.org/2000/svg','line');
  line.setAttribute('x1', a[0]+'%'); line.setAttribute('y1', a[1]+'%');
  line.setAttribute('x2', b[0]+'%'); line.setAttribute('y2', b[1]+'%');
  linesEl.appendChild(line);
}

const submitBtn = document.getElementById('submitBtn');
const errorMsg = document.getElementById('errorMsg');

async function doLogin(){
  const username = document.getElementById('loginInput').value.trim();
  const password = document.getElementById('pwInput').value;
  if(!username || !password) return;
  submitBtn.disabled = true;
  errorMsg.textContent = '';
  try{
    const resp = await apiFetch('/login', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({username, password}),
    });
    if(resp.ok){
      location.href = 'home.html';
      return;
    }
    if(resp.status === 429){
      errorMsg.textContent = 'Слишком много попыток, попробуйте позже';
    } else {
      errorMsg.textContent = 'неверный логин или пароль';
    }
  } catch(e){
    errorMsg.textContent = 'Hermes временно недоступен, попробуйте ещё раз';
  } finally {
    submitBtn.disabled = false;
  }
}

submitBtn.addEventListener('click', doLogin);
document.getElementById('pwInput').addEventListener('keydown', e=>{ if(e.key==='Enter') doLogin(); });
</script>
</body>
</html>
```

- [ ] **Step 3: Создать `hermes-web/static/home.html`**

Взять `/home/deploy/hermes-cn-ru/result/home.html` за основу, убрать демо `role-switch`-дропдаун, вместо него — `requireAuth()` из `app.js`, плитка «Быстрый чат» вызывает `POST /api/quick-chat` и ведёт на `chat.html?id=...`:

```html
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes — главная</title>
<style>
  :root{
    --sky:#12172b; --sky-deep:#0c1020; --panel:#1a2038; --panel-2:#212949;
    --panel-line:#3c4568; --text:#f8f6ef; --text-dim:#aeb7dc; --gold:#f0bb5c;
    --violet:#ad9fe6; --teal:#7fc4b2; --dim-star:#727bab;
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0;min-height:100%}
  body{
    background:
      radial-gradient(1px 1px at 20% 30%, #fff8, transparent),
      radial-gradient(1px 1px at 65% 15%, #fff6, transparent),
      radial-gradient(1.5px 1.5px at 82% 60%, #fff9, transparent),
      radial-gradient(1px 1px at 40% 80%, #fff5, transparent),
      radial-gradient(1px 1px at 12% 65%, #fff7, transparent),
      radial-gradient(1.5px 1.5px at 92% 30%, #fff6, transparent),
      radial-gradient(1px 1px at 75% 85%, #fff6, transparent),
      radial-gradient(1.5px 1.5px at 6% 20%, #fff7, transparent),
      linear-gradient(180deg, var(--sky-deep), var(--sky) 45%);
    background-attachment:fixed;
    color:var(--text);
    font-family:Georgia,"Iowan Old Style",serif;
    min-height:100vh;
  }
  .topbar{display:flex;align-items:center;gap:16px;padding:20px 40px;border-bottom:1px solid var(--panel-line)}
  .topbar .brand{font-family:ui-monospace,Consolas,monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:var(--text-dim)}
  .topbar .brand b{color:var(--text);font-family:Georgia,serif;font-size:16px;font-style:italic;letter-spacing:0;text-transform:none;margin-left:6px}
  .user-pill{margin-left:auto;display:flex;align-items:center;gap:10px}
  .avatar{width:32px;height:32px;border-radius:50%;background:var(--panel-2);border:1px solid var(--panel-line);display:flex;align-items:center;justify-content:center;font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--gold)}
  .user-pill .uname{font-size:13.5px}
  .logout-btn{font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--text-dim);background:none;border:1px solid var(--panel-line);border-radius:20px;padding:6px 13px;cursor:pointer}
  .logout-btn:hover{color:var(--text);border-color:#e88980}
  main{max-width:1040px;margin:0 auto;padding:56px 40px 80px}
  .greeting{margin-bottom:8px;font-size:32px;font-weight:400;font-style:italic}
  .subgreeting{color:var(--text-dim);font-size:14.5px;margin-bottom:30px}
  .tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
  .tile{background:var(--panel);border:1px solid var(--panel-line);border-radius:16px;padding:26px 24px;text-decoration:none;color:var(--text);position:relative;display:flex;flex-direction:column;gap:10px;transition:border-color .15s ease,transform .15s ease;min-height:150px;cursor:pointer}
  .tile:hover{border-color:var(--violet);transform:translateY(-2px)}
  .tile.primary{grid-column:span 2;background:linear-gradient(160deg, var(--panel-2), var(--panel));border-color:var(--gold)}
  .tile .ic{font-size:30px}
  .tile h3{margin:0;font-size:18px;font-weight:400}
  .tile p{margin:0;color:var(--text-dim);font-size:13px;line-height:1.5}
  .tile.disabled{opacity:.55;cursor:default}
  .tile.disabled:hover{border-color:var(--panel-line);transform:none}
  .tile .soon{position:absolute;top:16px;right:16px;font-family:ui-monospace,Consolas,monospace;font-size:9px;letter-spacing:1px;text-transform:uppercase;color:var(--dim-star);border:1px solid var(--panel-line);padding:2px 7px;border-radius:20px}
  [data-role-only="owner"]{display:none}
  body.role-owner [data-role-only="owner"]{display:flex}
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">Hermes <b>· главная</b></div>
  <div class="user-pill">
    <div class="avatar" id="avatarInitial">·</div>
    <span class="uname" id="userName">…</span>
  </div>
  <button class="logout-btn" id="logoutBtn">⏻ Выход</button>
</div>

<main>
  <div class="greeting" id="greeting">Загрузка…</div>
  <div class="subgreeting">Готовы продолжить один из проектов, или начать что-то новое?</div>

  <div class="tiles">
    <a class="tile primary disabled" href="#" onclick="return false">
      <span class="ic">📂</span>
      <h3>Работа с проектами</h3>
      <p>Все группы и темы — скоро (следующий срез).</p>
    </a>

    <a class="tile" id="quickChatTile" href="#">
      <span class="ic">💬</span>
      <h3>Быстрый чат</h3>
      <p>Начать разговор прямо сейчас, без выбора группы — попадёт в ALL, разберётесь с темой позже.</p>
    </a>

    <a class="tile disabled" href="#" onclick="return false">
      <span class="soon">скоро</span>
      <span class="ic">🔭</span>
      <h3>Искать по всем темам</h3>
      <p>Скоро — вместе с «Работой с проектами».</p>
    </a>

    <a class="tile admin disabled" href="#" onclick="return false" data-role-only="owner">
      <span class="soon">скоро</span>
      <span class="ic">🛠️</span>
      <h3>Администрирование</h3>
      <p>Пользователи, метрики VPS и wormsoft.ru — отдельный срез.</p>
    </a>
  </div>
</main>

<script src="app.js"></script>
<script>
(async () => {
  const me = await requireAuth();
  if (!me) return;
  document.getElementById('userName').textContent = me.display_name;
  document.getElementById('avatarInitial').textContent = me.display_name[0].toUpperCase();
  document.getElementById('greeting').textContent = `Добрый день, ${me.display_name}`;
  document.body.classList.toggle('role-owner', me.role === 'owner');
})();

document.getElementById('logoutBtn').addEventListener('click', logout);

document.getElementById('quickChatTile').addEventListener('click', async (e) => {
  e.preventDefault();
  const resp = await apiFetch('/api/quick-chat', { method: 'POST' });
  if (!resp.ok) { alert('Не удалось начать чат — попробуйте ещё раз'); return; }
  const body = await resp.json();
  location.href = `chat.html?id=${encodeURIComponent(body.chat_session_id)}`;
});
</script>
</body>
</html>
```

- [ ] **Step 4: Создать `hermes-web/static/chat.html`** (новый минимальный экран — без дерева `source/outer/result` и техлога, это часть будущего `project-workspace.html`, срез 3)

```html
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes — быстрый чат</title>
<style>
  :root{
    --sky:#12172b; --sky-deep:#0c1020; --panel:#1a2038; --panel-2:#212949;
    --panel-line:#3c4568; --text:#f8f6ef; --text-dim:#aeb7dc; --gold:#f0bb5c;
    --violet:#ad9fe6; --teal:#7fc4b2; --dim-star:#727bab;
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0;height:100%}
  body{background:linear-gradient(180deg, var(--sky-deep), var(--sky) 45%);color:var(--text);font-family:Georgia,"Iowan Old Style",serif;height:100vh;display:flex;flex-direction:column}
  .topbar{display:flex;align-items:center;gap:16px;padding:16px 32px;border-bottom:1px solid var(--panel-line)}
  .topbar a{color:var(--text-dim);text-decoration:none;font-family:ui-monospace,Consolas,monospace;font-size:12px}
  .topbar .path{margin-left:auto;font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--dim-star)}
  .thread{flex:1;overflow-y:auto;padding:24px 32px;display:flex;flex-direction:column;gap:16px;max-width:760px;margin:0 auto;width:100%}
  .msg{padding:12px 16px;border-radius:12px;line-height:1.55;font-size:14.5px;white-space:pre-wrap}
  .msg.user{align-self:flex-end;background:var(--panel-2);border:1px solid var(--panel-line)}
  .msg.assistant{align-self:flex-start;background:var(--panel);border:1px solid var(--panel-line)}
  .composer{border-top:1px solid var(--panel-line);padding:18px 32px;display:flex;gap:12px;max-width:760px;margin:0 auto;width:100%}
  textarea{flex:1;resize:none;background:var(--sky-deep);border:1px solid var(--panel-line);border-radius:10px;color:var(--text);font-family:Georgia,serif;font-size:14px;padding:10px 13px;outline:none;min-height:44px}
  textarea:focus{border-color:var(--violet)}
  button{background:var(--gold);color:var(--sky-deep);border:none;border-radius:9px;padding:0 18px;cursor:pointer;font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
  button:disabled{opacity:.6;cursor:default}
</style>
</head>
<body>

<div class="topbar">
  <a href="home.html">← Hermes</a>
  <span class="path" id="projectPath"></span>
</div>

<div class="thread" id="thread"></div>

<div class="composer">
  <textarea id="textInput" placeholder="Написать Hermes…"></textarea>
  <button id="sendBtn">Отправить</button>
</div>

<script src="app.js"></script>
<script>
const chatSessionId = new URLSearchParams(location.search).get('id');
const threadEl = document.getElementById('thread');
const textInput = document.getElementById('textInput');
const sendBtn = document.getElementById('sendBtn');

function appendMessage(role, text) {
  const el = document.createElement('div');
  el.className = `msg ${role}`;
  el.textContent = text;
  threadEl.appendChild(el);
  threadEl.scrollTop = threadEl.scrollHeight;
  return el;
}

async function loadHistory() {
  const resp = await apiFetch(`/api/chat/${encodeURIComponent(chatSessionId)}/messages`);
  if (!resp.ok) return;
  const body = await resp.json();
  for (const m of body.data) {
    if (m.role === 'user' || m.role === 'assistant') appendMessage(m.role, m.content || '');
  }
}

async function send() {
  const text = textInput.value.trim();
  if (!text) return;
  textInput.value = '';
  sendBtn.disabled = true;
  appendMessage('user', text);
  const assistantEl = appendMessage('assistant', '');

  const resp = await apiFetch(`/api/chat/${encodeURIComponent(chatSessionId)}/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) {
    assistantEl.textContent = 'Hermes временно недоступен, попробуйте ещё раз';
    sendBtn.disabled = false;
    return;
  }
  await readSSE(resp, (name, payload) => {
    if (name === 'assistant.delta') assistantEl.textContent += payload.delta || '';
    else if (name === 'error') assistantEl.textContent = `Ошибка: ${payload.message || 'неизвестная'}`;
    threadEl.scrollTop = threadEl.scrollHeight;
  });
  sendBtn.disabled = false;
}

(async () => {
  const me = await requireAuth();
  if (!me) return;
  if (!chatSessionId) { location.href = 'home.html'; return; }
  document.getElementById('projectPath').textContent = chatSessionId;
  await loadHistory();
})();

sendBtn.addEventListener('click', send);
textInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
</script>
</body>
</html>
```

- [ ] **Step 5: Ручная проверка локально**

```bash
cd /home/deploy/hermes-cn-ru/hermes-web
API_SERVER_KEY=dummy HERMES_WEB_COOKIE_SECURE=false PROJECT_INDEX_PLUGIN_DIR=../hermes-plugins \
  /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3 run.py
```

В другом терминале: `curl -s localhost:8643/login.html | head -5` — должна вернуться разметка страницы входа. Остановить (`Ctrl+C`) после проверки — реального Hermes API server ещё нет по адресу `127.0.0.1:8642` на этой машине, поэтому дальше логина проверить локально нельзя (это будет сделано в приёмочном тесте Task 8 на реальном сервере).

- [ ] **Step 6: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/
git commit -m "feat(hermes-web): статика — login/home доработаны, новый минимальный chat.html"
```

---

## Task 8: Развёртывание на VPS и приёмочный тест

**Files:**
- Deploy (rsync, не git): `hermes-web/` → `hermes@212.115.55.116:~/hermes-web/`
- Modify (на сервере, не в этом репозитории, от `root`): установка Caddy, `Caddyfile`, `ufw`
- Modify (на сервере, от `hermes`): `~/.hermes/.env` (добавить `API_SERVER_KEY`), новый `hermes-web.service`
- Modify (в этом репозитории): `docs/state.md`, `docs/changelog.md`

**Interfaces:** нет новых — операционная задача поверх уже протестированного пакета Task 0-7.

- [ ] **Step 1: Включить Hermes API server — добавить `API_SERVER_KEY` в `.env`**

```bash
API_SERVER_KEY="$(openssl rand -hex 32)"
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 "cat >> ~/.hermes/.env << EOF

API_SERVER_KEY=${API_SERVER_KEY}
EOF"
echo "Сохранённый ключ (понадобится для systemd-юнита ниже): $API_SERVER_KEY"
```

Перезапустить гейтвей, чтобы платформа `api_server` поднялась:

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  systemctl --user restart hermes-gateway.service
  sleep 2
  systemctl --user status hermes-gateway.service --no-pager | head -5
'
```

Проверить, что API-сервер реально слушает `127.0.0.1:8642`:

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 \
  "curl -s http://127.0.0.1:8642/health"
```

Expected: `{"status": "ok", "platform": "hermes-agent", ...}`.

- [ ] **Step 2: Скопировать `hermes-web` на сервер (без `tests/`, `__pycache__`, `.db`)**

```bash
rsync -av --exclude='__pycache__' --exclude='*.pyc' --exclude='*.db' --exclude='tests' \
  /home/deploy/hermes-cn-ru/hermes-web/ \
  -e "ssh -i ~/.ssh/id_ed25519_hermes_user" \
  hermes@212.115.55.116:~/hermes-web/
```

- [ ] **Step 3: Поставить зависимости в venv Hermes и прогнать тесты реальным интерпретатором**

`aiohttp` уже установлен в этом венве (зависимость самого `hermes-agent`, версия 3.14.1 — та же, что запиновали локально в Task 0) — переустанавливать/пиновать его здесь не нужно и рискованно: это общий венв с самим гейтвеем, понижение версии могло бы что-то в нём сломать. Ставим только то, чего не хватает:

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  ~/.hermes/hermes-agent/venv/bin/pip install --quiet argon2-cffi==25.1.0 pytest==9.0.2 pytest-aiohttp==1.1.0
'
scp -i ~/.ssh/id_ed25519_hermes_user -r hermes-web/tests hermes@212.115.55.116:~/hermes-web/
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  cd ~/hermes-web && PROJECT_INDEX_PLUGIN_DIR=/home/hermes/.hermes/plugins \
  ~/.hermes/hermes-agent/venv/bin/python3.11 -m pytest tests/ -v
'
```

Expected: `33 passed` — тем же интерпретатором и версиями библиотек, что будут исполнять сервис в проде.

- [ ] **Step 4: `hermes-web.service` — systemd user-юнит под `hermes`**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/hermes-web.service << "EOF"
[Unit]
Description=Hermes Web — авторизация + Быстрый чат
After=network.target hermes-gateway.service

[Service]
WorkingDirectory=%h/hermes-web
EnvironmentFile=%h/.hermes/.env
Environment=PROJECT_INDEX_PLUGIN_DIR=%h/.hermes/plugins
Environment=HERMES_WEB_DB_PATH=%h/hermes-web/hermes-web.db
ExecStart=%h/.hermes/hermes-agent/venv/bin/python3.11 %h/hermes-web/run.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now hermes-web.service
sleep 2
systemctl --user status hermes-web.service --no-pager | head -8
'
```

Expected: `Active: active (running)`.

- [ ] **Step 5: Сидировать пользователей `dem` и `rost`**

Выполнять интерактивно по SSH (пароли задать самостоятельно при запуске, не в этом плане):

```bash
ssh -t -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  cd ~/hermes-web && \
  ~/.hermes/hermes-agent/venv/bin/python3.11 -m hermes_web.seed_users dem owner "Дмитрий" --db-path hermes-web.db
'
ssh -t -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  cd ~/hermes-web && \
  ~/.hermes/hermes-agent/venv/bin/python3.11 -m hermes_web.seed_users rost participant "Ростислав" --db-path hermes-web.db
'
```

- [ ] **Step 6: Установить Caddy и настроить реверс-прокси (от `root`)**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_vps root@212.115.55.116 '
  apt-get update -qq
  apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
  curl -1sLf "https://dl.cloudsmith.io/public/caddy/stable/gpg.key" | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf "https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt" > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -qq
  apt-get install -y -qq caddy
'
ssh -i ~/.ssh/id_ed25519_hermes_vps root@212.115.55.116 "cat > /etc/caddy/Caddyfile << 'EOF'
hermes.blackboxbegin.space {
    reverse_proxy 127.0.0.1:8643
}
EOF
systemctl reload caddy
systemctl status caddy --no-pager | head -6"
```

Expected: `Active: active (running)`, и через минуту-две Caddy сам получает сертификат Let's Encrypt.

- [ ] **Step 7: Включить минимальный firewall (от `root`)**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_vps root@212.115.55.116 '
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
  ufw status
'
```

Expected: `Status: active`, разрешены только `22`, `80`, `443`.

- [ ] **Step 8: Приёмочный тест — вход и «Быстрый чат» через реальный домен**

```bash
curl -s -c /tmp/hermes-web-cookies.txt -X POST https://hermes.blackboxbegin.space/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"dem","password":"<пароль, заданный в Step 5>"}'
```

Expected: `{"username": "dem", "role": "owner", "display_name": "Дмитрий"}`.

```bash
curl -s -b /tmp/hermes-web-cookies.txt -X POST https://hermes.blackboxbegin.space/api/quick-chat
```

Expected: `{"chat_session_id": "...", "project_path": "/home/hermes/workspace/dem/ALL/2026-..._chat-..."}`. Проверить на сервере:

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 \
  "cat ~/workspace/dem/ALL/2026-*_chat-*/about.md | tail -20"
```

Затем отправить сообщение (заменить `<chat_session_id>` на значение из предыдущего ответа):

```bash
curl -s -b /tmp/hermes-web-cookies.txt -X POST \
  https://hermes.blackboxbegin.space/api/chat/<chat_session_id>/send \
  -H 'Content-Type: application/json' \
  -d '{"text":"Привет! Просто проверка, что чат работает."}'
```

Expected: поток `event: assistant.delta ...` строк, завершающийся `event: done`. Если агент реально ответил — приёмка пройдена. Если что-то ведёт себя не так (агент не отвечает, SSE обрывается) — применить systematic-debugging, начиная с `journalctl --user -u hermes-web.service -n 50` и `journalctl --user -u hermes-gateway.service -n 50` на сервере.

- [ ] **Step 9: Удалить тестовый проект после приёмки**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  rm -rf ~/workspace/dem/ALL/2026-*_chat-*
'
rm -f /tmp/hermes-web-cookies.txt
```

(Соответствующую строку из `hermes-web.db`/`project_index.db` можно оставить — это тестовые данные малого объёма, не мешают; при желании почистить так же, как в приёмке `project_index`, через `sqlite3`/`python3 -c`.)

- [ ] **Step 10: Обновить `docs/state.md` и `docs/changelog.md`**

В `state.md`: отметить срез 1+2 под-проекта B («авторизация + Быстрый чат») как выполненный, со ссылкой на этот план и итог приёмочного теста; следующий шаг — срез 3 (Группы/Проекты).

В `changelog.md`: новая запись за дату выполнения — что реализовано (`hermes-web`, включение `api_server` платформы Hermes, Caddy на `hermes.blackboxbegin.space`, `ufw`), что проверено (реальный вход + сообщение агенту через домен).

- [ ] **Step 11: Commit и snapshot**

```bash
cd /home/deploy/hermes-cn-ru
git add docs/state.md docs/changelog.md
bash scripts/snapshot.sh "hermes-web: авторизация + Быстрый чат реализованы и выкачены на hermes.blackboxbegin.space — приёмочный тест пройден"
```

---

## Self-Review (сверка со спеком)

- Архитектура (Caddy → hermes-web:8643 → Hermes API :8642) — покрыто (Task 8, Steps 1/6/7).
- Модель данных `users`/`web_sessions`/`chat_sessions` — покрыто (Task 1).
- Аутентификация: argon2, куки-сессии не-JWT, логаут мгновенно отзывает, rate limit 5/5мин, одно сообщение об ошибке на неверный логин/пароль, роль в ответе — покрыто (Task 2, Task 5).
- Сиды пользователей без UI — покрыто (Task 6, Task 8 Step 5).
- «Быстрый чат»: проект в `ALL`, placeholder `about.md`, `project_index.core.index_update` напрямую, Hermes-сессия, `ephemeral`/`system_message` с `project_path`, SSE 1:1 в браузер, история через `/api/sessions/{id}/messages` — покрыто (Task 4, Task 5, Task 7).
- Обработка ошибок (Hermes недоступен, wormsoft недоступен, неверный логин, истёкшая кука, гонка при создании проекта) — покрыто (Task 4/`QuickChatError`, Task 5 try/except в `handle_send_message`, Task 1 `web_sessions` TTL).
- Тестирование: pytest + замоканный Hermes API, тесты аутентификации, ручной приёмочный тест на реальном домене — покрыто (Task 1-6 юнит-тесты, Task 8 Step 8).
- Деплой: `.env`/`API_SERVER_KEY`, `hermes-web.service`, Caddy + Let's Encrypt, `ufw` — покрыто (Task 8).
- «Вне рамок» спека (Группы/Проекты, админка, `project-workspace.html` целиком, Android) — сознательно не тронуто ни одной задачей этого плана.
