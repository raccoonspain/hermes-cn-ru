# Админ-панель (под-проект C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать экран `admin.html` (метрики VPS, CRUD пользователей,
журнал событий) поверх существующего `hermes-web`, по согласованному
спеку `docs/superpowers/specs/2026-08-02-admin-panel-design.md`.

**Architecture:** Новая таблица `events` + пять новых функций в
`storage.py`; новый stdlib-модуль `admin_metrics.py` для CPU/RAM/диска;
шесть новых `/api/admin/*` эндпоинтов в `app.py` за проверкой
`role == "owner"`; вызовы `storage.log_event` вживлены в уже
существующие точки успеха (`handle_login`, `handle_create_project`,
`handle_delete_project`, `quickchat.create_quick_chat`,
`quickchat.get_or_open_session`); `admin.html`/`home.html` переведены с
демо-данных макета на реальные `fetch`-вызовы, по образцу
`project-selector.html`.

**Tech Stack:** Python 3 / aiohttp / SQLite (как весь `hermes-web`),
ванильный JS без сборщика на фронтенде, только stdlib (`/proc`,
`shutil`) для метрик — новых pip-зависимостей нет.

## Global Constraints

- Доступ ко всем `/api/admin/*` — только `role == "owner"` (403 для
  `participant`, 401 для неавторизованных).
- Никаких новых Python-зависимостей — метрики VPS через stdlib
  (`/proc/stat`, `/proc/meminfo`, `shutil.disk_usage`), без `psutil`.
- `username` — неизменяемый идентификатор (primary key в БД + имя папки
  на диске в `workspace/<username>/...`). Ни один эндпоинт не
  переименовывает пользователя — редактируется только `display_name` и
  `role`.
- Валидация нового логина при создании: `^[a-z0-9_-]{2,32}$`, 400 при
  несовпадении.
- Роль — только `"owner"` или `"participant"`, 400 на что угодно ещё.
- Владелец не может понизить роль **самому себе** через
  `POST /api/admin/users/{username}` (400) — смена роли/данных любого
  другого пользователя не ограничена.
- Журнал событий (`events`) логирует только крупные действия: `login`,
  `project.create`, `project.delete`, `chat.start`, `user.create`,
  `user.update`, `user.reset_password`. Никаких файловых операций и
  отдельных сообщений чата.
- Пароль (создание и сброс) — администратор вводит его сам в поле формы,
  без автогенерации.
- Карточки «Кредиты wormsoft.ru» / rate limit — не реализуются в этом
  срезе (у wormsoft.ru нет публичного API для этих цифр — проверено
  эмпирически 2026-08-02, см. спек).
- Удаление пользователя не реализуется (не было на макете).
- Каждый вызов `storage.log_event` — сразу ПОСЛЕ успешного завершения
  основного действия, не до.

---

### Task 1: Хранилище — таблица `events`, CRUD пользователей, счётчик сессий

**Files:**
- Modify: `hermes-web/hermes_web/storage.py`
- Test: `hermes-web/tests/test_storage.py`

**Interfaces:**
- Produces:
  - `list_users(conn) -> list[dict]` — каждый dict: `username`, `role`,
    `display_name` (без `password_hash`).
  - `update_user(conn, username: str, display_name: str, role: str) -> None`
  - `update_user_password(conn, username: str, password_hash: str) -> None`
  - `count_active_sessions(conn, now: float) -> dict` — `{"sessions": int, "users": int}`.
  - `get_last_activity(conn, user: str) -> Optional[float]` — `MAX(COALESCE(last_message_at, created_at))` по `chat_sessions` этого `user`, `None` если сессий нет.
  - `log_event(conn, actor: str, verb: str, detail: str = "") -> None`
  - `list_events(conn, limit: int = 50) -> list[dict]` — новые сверху, каждый dict: `ts`, `actor`, `verb`, `detail`.
  - Таблица `events(id, ts, actor, verb, detail)`, создаётся в `init_db`.

- [ ] **Step 1: Добавить таблицу `events` в `init_db`**

В `hermes-web/hermes_web/storage.py`, сразу после блока `group_meta` (после закрывающей `)` его `conn.execute(...)`, перед `conn.commit()` в конце `init_db`):

```python
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            actor TEXT NOT NULL,
            verb TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
        )
        """
    )
```

- [ ] **Step 2: Написать падающие тесты для новых функций**

Добавить в `hermes-web/tests/test_storage.py`:

```python
def test_list_users_returns_all_without_password_hash(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_user(conn, "dem", "hash1", "owner", "Дмитрий")
    storage.create_user(conn, "rost", "hash2", "participant", "Ростислав")
    users = storage.list_users(conn)
    assert {u["username"] for u in users} == {"dem", "rost"}
    dem = next(u for u in users if u["username"] == "dem")
    assert dem == {"username": "dem", "role": "owner", "display_name": "Дмитрий"}


def test_update_user_changes_display_name_and_role(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_user(conn, "rost", "hash2", "participant", "Ростислав")
    storage.update_user(conn, "rost", "Ростислав Н.", "owner")
    row = storage.get_user(conn, "rost")
    assert row["display_name"] == "Ростислав Н."
    assert row["role"] == "owner"
    assert row["username"] == "rost"


def test_update_user_password_changes_hash(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_user(conn, "dem", "oldhash", "owner", "Дмитрий")
    storage.update_user_password(conn, "dem", "newhash")
    row = storage.get_user(conn, "dem")
    assert row["password_hash"] == "newhash"


def test_count_active_sessions_counts_unexpired_only(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_web_session(conn, "tok1", "dem", expires_at=1000.0)
    storage.create_web_session(conn, "tok2", "dem", expires_at=1000.0)
    storage.create_web_session(conn, "tok3", "rost", expires_at=1000.0)
    storage.create_web_session(conn, "tok4", "rost", expires_at=10.0)  # уже истёк
    result = storage.count_active_sessions(conn, now=500.0)
    assert result == {"sessions": 3, "users": 2}


def test_get_last_activity_prefers_last_message_at_over_created_at(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/p/a", "web_1", created_at=100.0)
    storage.touch_chat_session(conn, "chat1", last_message_at=250.0)
    assert storage.get_last_activity(conn, "dem") == 250.0


def test_get_last_activity_falls_back_to_created_at_without_messages(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/p/a", "web_1", created_at=100.0)
    assert storage.get_last_activity(conn, "dem") == 100.0


def test_get_last_activity_returns_none_without_sessions(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    assert storage.get_last_activity(conn, "dem") is None


def test_log_event_and_list_events_newest_first(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.log_event(conn, "dem", "login", "")
    storage.log_event(conn, "dem", "project.create", "ALL/2026-08-02_x")
    events = storage.list_events(conn)
    assert [e["verb"] for e in events] == ["project.create", "login"]
    assert events[0]["actor"] == "dem"
    assert events[0]["detail"] == "ALL/2026-08-02_x"


def test_list_events_respects_limit(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    for i in range(5):
        storage.log_event(conn, "dem", "login", str(i))
    events = storage.list_events(conn, limit=2)
    assert len(events) == 2
    assert events[0]["detail"] == "4"
```

- [ ] **Step 3: Запустить тесты, убедиться что падают**

Run: `pytest tests/test_storage.py -v` (из `hermes-web/`)
Expected: FAIL — `AttributeError: module 'hermes_web.storage' has no attribute 'list_users'` (и аналогично для остальных новых функций).

- [ ] **Step 4: Реализовать новые функции**

Добавить в конец `hermes-web/hermes_web/storage.py`:

```python
def list_users(conn: sqlite3.Connection) -> list:
    rows = conn.execute("SELECT username, role, display_name FROM users ORDER BY username").fetchall()
    return [dict(row) for row in rows]


def update_user(conn: sqlite3.Connection, username: str, display_name: str, role: str) -> None:
    conn.execute(
        "UPDATE users SET display_name = ?, role = ? WHERE username = ?",
        (display_name, role, username),
    )
    conn.commit()


def update_user_password(conn: sqlite3.Connection, username: str, password_hash: str) -> None:
    conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, username))
    conn.commit()


def count_active_sessions(conn: sqlite3.Connection, now: float) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS sessions, COUNT(DISTINCT username) AS users FROM web_sessions WHERE expires_at > ?",
        (now,),
    ).fetchone()
    return {"sessions": row["sessions"], "users": row["users"]}


def get_last_activity(conn: sqlite3.Connection, user: str) -> Optional[float]:
    row = conn.execute(
        "SELECT MAX(COALESCE(last_message_at, created_at)) AS last_active FROM chat_sessions WHERE user = ?",
        (user,),
    ).fetchone()
    return row["last_active"]


def log_event(conn: sqlite3.Connection, actor: str, verb: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO events (ts, actor, verb, detail) VALUES (?, ?, ?, ?)",
        (time.time(), actor, verb, detail),
    )
    conn.commit()


def list_events(conn: sqlite3.Connection, limit: int = 50) -> list:
    rows = conn.execute(
        "SELECT ts, actor, verb, detail FROM events ORDER BY id DESC LIMIT ?", (limit,),
    ).fetchall()
    return [dict(row) for row in rows]
```

`log_event` использует `time.time()` — добавить `import time` в начало
файла (сейчас там только `import sqlite3` и `from pathlib import Path` /
`from typing import Optional`):

```python
import sqlite3
import time
from pathlib import Path
from typing import Optional
```

- [ ] **Step 5: Запустить тесты, убедиться что проходят**

Run: `pytest tests/test_storage.py -v`
Expected: PASS, все тесты файла (старые + новые) зелёные.

- [ ] **Step 6: Commit**

```bash
git add hermes-web/hermes_web/storage.py hermes-web/tests/test_storage.py
git commit -m "feat(hermes-web): events-таблица, CRUD пользователей и счётчик сессий в storage"
```

---

### Task 2: Метрики VPS (CPU/RAM/диск) без новых зависимостей

**Files:**
- Create: `hermes-web/hermes_web/admin_metrics.py`
- Test: `hermes-web/tests/test_admin_metrics.py`

**Interfaces:**
- Produces:
  - `read_cpu_times(stat_path: str = "/proc/stat") -> tuple[int, int]` — `(idle, total)`.
  - `compute_cpu_percent(idle_before: int, total_before: int, idle_after: int, total_after: int) -> float`
  - `async cpu_percent(stat_path: str = "/proc/stat", sample_interval: float = 0.1) -> float`
  - `ram_usage(meminfo_path: str = "/proc/meminfo") -> dict` — `{"used_bytes": int, "total_bytes": int}`.
  - `disk_usage(path: str) -> dict` — `{"used_bytes": int, "total_bytes": int, "path": str}`.
- Consumes: ничего из предыдущих задач — независимый модуль.

- [ ] **Step 1: Написать падающие тесты**

Создать `hermes-web/tests/test_admin_metrics.py`:

```python
import pytest

from hermes_web import admin_metrics


def test_read_cpu_times_parses_proc_stat_line(tmp_path):
    stat_path = tmp_path / "stat"
    stat_path.write_text(
        "cpu  100 0 50 800 10 0 0 0 0 0\n"
        "cpu0 100 0 50 800 10 0 0 0 0 0\n"
    )
    idle, total = admin_metrics.read_cpu_times(str(stat_path))
    # idle = idle-поле (800) + iowait (10)
    assert idle == 810
    assert total == 100 + 0 + 50 + 800 + 10


def test_compute_cpu_percent_from_deltas():
    result = admin_metrics.compute_cpu_percent(
        idle_before=100, total_before=1000, idle_after=150, total_after=1100,
    )
    assert result == 50.0


def test_compute_cpu_percent_zero_total_delta_returns_zero():
    result = admin_metrics.compute_cpu_percent(
        idle_before=100, total_before=1000, idle_after=100, total_after=1000,
    )
    assert result == 0.0


@pytest.mark.asyncio
async def test_cpu_percent_samples_twice_and_computes_percentage(monkeypatch):
    samples = iter([(800, 1000), (850, 1100)])
    monkeypatch.setattr(admin_metrics, "read_cpu_times", lambda stat_path="/proc/stat": next(samples))

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(admin_metrics.asyncio, "sleep", fake_sleep)
    result = await admin_metrics.cpu_percent()
    assert result == 50.0


def test_ram_usage_parses_proc_meminfo(tmp_path):
    meminfo_path = tmp_path / "meminfo"
    meminfo_path.write_text(
        "MemTotal:        8388608 kB\n"
        "MemFree:          200000 kB\n"
        "MemAvailable:    3000000 kB\n"
        "Buffers:           50000 kB\n"
    )
    result = admin_metrics.ram_usage(str(meminfo_path))
    assert result == {
        "used_bytes": (8388608 - 3000000) * 1024,
        "total_bytes": 8388608 * 1024,
    }


def test_disk_usage_returns_used_and_total_for_real_path(tmp_path):
    result = admin_metrics.disk_usage(str(tmp_path))
    assert result["path"] == str(tmp_path)
    assert result["total_bytes"] > 0
    assert 0 <= result["used_bytes"] <= result["total_bytes"]
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `pytest tests/test_admin_metrics.py -v` (из `hermes-web/`)
Expected: FAIL — `ModuleNotFoundError: No module named 'hermes_web.admin_metrics'`.

- [ ] **Step 3: Реализовать `admin_metrics.py`**

Создать `hermes-web/hermes_web/admin_metrics.py`:

```python
"""Метрики VPS для /api/admin/overview — только stdlib (/proc, shutil),
без psutil: в проекте нет requirements.txt, пакеты в venv ставятся
вручную, лишнюю зависимость заводить не хочется без нужды."""
from __future__ import annotations

import asyncio
import shutil


def read_cpu_times(stat_path: str = "/proc/stat") -> tuple:
    with open(stat_path, "r", encoding="utf-8") as fh:
        first_line = fh.readline()
    values = [int(v) for v in first_line.split()[1:]]
    # /proc/stat cpu-строка: user nice system idle iowait irq softirq steal guest guest_nice
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return idle, total


def compute_cpu_percent(idle_before: int, total_before: int, idle_after: int, total_after: int) -> float:
    idle_delta = idle_after - idle_before
    total_delta = total_after - total_before
    if total_delta <= 0:
        return 0.0
    return round((1 - idle_delta / total_delta) * 100, 1)


async def cpu_percent(stat_path: str = "/proc/stat", sample_interval: float = 0.1) -> float:
    idle1, total1 = read_cpu_times(stat_path)
    await asyncio.sleep(sample_interval)
    idle2, total2 = read_cpu_times(stat_path)
    return compute_cpu_percent(idle1, total1, idle2, total2)


def ram_usage(meminfo_path: str = "/proc/meminfo") -> dict:
    values = {}
    with open(meminfo_path, "r", encoding="utf-8") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                values[key] = int(rest.strip().split()[0]) * 1024  # kB -> bytes
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    return {"used_bytes": total - available, "total_bytes": total}


def disk_usage(path: str) -> dict:
    usage = shutil.disk_usage(path)
    return {"used_bytes": usage.used, "total_bytes": usage.total, "path": path}
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `pytest tests/test_admin_metrics.py -v`
Expected: PASS, все 7 тестов зелёные.

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/admin_metrics.py hermes-web/tests/test_admin_metrics.py
git commit -m "feat(hermes-web): метрики CPU/RAM/диска через stdlib для админ-панели"
```

---

### Task 3: Логирование крупных событий в существующих точках успеха

**Files:**
- Modify: `hermes-web/hermes_web/app.py` (`handle_login`, `handle_create_project`, `handle_delete_project`)
- Modify: `hermes-web/hermes_web/quickchat.py` (`create_quick_chat`, `get_or_open_session`)
- Test: `hermes-web/tests/test_quickchat.py`, `hermes-web/tests/test_app.py`

**Interfaces:**
- Consumes: `storage.log_event(conn, actor, verb, detail="")` из Task 1.
- Produces: ничего нового для последующих задач — это точки записи,
  Task 4 их только читает через `storage.list_events`.

- [ ] **Step 1: Написать падающие тесты в `test_quickchat.py`**

Добавить в `hermes-web/tests/test_quickchat.py` (рядом с
`test_create_quick_chat_creates_project_and_hermes_session`):

```python
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
```

Добавить в `hermes-web/tests/test_quickchat.py` рядом с
`test_get_or_open_session_creates_new_session_for_existing_project`
(нужно посмотреть, как та тестовая функция готовит существующий проект —
`_config`, создание `about.md` через `create_project`, и переиспользовать
тот же паттерн подготовки):

```python
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
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `pytest tests/test_quickchat.py -k "logs_chat_start" -v` (из `hermes-web/`)
Expected: FAIL — `assert 0 == 1` (список `events` пуст, `log_event` ещё
не вызывается).

- [ ] **Step 3: Вживить `log_event` в `quickchat.py`**

В `hermes-web/hermes_web/quickchat.py`, функция `create_quick_chat` —
после `storage.create_chat_session(...)` (текущие строки 247-250), перед
`return`:

```python
    chat_session_id = uuid.uuid4().hex
    storage.create_chat_session(
        db_conn, chat_session_id, user, index_result["path"], hermes_session_id, created_at=time.time(),
    )
    storage.log_event(db_conn, user, "chat.start", index_result["path"])

    return {
        "chat_session_id": chat_session_id,
        "project_path": index_result["path"],
        "hermes_session_id": hermes_session_id,
    }
```

В той же функции `get_or_open_session` — после `storage.create_chat_session(...)`
в ветке НОВОЙ сессии (текущие строки 274-277; ветка переиспользования
существующей сессии, которая заканчивается на `return {...}` строкой
выше, не трогается):

```python
    hermes_session_id = await _new_hermes_session(http_session, config)
    chat_session_id = uuid.uuid4().hex
    storage.create_chat_session(db_conn, chat_session_id, user, resolved, hermes_session_id, created_at=time.time())
    storage.log_event(db_conn, user, "chat.start", resolved)
    return {"chat_session_id": chat_session_id, "project_path": resolved, "hermes_session_id": hermes_session_id}
```

- [ ] **Step 4: Запустить тесты quickchat, убедиться что проходят**

Run: `pytest tests/test_quickchat.py -v`
Expected: PASS, весь файл зелёный (старые + 2 новых теста).

- [ ] **Step 5: Написать падающие тесты в `test_app.py`**

Добавить в `hermes-web/tests/test_app.py`:

```python
@pytest.mark.asyncio
async def test_login_success_logs_event(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    events = storage.list_events(app_and_conn["db"])
    assert len(events) == 1
    assert events[0] == {"ts": events[0]["ts"], "actor": "dem", "verb": "login", "detail": ""}


@pytest.mark.asyncio
async def test_create_project_logs_event(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_create_project(db_conn, config, user, group, title):
        return {"project_path": "/w/dem/ALL/новая-тема", "group": group}

    monkeypatch.setattr("hermes_web.app.quickchat.create_project", fake_create_project)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects", json={"group": "ALL", "title": "Новая тема"})
    assert resp.status == 200

    events = [e for e in storage.list_events(app_and_conn["db"]) if e["verb"] == "project.create"]
    assert len(events) == 1
    assert events[0]["actor"] == "dem"
    assert events[0]["detail"] == "/w/dem/ALL/новая-тема"


@pytest.mark.asyncio
async def test_delete_project_logs_event(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_delete_project(user, path, config, db_conn):
        return {"old_path": path, "trashed_path": path + ".trash"}

    monkeypatch.setattr("hermes_web.app.projects.delete_project", fake_delete_project)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/delete", json={"path": "/w/dem/ALL/x"})
    assert resp.status == 200

    events = [e for e in storage.list_events(app_and_conn["db"]) if e["verb"] == "project.delete"]
    assert len(events) == 1
    assert events[0]["actor"] == "dem"
    assert events[0]["detail"] == "/w/dem/ALL/x"
```

`storage` уже импортирован в `test_app.py` (см. текущий импорт `from
hermes_web import auth, hermes_client, projects, quickchat, storage`).

- [ ] **Step 6: Запустить тесты, убедиться что падают**

Run: `pytest tests/test_app.py -k "logs_event" -v`
Expected: FAIL — списки `events` пустые.

- [ ] **Step 7: Вживить `log_event` в `app.py`**

В `hermes_web/app.py`, `handle_login` — после
`storage.create_web_session(...)` (текущая строка 69), перед
построением `response`:

```python
    token = auth.generate_session_token()
    storage.create_web_session(request.app["db"], token, username, expires_at=time.time() + SESSION_TTL_SECONDS)
    storage.log_event(request.app["db"], user_row["username"], "login", "")
```

`handle_create_project` — после успешного `quickchat.create_project(...)`
(текущие строки 236-239), перед `return`:

```python
    try:
        result = await quickchat.create_project(request.app["db"], request.app["quickchat_config"], user["username"], group, title)
    except quickchat.QuickChatError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    storage.log_event(request.app["db"], user["username"], "project.create", result["project_path"])
    return web.json_response(result)
```

`handle_delete_project` — после успешного `projects.delete_project(...)`
(текущие строки 299-302), перед `return`:

```python
    try:
        result = await projects.delete_project(user["username"], path, request.app["quickchat_config"], request.app["db"])
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    storage.log_event(request.app["db"], user["username"], "project.delete", result["old_path"])
    return web.json_response(result)
```

- [ ] **Step 8: Запустить тесты, убедиться что проходят**

Run: `pytest tests/test_app.py tests/test_quickchat.py -v`
Expected: PASS, оба файла целиком зелёные.

- [ ] **Step 9: Commit**

```bash
git add hermes-web/hermes_web/app.py hermes-web/hermes_web/quickchat.py hermes-web/tests/test_app.py hermes-web/tests/test_quickchat.py
git commit -m "feat(hermes-web): логировать вход/создание и удаление проекта/старт чата в events"
```

---

### Task 4: `/api/admin/*` — обзор, пользователи, журнал

**Files:**
- Modify: `hermes-web/hermes_web/app.py`
- Modify: `hermes-web/hermes_web/projects.py`
- Test: `hermes-web/tests/test_admin.py` (новый файл)
- Test: `hermes-web/tests/test_projects.py`

**Interfaces:**
- Consumes: `storage.list_users/update_user/update_user_password/
  count_active_sessions/get_last_activity/log_event/list_events` (Task 1),
  `admin_metrics.cpu_percent/ram_usage/disk_usage` (Task 2).
- Produces: `projects.count_projects(user: str, config) -> int` — считает
  проекты пользователя во всех группах и статусах разом (без фильтров),
  инкапсулирует `_workspace_kwargs` внутри `projects.py` вместо того,
  чтобы `app.py` дотягивался до приватного хелпера другого модуля (в
  кодовой базе так уже сделано для `workspace.py` — у него свой
  дублированный `_project_index_kwargs`, а не импорт из `projects.py`).
- Produces: маршруты `GET /api/admin/overview`, `GET /api/admin/users`,
  `POST /api/admin/users`, `POST /api/admin/users/{username}`,
  `POST /api/admin/users/{username}/reset-password`,
  `GET /api/admin/events` — контракты см. в шагах ниже. Task 5 их
  потребляет с фронтенда.

- [ ] **Step 1: Написать падающий тест для `projects.count_projects`**

Добавить в `hermes-web/tests/test_projects.py`:

```python
def test_count_projects_returns_zero_for_user_without_projects(tmp_path):
    config = _config(tmp_path)
    assert projects.count_projects("dem", config) == 0
```

(если в файле уже есть локальный хелпер `_config(tmp_path)`, использовать
его; если модуль импортирован как `from hermes_web import projects`,
оставить как есть — сигнатура нового вызова не зависит от остального
файла.)

Run: `pytest tests/test_projects.py -k count_projects -v` (из `hermes-web/`)
Expected: FAIL — `AttributeError: module 'hermes_web.projects' has no attribute 'count_projects'`.

- [ ] **Step 2: Реализовать `projects.count_projects`**

Добавить в конец `hermes-web/hermes_web/projects.py`:

```python
def count_projects(user: str, config) -> int:
    return len(project_index_core.list_projects_for_user(user, **_workspace_kwargs(config)))
```

Run: `pytest tests/test_projects.py -k count_projects -v`
Expected: PASS.

- [ ] **Step 3: Написать падающие тесты для `/api/admin/*`**

Создать `hermes-web/tests/test_admin.py`:

```python
import pytest

from hermes_web import auth, quickchat, storage
from hermes_web.app import create_app


@pytest.fixture
def app_and_conn(tmp_path):
    db_path = str(tmp_path / "hermes-web.db")
    conn = storage.get_connection(db_path)
    storage.create_user(conn, "dem", auth.hash_password("secret123"), "owner", "Дмитрий")
    storage.create_user(conn, "rost", auth.hash_password("secret456"), "participant", "Ростислав")
    conn.close()

    config = quickchat.Config(
        hermes_base_url="http://fake-hermes.invalid",
        hermes_api_key="fake-key",
        workspace_root=str(tmp_path / "workspace"),
        project_index_db_path=str(tmp_path / "project_index.db"),
    )
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    app = create_app(db_path=db_path, quickchat_config=config, cookie_secure=False, static_dir=str(static_dir))
    return app


async def _login(client, username, password):
    resp = await client.post("/login", json={"username": username, "password": password})
    assert resp.status == 200


@pytest.mark.asyncio
async def test_overview_requires_auth(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.get("/api/admin/overview")
    assert resp.status == 401


@pytest.mark.asyncio
async def test_overview_requires_owner_role(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "rost", "secret456")
    resp = await client.get("/api/admin/overview")
    assert resp.status == 403


@pytest.mark.asyncio
async def test_overview_returns_metrics_for_owner(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.get("/api/admin/overview")
    assert resp.status == 200
    body = await resp.json()
    assert isinstance(body["cpu_percent"], (int, float))
    assert set(body["ram"]) == {"used_bytes", "total_bytes"}
    assert set(body["disk"]) == {"used_bytes", "total_bytes", "path"}
    assert body["active_sessions"] >= 1
    assert body["active_users"] >= 1


@pytest.mark.asyncio
async def test_list_users_requires_owner_role(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "rost", "secret456")
    resp = await client.get("/api/admin/users")
    assert resp.status == 403


@pytest.mark.asyncio
async def test_list_users_returns_all_with_counts(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.get("/api/admin/users")
    assert resp.status == 200
    body = await resp.json()
    usernames = {u["username"] for u in body["users"]}
    assert usernames == {"dem", "rost"}
    dem = next(u for u in body["users"] if u["username"] == "dem")
    assert dem["display_name"] == "Дмитрий"
    assert dem["role"] == "owner"
    assert dem["project_count"] == 0
    assert dem["last_active"] is None


@pytest.mark.asyncio
async def test_create_user_success(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users", json={
        "username": "gleb", "display_name": "Глеб", "role": "participant", "password": "newpass1",
    })
    assert resp.status == 200
    row = storage.get_user(app_and_conn["db"], "gleb")
    assert row["display_name"] == "Глеб"
    assert row["role"] == "participant"
    assert auth.verify_password("newpass1", row["password_hash"])


@pytest.mark.asyncio
async def test_create_user_rejects_invalid_username(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users", json={
        "username": "Bad Name!", "display_name": "X", "role": "participant", "password": "pass1234",
    })
    assert resp.status == 400


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_username(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users", json={
        "username": "dem", "display_name": "X", "role": "participant", "password": "pass1234",
    })
    assert resp.status == 409


@pytest.mark.asyncio
async def test_create_user_rejects_invalid_role(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users", json={
        "username": "gleb", "display_name": "Глеб", "role": "admin", "password": "pass1234",
    })
    assert resp.status == 400


@pytest.mark.asyncio
async def test_update_user_changes_name_and_role(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users/rost", json={"display_name": "Ростислав Н.", "role": "owner"})
    assert resp.status == 200
    row = storage.get_user(app_and_conn["db"], "rost")
    assert row["display_name"] == "Ростислав Н."
    assert row["role"] == "owner"


@pytest.mark.asyncio
async def test_update_user_unknown_returns_404(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users/nobody", json={"display_name": "X", "role": "participant"})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_update_user_cannot_demote_self(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users/dem", json={"display_name": "Дмитрий", "role": "participant"})
    assert resp.status == 400
    row = storage.get_user(app_and_conn["db"], "dem")
    assert row["role"] == "owner"


@pytest.mark.asyncio
async def test_reset_password_updates_hash(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users/rost/reset-password", json={"password": "brandnew1"})
    assert resp.status == 200
    row = storage.get_user(app_and_conn["db"], "rost")
    assert auth.verify_password("brandnew1", row["password_hash"])
    assert not auth.verify_password("secret456", row["password_hash"])


@pytest.mark.asyncio
async def test_reset_password_unknown_user_404(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.post("/api/admin/users/nobody/reset-password", json={"password": "brandnew1"})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_events_requires_owner_role(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    await _login(client, "rost", "secret456")
    resp = await client.get("/api/admin/events")
    assert resp.status == 403


@pytest.mark.asyncio
async def test_events_returns_newest_first(aiohttp_client, app_and_conn):
    storage.log_event(app_and_conn["db"], "dem", "login", "")
    storage.log_event(app_and_conn["db"], "dem", "project.create", "ALL/x")

    client = await aiohttp_client(app_and_conn)
    await _login(client, "dem", "secret123")
    resp = await client.get("/api/admin/events")
    assert resp.status == 200
    body = await resp.json()
    verbs = [e["verb"] for e in body["events"]]
    assert verbs[0] == "login"  # логин ИЗ ЭТОГО ЖЕ теста (_login) залогировался последним
    assert "project.create" in verbs
```

- [ ] **Step 4: Запустить тесты, убедиться что падают**

Run: `pytest tests/test_admin.py -v` (из `hermes-web/`)
Expected: FAIL — `404 Not Found` на всех запросах (маршруты `/api/admin/*`
ещё не зарегистрированы).

- [ ] **Step 5: Добавить `_require_owner` и обработчики в `app.py`**

Добавить `import re` в блок импортов вверху `hermes_web/app.py` (сейчас
там `import asyncio`, `import json`, `import os`, `import time`,
`import urllib.parse`):

```python
import asyncio
import json
import os
import re
import time
import urllib.parse
```

Добавить `admin_metrics` в импорт модулей пакета:

```python
from . import admin_metrics, auth, hermes_client, projects, quickchat, storage, workspace
```

После функции `_require_user` (текущие строки 30-34) добавить:

```python
USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")


def _require_owner(request: web.Request) -> dict:
    user = _require_user(request)
    if user["role"] != "owner":
        raise web.HTTPForbidden(text=json.dumps({"error": "forbidden"}), content_type="application/json")
    return user
```

В конец файла, перед `async def _on_startup(...)`, добавить шесть новых
хендлеров:

```python
async def handle_admin_overview(request: web.Request) -> web.Response:
    _require_owner(request)
    config = request.app["quickchat_config"]
    workspace_root = config.workspace_root or projects.project_index_core.WORKSPACE_ROOT
    cpu = await admin_metrics.cpu_percent()
    ram = admin_metrics.ram_usage()
    disk = admin_metrics.disk_usage(workspace_root)
    active = storage.count_active_sessions(request.app["db"], now=time.time())
    return web.json_response({
        "cpu_percent": cpu,
        "ram": ram,
        "disk": disk,
        "active_sessions": active["sessions"],
        "active_users": active["users"],
    })


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
```

В `create_app`, после блока с `/api/projects/*` маршрутами и перед
`app.router.add_get("/", handle_root)`, зарегистрировать новые маршруты:

```python
    app.router.add_get("/api/admin/overview", handle_admin_overview)
    app.router.add_get("/api/admin/users", handle_admin_list_users)
    app.router.add_post("/api/admin/users", handle_admin_create_user)
    app.router.add_post("/api/admin/users/{username}", handle_admin_update_user)
    app.router.add_post("/api/admin/users/{username}/reset-password", handle_admin_reset_password)
    app.router.add_get("/api/admin/events", handle_admin_events)
    app.router.add_get("/", handle_root)
```

- [ ] **Step 6: Запустить тесты, убедиться что проходят**

Run: `pytest tests/test_admin.py -v`
Expected: PASS, все тесты файла зелёные.

- [ ] **Step 7: Прогнать весь backend-набор**

Run: `pytest -v` (из `hermes-web/`)
Expected: PASS, весь набор целиком (старые тесты + все добавленные в
Task 1-4), без регрессий.

- [ ] **Step 8: Commit**

```bash
git add hermes-web/hermes_web/app.py hermes-web/hermes_web/projects.py hermes-web/tests/test_admin.py hermes-web/tests/test_projects.py
git commit -m "feat(hermes-web): API-эндпоинты /api/admin/* — обзор, пользователи, журнал"
```

---

### Task 5: Фронтенд — `admin.html` на реальных данных, разблокировка ссылки в `home.html`

**Files:**
- Modify: `hermes-web/static/admin.html`
- Modify: `hermes-web/static/home.html`

**Interfaces:**
- Consumes: `/api/admin/overview`, `/api/admin/users`, `POST
  /api/admin/users`, `POST /api/admin/users/{username}`, `POST
  /api/admin/users/{username}/reset-password`, `/api/admin/events` (Task 4);
  `apiFetch`/`requireAuth`/`logout` из `hermes-web/static/app.js`
  (уже существуют, без изменений).
- Produces: ничего для дальнейших задач — конечная задача плана.

Копию текущего `hermes-web/static/admin.html` (кликабельный макет,
условные данные) уже прочитали — далее редактируем именно её.

- [ ] **Step 1: Убрать карточки «Кредиты wormsoft.ru» и «Rate limit»**

В `hermes-web/static/admin.html`, внутри `<div class="cards">`, найти и
удалить целиком эти два блока (между карточкой «Диск (NVMe)» и карточкой
«Активные сессии»):

```html
    <div class="card">
      <div class="lbl">Кредиты wormsoft.ru</div>
      <div class="big">1.8M<small>/ 3.0M</small></div>
      <div class="bar warn"><i style="width:60%"></i></div>
      <div class="sub">окно 4 часа · Payed</div>
    </div>
    <div class="card">
      <div class="lbl">Rate limit</div>
      <div class="big">37<small>/ 120 req/мин</small></div>
      <div class="bar"><i style="width:31%"></i></div>
      <div class="sub">пик за последний час: 98</div>
    </div>
```

Останется 4 карточки: CPU, RAM, Диск, Активные сессии.

- [ ] **Step 2: Дать оставшимся 4 карточкам id и сбросить демо-значения**

Заменить блок 4 оставшихся карточек (было: CPU/RAM/Диск/Активные сессии
с захардкоженными числами) на:

```html
    <div class="card" id="cpuCard">
      <div class="lbl">CPU</div>
      <div class="big">…</div>
      <div class="bar"><i style="width:0%"></i></div>
      <div class="sub">8 vCPU · RU-датацентр</div>
    </div>
    <div class="card" id="ramCard">
      <div class="lbl">RAM</div>
      <div class="big">…</div>
      <div class="bar warn"><i style="width:0%"></i></div>
      <div class="sub">—</div>
    </div>
    <div class="card" id="diskCard">
      <div class="lbl">Диск (NVMe)</div>
      <div class="big">…</div>
      <div class="bar"><i style="width:0%"></i></div>
      <div class="sub">кэш вложений + skills</div>
    </div>
    <div class="card" id="sessionsCard">
      <div class="lbl">Активные сессии</div>
      <div class="big">…</div>
      <div class="sub">—</div>
    </div>
```

- [ ] **Step 3: Пользователи — таблица из API, кнопка создания получает id**

Заменить:

```html
    <div class="section-head">
      <h3>Пользователи</h3>
      <button class="btn" onclick="document.getElementById('overlay').classList.add('on')">+ создать пользователя</button>
    </div>
    <table>
      <thead><tr><th>Имя</th><th>Логин</th><th>Роль</th><th>Проектов</th><th>Последняя активность</th><th></th></tr></thead>
      <tbody>
        <tr>
          <td id="name-dem">dem</td>
          ...
        </tr>
        <tr>
          <td id="name-gleb">Глеб (сын)</td>
          ...
        </tr>
      </tbody>
    </table>
```

на:

```html
    <div class="section-head">
      <h3>Пользователи</h3>
      <button class="btn" id="createUserBtn">+ создать пользователя</button>
    </div>
    <table>
      <thead><tr><th>Имя</th><th>Логин</th><th>Роль</th><th>Проектов</th><th>Последняя активность</th><th></th></tr></thead>
      <tbody id="usersBody"></tbody>
    </table>
```

(удалить оба захардкоженных `<tr>` целиком — рендерятся из JS).

- [ ] **Step 4: Журнал — пустой контейнер вместо 5 захардкоженных строк**

Заменить:

```html
    <div class="log">
      <div class="log-line">...</div>
      <div class="log-line ok">...</div>
      <div class="log-line">...</div>
      <div class="log-line err">...</div>
      <div class="log-line">...</div>
    </div>
```

на:

```html
    <div class="log" id="eventsLog"></div>
```

- [ ] **Step 5: Модалка создания пользователя — добавить поле пароля, снять inline-обработчики**

Заменить весь блок `<div class="overlay" id="overlay">...</div>` на:

```html
<div class="overlay" id="overlay">
  <div class="modal">
    <h3>Новый пользователь</h3>
    <label>Имя</label>
    <input type="text" id="createNameInput" placeholder="например, Глеб">
    <p style="font-family:ui-monospace,Consolas,monospace;font-size:10.5px;color:var(--text-dim);margin:4px 0 0">
      имя задаёт администратор — пользователю не нужно ничего придумывать самому, можно поменять в любой момент
    </p>
    <label>Логин</label>
    <input type="text" id="createLoginInput" placeholder="gleb">
    <p style="font-family:ui-monospace,Consolas,monospace;font-size:10.5px;color:var(--text-dim);margin:4px 0 0">
      строчные латинские буквы, цифры, "_", "-" — станет именем рабочей папки, после создания не меняется
    </p>
    <label>Пароль</label>
    <input type="password" id="createPasswordInput" placeholder="пароль для входа">
    <label>Роль</label>
    <select id="createRoleSelect"><option value="participant">участник</option><option value="owner">владелец</option></select>
    <div class="modal-actions">
      <button class="ghost" id="createCancelBtn">Отмена</button>
      <button class="btn" id="createSaveBtn">Создать</button>
    </div>
  </div>
</div>
```

- [ ] **Step 6: Модалка редактирования — логин становится read-only текстом**

Заменить весь блок `<div class="overlay" id="editOverlay">...</div>` на:

```html
<div class="overlay" id="editOverlay">
  <div class="modal">
    <h3>Изменить пользователя</h3>
    <label>Имя</label>
    <input type="text" id="editNameInput">
    <label>Логин</label>
    <div class="mono" id="editLoginText" style="padding:9px 0"></div>
    <label>Роль</label>
    <select id="editRoleSelect"><option value="participant">участник</option><option value="owner">владелец</option></select>
    <div class="modal-actions">
      <button class="ghost" id="editCancelBtn">Отмена</button>
      <button class="btn" id="editSaveBtn">Сохранить</button>
    </div>
  </div>
</div>
```

- [ ] **Step 7: Добавить новую модалку сброса пароля**

Сразу после закрывающего `</div>` блока `editOverlay` (перед `<script>`)
добавить:

```html
<div class="overlay" id="resetOverlay">
  <div class="modal">
    <h3>Сброс пароля</h3>
    <label>Новый пароль</label>
    <input type="password" id="resetPasswordInput" placeholder="новый пароль для входа">
    <div class="modal-actions">
      <button class="ghost" id="resetCancelBtn">Отмена</button>
      <button class="btn" id="resetSaveBtn">Сохранить</button>
    </div>
  </div>
</div>
```

- [ ] **Step 8: Заменить весь `<script>` на реальную логику**

Заменить старый блок `<script>...</script>` (демо-обработчики
`openEdit`/`editSaveBtn` на статичных данных) целиком на:

```html
<script src="app.js"></script>
<script>
function fmtBytes(bytes) {
  if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(1) + ' GB';
  if (bytes >= 1024 ** 2) return (bytes / 1024 ** 2).toFixed(0) + ' MB';
  return bytes + ' B';
}

function fmtTime(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString('ru-RU');
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

const EVENT_LABELS = {
  'login': 'вход',
  'project.create': 'создал проект',
  'project.delete': 'удалил проект',
  'chat.start': 'начал чат',
  'user.create': 'создал пользователя',
  'user.update': 'изменил пользователя',
  'user.reset_password': 'сбросил пароль',
};

async function loadOverview() {
  const resp = await apiFetch('/api/admin/overview');
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (resp.status === 403) { location.href = 'home.html'; return; }
  const data = await resp.json();

  document.querySelector('#cpuCard .big').textContent = data.cpu_percent + '%';
  document.querySelector('#cpuCard .bar i').style.width = Math.min(100, data.cpu_percent) + '%';

  const ramPct = data.ram.total_bytes ? Math.round(data.ram.used_bytes / data.ram.total_bytes * 100) : 0;
  document.querySelector('#ramCard .big').textContent = `${fmtBytes(data.ram.used_bytes)} / ${fmtBytes(data.ram.total_bytes)}`;
  document.querySelector('#ramCard .bar i').style.width = ramPct + '%';
  document.querySelector('#ramCard .sub').textContent = `${ramPct}% занято`;

  const diskPct = data.disk.total_bytes ? Math.round(data.disk.used_bytes / data.disk.total_bytes * 100) : 0;
  document.querySelector('#diskCard .big').textContent = `${fmtBytes(data.disk.used_bytes)} / ${fmtBytes(data.disk.total_bytes)}`;
  document.querySelector('#diskCard .bar i').style.width = diskPct + '%';

  document.querySelector('#sessionsCard .big').textContent = data.active_sessions;
  document.querySelector('#sessionsCard .sub').textContent = `${data.active_users} пользователей онлайн`;
}

let editingUsername = null;
let resettingUsername = null;

async function loadUsers() {
  const resp = await apiFetch('/api/admin/users');
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (resp.status === 403) { location.href = 'home.html'; return; }
  const data = await resp.json();

  const tbody = document.getElementById('usersBody');
  tbody.innerHTML = '';
  for (const u of data.users) {
    const tr = document.createElement('tr');
    const roleLabel = u.role === 'owner' ? 'владелец' : 'участник';
    const badgeClass = u.role === 'owner' ? 'owner' : 'member';
    tr.innerHTML = `
      <td>${escapeHtml(u.display_name)}</td>
      <td class="mono">${escapeHtml(u.username)}</td>
      <td><span class="badge ${badgeClass}">${roleLabel}</span></td>
      <td>${u.project_count}</td>
      <td class="mono">${fmtTime(u.last_active)}</td>
      <td class="row-actions"></td>
    `;
    const actionsCell = tr.querySelector('.row-actions');
    const editBtn = document.createElement('button');
    editBtn.textContent = 'изменить';
    editBtn.addEventListener('click', () => openEditModal(u));
    const resetBtn = document.createElement('button');
    resetBtn.textContent = 'сброс пароля';
    resetBtn.addEventListener('click', () => openResetModal(u.username));
    actionsCell.append(editBtn, resetBtn);
    tbody.appendChild(tr);
  }
}

async function loadEvents() {
  const resp = await apiFetch('/api/admin/events?limit=50');
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (resp.status === 403) { location.href = 'home.html'; return; }
  const data = await resp.json();

  const log = document.getElementById('eventsLog');
  log.innerHTML = '';
  for (const ev of data.events) {
    const div = document.createElement('div');
    div.className = 'log-line';
    const label = EVENT_LABELS[ev.verb] || ev.verb;
    const detail = ev.detail ? `: ${escapeHtml(ev.detail)}` : '';
    div.innerHTML = `<span class="t">${fmtTime(ev.ts)}</span>${escapeHtml(ev.actor)} → ${escapeHtml(label)}${detail}`;
    log.appendChild(div);
  }
}

function openEditModal(u) {
  editingUsername = u.username;
  document.getElementById('editNameInput').value = u.display_name;
  document.getElementById('editLoginText').textContent = u.username;
  document.getElementById('editRoleSelect').value = u.role;
  document.getElementById('editOverlay').classList.add('on');
}

function openResetModal(username) {
  resettingUsername = username;
  document.getElementById('resetPasswordInput').value = '';
  document.getElementById('resetOverlay').classList.add('on');
}

document.getElementById('createUserBtn').addEventListener('click', () => {
  document.getElementById('createNameInput').value = '';
  document.getElementById('createLoginInput').value = '';
  document.getElementById('createPasswordInput').value = '';
  document.getElementById('createRoleSelect').value = 'participant';
  document.getElementById('overlay').classList.add('on');
});

document.getElementById('createCancelBtn').addEventListener('click', () => {
  document.getElementById('overlay').classList.remove('on');
});

document.getElementById('createSaveBtn').addEventListener('click', async () => {
  const payload = {
    username: document.getElementById('createLoginInput').value.trim(),
    display_name: document.getElementById('createNameInput').value.trim(),
    role: document.getElementById('createRoleSelect').value,
    password: document.getElementById('createPasswordInput').value,
  };
  const resp = await apiFetch('/api/admin/users', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    alert('Не удалось создать пользователя: ' + (body.error || resp.status));
    return;
  }
  document.getElementById('overlay').classList.remove('on');
  await loadUsers();
});

document.getElementById('editCancelBtn').addEventListener('click', () => {
  document.getElementById('editOverlay').classList.remove('on');
});

document.getElementById('editSaveBtn').addEventListener('click', async () => {
  const payload = {
    display_name: document.getElementById('editNameInput').value.trim(),
    role: document.getElementById('editRoleSelect').value,
  };
  const resp = await apiFetch('/api/admin/users/' + encodeURIComponent(editingUsername), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  });
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    alert('Не удалось сохранить: ' + (body.error || resp.status));
    return;
  }
  document.getElementById('editOverlay').classList.remove('on');
  await loadUsers();
});

document.getElementById('resetCancelBtn').addEventListener('click', () => {
  document.getElementById('resetOverlay').classList.remove('on');
});

document.getElementById('resetSaveBtn').addEventListener('click', async () => {
  const password = document.getElementById('resetPasswordInput').value;
  const resp = await apiFetch('/api/admin/users/' + encodeURIComponent(resettingUsername) + '/reset-password', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }),
  });
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    alert('Не удалось сбросить пароль: ' + (body.error || resp.status));
    return;
  }
  document.getElementById('resetOverlay').classList.remove('on');
  alert('Пароль обновлён');
});

(async () => {
  const me = await requireAuth();
  if (!me) return;
  if (me.role !== 'owner') { location.href = 'home.html'; return; }
  await Promise.all([loadOverview(), loadUsers(), loadEvents()]);
})();
</script>
```

- [ ] **Step 9: Проверить синтаксис извлечённого `<script>` через node**

Скопировать содержимое финального `<script>` (без тега `<script src="app.js">`,
только второй инлайновый блок) в отдельный файл и проверить:

Run: `node --check /tmp/admin-script-check.js` (или, без создания файла:
`node -e "new Function(require('fs').readFileSync('/dev/stdin', 'utf8'))" < extracted-script.js`)
Expected: без ошибок синтаксиса (пустой вывод, код выхода 0).

- [ ] **Step 10: Разблокировать плитку «Администрирование» в `home.html`**

В `hermes-web/static/home.html` заменить:

```html
    <a class="tile admin disabled" href="#" onclick="return false" data-role-only="owner">
      <span class="soon">скоро</span>
      <span class="ic">🛠️</span>
      <h3>Администрирование</h3>
      <p>Пользователи, метрики VPS и wormsoft.ru — отдельный срез.</p>
    </a>
```

на:

```html
    <a class="tile admin" href="admin.html" data-role-only="owner">
      <span class="ic">🛠️</span>
      <h3>Администрирование</h3>
      <p>Пользователи, метрики VPS, журнал событий.</p>
    </a>
```

(убрали `.disabled`, `onclick="return false"`, бейдж «скоро»; текст
больше не обещает wormsoft.ru-метрики, которых в этом срезе нет; ссылка
теперь ведёт на `admin.html`. Видимость по-прежнему управляется уже
существующим CSS-правилом `[data-role-only="owner"]` +
`body.role-owner`, JS в `home.html` трогать не нужно — `role-owner`
уже выставляется в текущем `(async () => {...})()` блоке.)

- [ ] **Step 11: Прогнать весь backend-набор ещё раз (регрессия от фронтенд-правок исключена, но контракт проверить стоит)**

Run: `pytest -v` (из `hermes-web/`)
Expected: PASS, без изменений относительно конца Task 4.

- [ ] **Step 12: Commit**

```bash
git add hermes-web/static/admin.html hermes-web/static/home.html
git commit -m "feat(hermes-web): admin.html на реальных данных API, разблокирована ссылка в home.html"
```

---

## Self-Review (проведено при написании плана)

**Spec coverage:**
- Раздел 1 (доступ) → Task 4 Step 3 (`_require_owner`) + Task 5 Step 10
  (скрытие ссылки в `home.html`, уже готовое CSS-правило).
- Раздел 2 (обзор/метрики) → Task 2 (метрики) + Task 4 (`handle_admin_overview`)
  + Task 5 (карточки).
- Раздел 3 (пользователи) → Task 1 (storage) + Task 4 (4 эндпоинта) +
  Task 5 (таблица + 3 модалки).
- Раздел 4 (журнал) → Task 1 (`events`/`log_event`/`list_events`) +
  Task 3 (точки логирования) + Task 4 (`handle_admin_events`) + Task 5
  (рендер лога).
- Global Constraints (валидация логина, запрет самопонижения, неизменный
  логин, отсутствие новых зависимостей) — покрыты в Task 4 Step 3 и
  Task 1.
- «Что сознательно не делаем» (кредиты wormsoft.ru, удаление
  пользователя, смена логина, отдельный экран «VPS и агент», ретенция
  `events`) — ни в одной задаче не реализуется, соответствует спеку.

**Placeholder scan:** нет TBD/TODO, весь код в шагах — финальный, без
заглушек типа «добавить обработку ошибок».

**Type consistency:** `storage.log_event(conn, actor, verb, detail="")` —
сигнатура одна и та же в Task 1 (определение) и во всех точках вызова в
Task 3 и Task 4. `storage.list_events(conn, limit=50)` — использована с
тем же контрактом в Task 4 (`handle_admin_events`) и в тестах Task 1/4.
`admin_metrics.cpu_percent()`/`ram_usage()`/`disk_usage(path)` — сигнатуры
из Task 2 используются в Task 4 `handle_admin_overview` без расхождений.
`count_active_sessions` возвращает `{"sessions", "users"}` — Task 1
определение и Task 4 использование (`active["sessions"]`/`active["users"]`)
совпадают.
