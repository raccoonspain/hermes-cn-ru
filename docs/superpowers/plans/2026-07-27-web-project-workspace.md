# Рабочий экран проекта (срез 3, часть 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Подключить `project-workspace.html` к реальному бэкенду: открыть
любой существующий проект и продолжить с ним диалог, увидеть и
организовать файлы `source`/`outer`/`result` (включая подпапки),
смотреть «Активность агента» в реальном времени.

**Architecture:** Тот же `hermes-web` (Python/aiohttp), без нового
стека. Новый модуль `hermes_web/workspace.py` — файловые операции с
двухслойной защитой путей поверх уже проверенного
`project_index_core.resolve_project_path`. Ленивая Hermes-сессия на
проект в `quickchat.py`. 6 новых HTTP-эндпоинтов в `app.py`. Вложения —
через машиночитаемый хвост текста сообщения (`📎 ...`), без новых
таблиц. Активность агента — эфемерно, поверх уже идущего SSE.

**Tech Stack:** Python 3 / aiohttp / SQLite (без изменений); фронтенд —
чистый HTML/CSS/JS без сборщика (как и весь `hermes-web/static/`).

## Global Constraints

- Двухслойная защита путей везде: слой 1 — `project_index_core.
  resolve_project_path` (проект принадлежит пользователю), слой 2 —
  запрошенный файл не выходит за пределы **этого** проекта. Для
  `mkdir`/`upload`/сохранения не-корневого файла — обязателен третий
  слой: путь должен лежать внутри `source`/`outer`/`result`.
- Никакой новой таблицы под лог активности — рендерим `tool.*`/`run.*`
  события прямо из уже идущего SSE-потока `POST /api/chat/{id}/send`.
- Никакой новой таблицы под вложения — путь кодируется хвостом текста
  сообщения (`\n\n📎 relative_path, relative_path2`), парсится и на
  отправке, и при рендере истории.
- Коллизия имени при `mkdir`/`upload` — 409, без тихого авто-суффикса
  (та же политика, что уже принята для `move_project`).
- Текстовый редактор в браузере сохраняет только `.md`/`.txt` — иначе
  400.
- Сохранение **корневого** `about.md` (ровно `relative_path == "about.
  md"`, не `source/about.md`) сразу вызывает `project_index_core.
  index_update` через `run_in_executor` (сеть может дойти до ~44с,
  нельзя блокировать однопоточный event loop aiohttp).
- В этом срезе — только «создать папку» и «загрузить в выбранную
  папку». Переименование/перемещение/удаление — вне рамок (агент в
  чате или SSH).
- D-010: внутри `source`/`outer`/`result` разрешены подпапки любой
  вложенности (см. `docs/decisions.md`).
- Спек: `docs/superpowers/specs/2026-07-27-web-project-workspace-design.md`.

---

## Task 0: Безопасность путей + дерево файлов (`workspace.py`)

**Files:**
- Create: `hermes-web/hermes_web/workspace.py`
- Create: `hermes-web/tests/test_workspace.py`

**Interfaces:**
- Produces: `workspace.WorkspaceError(Exception)`, `workspace.
  WorkspaceCollisionError(WorkspaceError)`, `workspace.resolve_file_path
  (user: str, project_path: str, relative_path: str, config) -> tuple
  [str, str]` (возвращает `(project_root, candidate)`, оба —
  `os.path.realpath`), `workspace.list_tree(user: str, project_path:
  str, config) -> dict` (`{"root_files": [...], "source": [...],
  "outer": [...], "result": [...]}`, каждый файл —
  `{"relative_path"/"name", "size", "mtime"}`).
- Consumes: `project_index_core.resolve_project_path`/`ProjectIndexError`
  (уже есть в `hermes-plugins/project_index/core.py`), `quickchat.Config`
  (`workspace_root`/`project_index_db_path`/`wormsoft_api_key`, уже есть
  в `hermes_web/quickchat.py`).

- [ ] **Step 1: Написать падающие тесты**

```python
# hermes-web/tests/test_workspace.py
import os
import sys

import pytest

sys.path.insert(0, os.environ["PROJECT_INDEX_PLUGIN_DIR"])
from project_index import core as project_index_core  # noqa: E402

from hermes_web import workspace
from hermes_web.quickchat import Config


def _config(tmp_path):
    return Config(
        hermes_base_url="http://fake-hermes.invalid",
        hermes_api_key="fake-key",
        workspace_root=str(tmp_path / "workspace"),
        project_index_db_path=str(tmp_path / "project_index.db"),
        wormsoft_api_key=None,
    )


ABOUT_MD = """---
tags: []
status: active
---

# Название проекта
Тест

# Краткое описание
Описание

# Опорные точки

# На чём остановились
"""


def _write_project(tmp_path, config, rel_dir):
    project_dir = tmp_path / "workspace" / rel_dir
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(ABOUT_MD, encoding="utf-8")
    user = rel_dir.split("/")[0]
    project_index_core.index_update(
        user, rel_dir, workspace_root=config.workspace_root, db_path=config.project_index_db_path,
    )
    return project_dir


def test_resolve_file_path_accepts_file_inside_project(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    project_root, candidate = workspace.resolve_file_path("dem", "dem/ALL/a", "about.md", config)
    assert project_root == str(tmp_path / "workspace" / "dem" / "ALL" / "a")
    assert candidate == str(tmp_path / "workspace" / "dem" / "ALL" / "a" / "about.md")


def test_resolve_file_path_rejects_traversal_outside_project(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.resolve_file_path("dem", "dem/ALL/a", "../../etc/passwd", config)


def test_resolve_file_path_rejects_foreign_project(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(project_index_core.ProjectIndexError):
        workspace.resolve_file_path("rost", "dem/ALL/a", "about.md", config)


def test_list_tree_includes_only_existing_root_files(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert [f["name"] for f in tree["root_files"]] == ["about.md"]
    assert tree["source"] == []
    assert tree["outer"] == []
    assert tree["result"] == []


def test_list_tree_lists_nested_folders(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    nested = project_dir / "source" / "Иванов"
    nested.mkdir(parents=True)
    (nested / "2026-07-27_glava1.pdf").write_bytes(b"pdf-bytes")

    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert [f["relative_path"] for f in tree["source"]] == ["source/Иванов/2026-07-27_glava1.pdf"]
    assert tree["source"][0]["size"] == len(b"pdf-bytes")


def test_list_tree_rejects_foreign_project(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(project_index_core.ProjectIndexError):
        workspace.list_tree("rost", "dem/ALL/a", config)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd hermes-web && venv/bin/pytest tests/test_workspace.py -v` (или
путь до venv, использованного в предыдущих срезах — см. `docs/state.md`)

Expected: `ModuleNotFoundError: No module named 'hermes_web.workspace'`

- [ ] **Step 3: Реализовать `workspace.py`**

```python
# hermes-web/hermes_web/workspace.py
"""Файловые операции внутри проекта для рабочего экрана
(project-workspace.html): дерево source/outer/result, чтение/сохранение
текстовых файлов, создание подпапок, загрузка вложений.

Не часть Hermes-плагина project_index — эта логика специфична для веб-
морды (агенту такое не нужно, у него прямой доступ к файловой системе
своей песочницы). sys.path-манипуляция для PROJECT_INDEX_PLUGIN_DIR
продублирована из quickchat.py/projects.py намеренно (тот же повод, см.
их докстринги — reaching into another module's private setup would be
more fragile than a few self-contained lines here).
"""
from __future__ import annotations

import datetime
import os
import sys

_PROJECT_INDEX_DIR = os.environ.get("PROJECT_INDEX_PLUGIN_DIR")
if _PROJECT_INDEX_DIR and _PROJECT_INDEX_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_INDEX_DIR)

from project_index import core as project_index_core  # noqa: E402

BUCKETS = ("source", "outer", "result")
ROOT_EDITABLE_FILES = ("about.md", "AGENTS.md", "history.md")


class WorkspaceError(Exception):
    """Raised for expected, user-facing failures (bad path, bad extension, bad name)."""


class WorkspaceCollisionError(WorkspaceError):
    """Raised when mkdir/upload target already exists — no silent auto-suffix."""


def _workspace_root(config) -> str:
    return config.workspace_root or project_index_core.WORKSPACE_ROOT


def _project_index_kwargs(config) -> dict:
    kwargs: dict = {}
    if config.workspace_root is not None:
        kwargs["workspace_root"] = config.workspace_root
    if config.project_index_db_path is not None:
        kwargs["db_path"] = config.project_index_db_path
    if config.wormsoft_api_key is not None:
        kwargs["api_key"] = config.wormsoft_api_key
    return kwargs


def resolve_file_path(user: str, project_path: str, relative_path: str, config) -> tuple[str, str]:
    """Двухслойная проверка: проект принадлежит user (слой 1, через уже
    проверенный project_index_core.resolve_project_path — там же уже
    закрыт path-traversal баг, который реально эксплуатировали в
    move_project), запрошенный файл не выходит за пределы этого
    проекта (слой 2). Возвращает (project_root, candidate), оба —
    os.path.realpath."""
    project_root = project_index_core.resolve_project_path(user, project_path, _workspace_root(config))
    candidate = os.path.realpath(os.path.join(project_root, relative_path))
    if candidate != project_root and not candidate.startswith(project_root + os.sep):
        raise WorkspaceError(f"'{relative_path}' выходит за пределы проекта")
    return project_root, candidate


def _require_within_bucket(project_root: str, candidate: str) -> None:
    for bucket in BUCKETS:
        bucket_dir = os.path.join(project_root, bucket)
        if candidate == bucket_dir or candidate.startswith(bucket_dir + os.sep):
            return
    raise WorkspaceError("путь должен быть внутри source/outer/result")


def _iso_mtime(path: str) -> str:
    return datetime.datetime.utcfromtimestamp(os.path.getmtime(path)).isoformat()


def list_tree(user: str, project_path: str, config) -> dict:
    project_root, _ = resolve_file_path(user, project_path, ".", config)

    root_files = []
    for name in ROOT_EDITABLE_FILES:
        full = os.path.join(project_root, name)
        if os.path.isfile(full):
            root_files.append({"name": name, "size": os.path.getsize(full), "mtime": _iso_mtime(full)})

    tree = {"root_files": root_files}
    for bucket in BUCKETS:
        bucket_dir = os.path.join(project_root, bucket)
        entries = []
        if os.path.isdir(bucket_dir):
            for dirpath, _dirnames, filenames in os.walk(bucket_dir):
                for filename in filenames:
                    full = os.path.join(dirpath, filename)
                    entries.append({
                        "relative_path": os.path.relpath(full, project_root),
                        "size": os.path.getsize(full),
                        "mtime": _iso_mtime(full),
                    })
        tree[bucket] = sorted(entries, key=lambda e: e["relative_path"])
    return tree
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd hermes-web && venv/bin/pytest tests/test_workspace.py -v`

Expected: PASS (все 5 тестов)

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/workspace.py hermes-web/tests/test_workspace.py
git commit -m "feat(hermes-web): двухслойная защита путей + дерево файлов проекта"
```

---

## Task 1: `storage.get_chat_session_for_project`

**Files:**
- Modify: `hermes-web/hermes_web/storage.py`
- Modify: `hermes-web/tests/test_storage.py`

**Interfaces:**
- Produces: `storage.get_chat_session_for_project(conn, user: str,
  project_path: str) -> Optional[dict]` — последняя (по `created_at`)
  сессия чата для пары `(user, project_path)`, или `None`.
- Consumes: таблица `chat_sessions` (уже есть, без изменений схемы).

- [ ] **Step 1: Написать падающий тест**

```python
# добавить в hermes-web/tests/test_storage.py

def test_get_chat_session_for_project_returns_latest(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/p/a", "web_1", created_at=100.0)
    storage.create_chat_session(conn, "chat2", "dem", "/p/a", "web_2", created_at=200.0)
    row = storage.get_chat_session_for_project(conn, "dem", "/p/a")
    assert row["id"] == "chat2"


def test_get_chat_session_for_project_scoped_to_user(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/p/a", "web_1", created_at=100.0)
    assert storage.get_chat_session_for_project(conn, "rost", "/p/a") is None


def test_get_chat_session_for_project_missing_returns_none(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    assert storage.get_chat_session_for_project(conn, "dem", "/nope") is None
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd hermes-web && venv/bin/pytest tests/test_storage.py -k for_project -v`

Expected: `AttributeError: module 'hermes_web.storage' has no attribute 'get_chat_session_for_project'`

- [ ] **Step 3: Реализовать функцию**

```python
# добавить в hermes-web/hermes_web/storage.py, рядом с get_chat_session

def get_chat_session_for_project(conn: sqlite3.Connection, user: str, project_path: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM chat_sessions WHERE user = ? AND project_path = ? ORDER BY created_at DESC LIMIT 1",
        (user, project_path),
    ).fetchone()
    return dict(row) if row else None
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd hermes-web && venv/bin/pytest tests/test_storage.py -v`

Expected: PASS (все тесты файла)

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/storage.py hermes-web/tests/test_storage.py
git commit -m "feat(hermes-web): storage.get_chat_session_for_project"
```

---

## Task 2: Ленивая Hermes-сессия для существующего проекта (`quickchat.get_or_open_session`)

**Files:**
- Modify: `hermes-web/hermes_web/quickchat.py`
- Modify: `hermes-web/tests/test_quickchat.py`

**Interfaces:**
- Produces: `quickchat.get_or_open_session(db_conn, http_session,
  config: Config, user: str, project_path: str) -> dict` — `{
  "chat_session_id", "project_path", "hermes_session_id"}`. Кидает
  `project_index_core.ProjectIndexError`, если проект не принадлежит
  `user` или `about.md` не найден.
- Consumes: `storage.get_chat_session_for_project` (Task 1),
  `project_index_core.get_project_detail`/`resolve_project_path`,
  `hermes_client.create_session`.
- Внутренний рефакторинг: создание Hermes-сессии выносится в приватный
  `_new_hermes_session(http_session, config)` — используется и
  `create_quick_chat`, и `get_or_open_session`; публичный контракт
  `create_quick_chat` не меняется.

- [ ] **Step 1: Написать падающие тесты**

```python
# добавить в hermes-web/tests/test_quickchat.py

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
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd hermes-web && venv/bin/pytest tests/test_quickchat.py -k get_or_open_session -v`

Expected: `AttributeError: module 'hermes_web.quickchat' has no attribute 'get_or_open_session'`

- [ ] **Step 3: Рефакторинг + реализация**

```python
# hermes_web/quickchat.py — заменить блок создания Hermes-сессии внутри
# create_quick_chat новым вызовом и добавить _new_hermes_session +
# get_or_open_session

# было (внутри create_quick_chat):
#     hermes_session_id = f"web_{uuid.uuid4().hex}"
#     await hermes_client.create_session(http_session, config.hermes_base_url, config.hermes_api_key, hermes_session_id)
# заменить на:
    hermes_session_id = await _new_hermes_session(http_session, config)

# новая функция, рядом с create_quick_chat:
async def _new_hermes_session(http_session, config: Config) -> str:
    hermes_session_id = f"web_{uuid.uuid4().hex}"
    await hermes_client.create_session(http_session, config.hermes_base_url, config.hermes_api_key, hermes_session_id)
    return hermes_session_id


async def get_or_open_session(db_conn, http_session, config: Config, user: str, project_path: str) -> dict:
    resolved = project_index_core.resolve_project_path(user, project_path, _workspace_root(config))
    # get_project_detail кидает ProjectIndexError, если about.md не найден —
    # значит это не проект, открывать нечего.
    project_index_core.get_project_detail(user, project_path, workspace_root=_workspace_root(config))

    existing = storage.get_chat_session_for_project(db_conn, user, resolved)
    if existing is not None:
        return {
            "chat_session_id": existing["id"],
            "project_path": existing["project_path"],
            "hermes_session_id": existing["hermes_session_id"],
        }

    hermes_session_id = await _new_hermes_session(http_session, config)
    chat_session_id = uuid.uuid4().hex
    storage.create_chat_session(db_conn, chat_session_id, user, resolved, hermes_session_id, created_at=time.time())
    return {"chat_session_id": chat_session_id, "project_path": resolved, "hermes_session_id": hermes_session_id}
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd hermes-web && venv/bin/pytest tests/test_quickchat.py -v`

Expected: PASS (все тесты файла, включая уже существовавшие для
`create_quick_chat` — рефакторинг не должен их сломать)

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/quickchat.py hermes-web/tests/test_quickchat.py
git commit -m "feat(hermes-web): ленивая Hermes-сессия для существующего проекта"
```

---

## Task 3: Чтение и сохранение файлов + реиндексация `about.md`

**Files:**
- Modify: `hermes-web/hermes_web/workspace.py`
- Modify: `hermes-web/tests/test_workspace.py`

**Interfaces:**
- Produces: `workspace.read_file(user, project_path, relative_path,
  config) -> dict` (`{"path", "name", "content": bytes}`, кидает
  `WorkspaceError`, если файла нет). `workspace.save_file(user,
  project_path, relative_path, content: str, config) -> dict`
  (async; `{"path", "reindexed": bool}`).
- Consumes: `resolve_file_path`/`_require_within_bucket` (Task 0),
  `project_index_core.index_update`.

- [ ] **Step 1: Написать падающие тесты**

```python
# добавить в hermes-web/tests/test_workspace.py
import asyncio
import threading


def test_read_file_returns_bytes(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("привет", encoding="utf-8")

    result = workspace.read_file("dem", "dem/ALL/a", "source/note.txt", config)
    assert result["content"] == "привет".encode("utf-8")
    assert result["name"] == "note.txt"


def test_read_file_missing_raises(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.read_file("dem", "dem/ALL/a", "source/nope.txt", config)


@pytest.mark.asyncio
async def test_save_file_writes_content(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()

    result = await workspace.save_file("dem", "dem/ALL/a", "source/note.txt", "новый текст", config)
    assert (project_dir / "source" / "note.txt").read_text(encoding="utf-8") == "новый текст"
    assert result["reindexed"] is False


@pytest.mark.asyncio
async def test_save_file_rejects_non_editable_extension(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        await workspace.save_file("dem", "dem/ALL/a", "source/data.bin", "x", config)


@pytest.mark.asyncio
async def test_save_file_rejects_path_outside_bucket(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        await workspace.save_file("dem", "dem/ALL/a", "note.txt", "x", config)


@pytest.mark.asyncio
async def test_save_root_about_md_triggers_reindex(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")

    calls = []

    def fake_index_update(user, project_path, **kwargs):
        calls.append((user, project_path))
        return {"path": project_path, "indexed": False, "message": "ok"}

    monkeypatch.setattr(workspace.project_index_core, "index_update", fake_index_update)

    result = await workspace.save_file("dem", "dem/ALL/a", "about.md", "новый about", config)
    assert result["reindexed"] is True
    assert calls == [("dem", "dem/ALL/a")]
    assert (project_dir / "about.md").read_text(encoding="utf-8") == "новый about"


@pytest.mark.asyncio
async def test_save_nested_about_md_does_not_trigger_reindex(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()

    calls = []
    monkeypatch.setattr(workspace.project_index_core, "index_update", lambda *a, **k: calls.append(1))

    result = await workspace.save_file("dem", "dem/ALL/a", "source/about.md", "текст", config)
    assert result["reindexed"] is False
    assert calls == []


@pytest.mark.asyncio
async def test_save_about_md_reindex_runs_off_event_loop(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    calling_thread = threading.current_thread()
    seen = {}

    def fake_index_update(user, project_path, **kwargs):
        seen["thread"] = threading.current_thread()
        return {"path": project_path, "indexed": False, "message": "ok"}

    monkeypatch.setattr(workspace.project_index_core, "index_update", fake_index_update)
    await workspace.save_file("dem", "dem/ALL/a", "about.md", "текст", config)
    assert seen["thread"] is not calling_thread
    assert seen["thread"] is not threading.main_thread()
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd hermes-web && venv/bin/pytest tests/test_workspace.py -k "read_file or save_file or about_md" -v`

Expected: `AttributeError: module 'hermes_web.workspace' has no attribute 'read_file'`

- [ ] **Step 3: Реализовать**

```python
# добавить в hermes-web/hermes_web/workspace.py

import asyncio
import functools

EDITABLE_EXTENSIONS = (".md", ".txt")


def read_file(user: str, project_path: str, relative_path: str, config) -> dict:
    _, candidate = resolve_file_path(user, project_path, relative_path, config)
    if not os.path.isfile(candidate):
        raise WorkspaceError(f"файл не найден: {relative_path}")
    with open(candidate, "rb") as fh:
        content = fh.read()
    return {"path": candidate, "name": os.path.basename(candidate), "content": content}


async def save_file(user: str, project_path: str, relative_path: str, content: str, config) -> dict:
    ext = os.path.splitext(relative_path)[1].lower()
    if ext not in EDITABLE_EXTENSIONS:
        raise WorkspaceError(f"недопустимое расширение для сохранения: {ext or '(нет)'}")

    project_root, candidate = resolve_file_path(user, project_path, relative_path, config)
    if relative_path not in ROOT_EDITABLE_FILES:
        _require_within_bucket(project_root, candidate)

    os.makedirs(os.path.dirname(candidate), exist_ok=True)
    with open(candidate, "w", encoding="utf-8") as fh:
        fh.write(content)

    reindexed = False
    if relative_path == "about.md":
        loop = asyncio.get_running_loop()
        # index_update может дойти до реального HTTP-вызова (эмбеддинг через
        # wormsoft.ru) — тот же повод, что уже закрыт в quickchat.create_quick_chat:
        # синхронный вызов такой длины прямо в event loop замораживает весь
        # процесс, не только этот запрос.
        await loop.run_in_executor(
            None, functools.partial(project_index_core.index_update, user, project_path, **_project_index_kwargs(config)),
        )
        reindexed = True
    return {"path": candidate, "reindexed": reindexed}
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd hermes-web && venv/bin/pytest tests/test_workspace.py -v`

Expected: PASS (все тесты файла)

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/workspace.py hermes-web/tests/test_workspace.py
git commit -m "feat(hermes-web): чтение/сохранение файлов проекта, реиндексация about.md"
```

---

## Task 4: Создание подпапок (`workspace.make_dir`)

**Files:**
- Modify: `hermes-web/hermes_web/workspace.py`
- Modify: `hermes-web/tests/test_workspace.py`

**Interfaces:**
- Produces: `workspace.make_dir(user, project_path, parent: str, name:
  str, config) -> dict` (`{"relative_path"}`). Кидает
  `WorkspaceCollisionError`, если папка/файл с таким именем уже есть;
  `WorkspaceError` — недопустимое имя или `parent` вне
  `source`/`outer`/`result`.

- [ ] **Step 1: Написать падающие тесты**

```python
# добавить в hermes-web/tests/test_workspace.py

def test_make_dir_creates_folder_inside_bucket(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    result = workspace.make_dir("dem", "dem/ALL/a", "source", "Иванов", config)
    assert result["relative_path"] == "source/Иванов"
    assert (project_dir / "source" / "Иванов").is_dir()


def test_make_dir_bootstraps_missing_bucket_dir(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    assert not (project_dir / "outer").exists()
    workspace.make_dir("dem", "dem/ALL/a", "outer", "новое", config)
    assert (project_dir / "outer" / "новое").is_dir()


def test_make_dir_nested_parent(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    workspace.make_dir("dem", "dem/ALL/a", "source", "Иванов", config)
    result = workspace.make_dir("dem", "dem/ALL/a", "source/Иванов", "глава1", config)
    assert result["relative_path"] == "source/Иванов/глава1"


def test_make_dir_collision_raises(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    workspace.make_dir("dem", "dem/ALL/a", "source", "Иванов", config)
    with pytest.raises(workspace.WorkspaceCollisionError):
        workspace.make_dir("dem", "dem/ALL/a", "source", "Иванов", config)


def test_make_dir_rejects_parent_outside_buckets(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.make_dir("dem", "dem/ALL/a", ".", "новая-папка", config)


def test_make_dir_rejects_bad_name(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.make_dir("dem", "dem/ALL/a", "source", "../escape", config)
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd hermes-web && venv/bin/pytest tests/test_workspace.py -k make_dir -v`

Expected: `AttributeError: module 'hermes_web.workspace' has no attribute 'make_dir'`

- [ ] **Step 3: Реализовать**

```python
# добавить в hermes-web/hermes_web/workspace.py

def make_dir(user: str, project_path: str, parent: str, name: str, config) -> dict:
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise WorkspaceError(f"недопустимое имя папки: '{name}'")

    project_root, parent_candidate = resolve_file_path(user, project_path, parent, config)
    _require_within_bucket(project_root, parent_candidate)

    target = os.path.realpath(os.path.join(parent_candidate, name))
    if target != parent_candidate and not target.startswith(parent_candidate + os.sep):
        raise WorkspaceError(f"недопустимое имя папки: '{name}'")
    if os.path.exists(target):
        raise WorkspaceCollisionError(f"'{name}' уже существует в '{parent}'")

    os.makedirs(target)
    return {"relative_path": os.path.relpath(target, project_root)}
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd hermes-web && venv/bin/pytest tests/test_workspace.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/workspace.py hermes-web/tests/test_workspace.py
git commit -m "feat(hermes-web): создание подпапок внутри source/outer/result"
```

---

## Task 5: Загрузка вложений (`workspace.save_upload`)

**Files:**
- Modify: `hermes-web/hermes_web/workspace.py`
- Modify: `hermes-web/tests/test_workspace.py`

**Interfaces:**
- Produces: `workspace.save_upload(user, project_path, target_dir: str,
  filename: str, content: bytes, config) -> dict` (`{"relative_path",
  "size"}`). Дата-префикс на имени файла — как в `project_index_core.
  _add_date_prefix`, локальная копия (та же логика, не импорт приватной
  функции плагина — hermes-web не должен зависеть от internals плагина).

- [ ] **Step 1: Написать падающие тесты**

```python
# добавить в hermes-web/tests/test_workspace.py
import datetime as _dt


def test_save_upload_adds_date_prefix(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    result = workspace.save_upload("dem", "dem/ALL/a", "source", "scan.jpg", b"jpeg-bytes", config)
    today = _dt.date.today().isoformat()
    assert result["relative_path"] == f"source/{today}_scan.jpg"
    assert result["size"] == len(b"jpeg-bytes")
    assert (project_dir / "source" / f"{today}_scan.jpg").read_bytes() == b"jpeg-bytes"


def test_save_upload_keeps_existing_date_prefix(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    result = workspace.save_upload("dem", "dem/ALL/a", "source", "2026-01-01_old.jpg", b"x", config)
    assert result["relative_path"] == "source/2026-01-01_old.jpg"


def test_save_upload_into_nested_folder(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source" / "Иванов").mkdir(parents=True)
    result = workspace.save_upload("dem", "dem/ALL/a", "source/Иванов", "glava1.pdf", b"pdf", config)
    assert result["relative_path"].startswith("source/Иванов/")


def test_save_upload_bootstraps_missing_target_dir(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    workspace.save_upload("dem", "dem/ALL/a", "source/новая-папка", "x.txt", b"x", config)
    assert (project_dir / "source" / "новая-папка").is_dir()


def test_save_upload_collision_raises(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    workspace.save_upload("dem", "dem/ALL/a", "source", "2026-01-01_old.jpg", b"x", config)
    with pytest.raises(workspace.WorkspaceCollisionError):
        workspace.save_upload("dem", "dem/ALL/a", "source", "2026-01-01_old.jpg", b"y", config)


def test_save_upload_rejects_target_outside_buckets(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.save_upload("dem", "dem/ALL/a", ".", "x.txt", b"x", config)


def test_save_upload_strips_path_from_filename(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    today = _dt.date.today().isoformat()
    result = workspace.save_upload("dem", "dem/ALL/a", "source", "../../etc/evil.txt", b"x", config)
    # basename() из имени файла убрал ../../etc/ — файл лёг прямо в source/,
    # а не по пути evil.txt из непроверенного имени.
    assert result["relative_path"] == f"source/{today}_evil.txt"
    assert (project_dir / "source" / f"{today}_evil.txt").read_bytes() == b"x"
    assert list(project_dir.glob("etc")) == []
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd hermes-web && venv/bin/pytest tests/test_workspace.py -k save_upload -v`

Expected: `AttributeError: module 'hermes_web.workspace' has no attribute 'save_upload'`

- [ ] **Step 3: Реализовать**

```python
# добавить в hermes-web/hermes_web/workspace.py

import datetime
import re

_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_")


def _add_date_prefix(name: str) -> str:
    if _DATE_PREFIX_RE.match(name):
        return name
    today = datetime.date.today().isoformat()
    return f"{today}_{name}"


def save_upload(user: str, project_path: str, target_dir: str, filename: str, content: bytes, config) -> dict:
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name in (".", ".."):
        raise WorkspaceError(f"недопустимое имя файла: '{filename}'")

    project_root, target_dir_candidate = resolve_file_path(user, project_path, target_dir, config)
    _require_within_bucket(project_root, target_dir_candidate)

    dated_name = _add_date_prefix(safe_name)
    target = os.path.join(target_dir_candidate, dated_name)
    if os.path.exists(target):
        raise WorkspaceCollisionError(f"'{dated_name}' уже существует в '{target_dir}'")

    os.makedirs(target_dir_candidate, exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(content)

    return {"relative_path": os.path.relpath(target, project_root), "size": len(content)}
```

(Примечание: `import datetime` уже может быть добавлен в Task 0 — если
так, не дублировать; убедиться, что модуль импортирует `datetime` и `re`
ровно один раз в начале файла.)

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd hermes-web && venv/bin/pytest tests/test_workspace.py -v`

Expected: PASS (весь файл — к этому шагу должно быть ~20+ тестов)

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/workspace.py hermes-web/tests/test_workspace.py
git commit -m "feat(hermes-web): загрузка вложений с датой-префиксом в выбранную папку"
```

---

## Task 6: HTTP-эндпоинты (`app.py`)

**Files:**
- Modify: `hermes-web/hermes_web/app.py`
- Modify: `hermes-web/tests/test_app.py`

**Interfaces:**
- Produces:
  - `POST /api/projects/open {path}` → `{chat_session_id,
    project_path}`, 404 на `ProjectIndexError`.
  - `GET /api/projects/tree?path=` → дерево, 404 на любую ошибку
    (проект не найден/не принадлежит пользователю).
  - `GET /api/projects/file?path=&file=&download=` → тело файла; 404
    на любую ошибку.
  - `POST /api/projects/file {path, file, content}` → `{path,
    reindexed}`; `WorkspaceError`→400, `ProjectIndexError`→404.
  - `POST /api/projects/mkdir {path, parent, name}` → `{relative_
    path}`; `WorkspaceCollisionError`→409, `WorkspaceError`→400,
    `ProjectIndexError`→404.
  - `POST /api/projects/upload` (multipart: `path`, `target_dir`,
    `file`) → `{relative_path, size}`; те же статусы, что и `mkdir`.
- Consumes: `workspace.*` (Task 0/3/4/5), `quickchat.get_or_open_session`
  (Task 2). Все хендлеры — под `_require_user` (как везде в `app.py`).

- [ ] **Step 1: Написать падающие тесты**

```python
# добавить в hermes-web/tests/test_app.py

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
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd hermes-web && venv/bin/pytest tests/test_app.py -k "open_project or project_tree or project_file or project_mkdir or project_upload" -v`

Expected: FAIL с `404 Not Found` (маршруты ещё не зарегистрированы) для всех новых тестов

- [ ] **Step 3: Реализовать хендлеры и маршруты**

```python
# hermes_web/app.py — добавить в импорты:
import os

from . import auth, hermes_client, projects, quickchat, storage, workspace

# добавить хендлеры (рядом с остальными handle_*):

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
        result = workspace.read_file(user["username"], path, file_param, request.app["quickchat_config"])
    except (projects.project_index_core.ProjectIndexError, workspace.WorkspaceError):
        return web.json_response({"error": "not found"}, status=404)

    headers = {}
    content_type = "application/octet-stream"
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{result["name"]}"'
    elif os.path.splitext(result["name"])[1].lower() in (".md", ".txt"):
        content_type = "text/plain; charset=utf-8"
    return web.Response(body=result["content"], headers=headers, content_type=content_type)


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


# в create_app(), рядом с остальными app.router.add_*, до add_static:
    app.router.add_post("/api/projects/open", handle_open_project)
    app.router.add_get("/api/projects/tree", handle_project_tree)
    app.router.add_get("/api/projects/file", handle_project_file_get)
    app.router.add_post("/api/projects/file", handle_project_file_post)
    app.router.add_post("/api/projects/mkdir", handle_project_mkdir)
    app.router.add_post("/api/projects/upload", handle_project_upload)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd hermes-web && venv/bin/pytest tests/ -v`

Expected: PASS (весь пакет — старые тесты не сломаны, новые проходят)

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/app.py hermes-web/tests/test_app.py
git commit -m "feat(hermes-web): эндпоинты рабочего экрана проекта (open/tree/file/mkdir/upload)"
```

---

## Task 7: Включить «Открыть проект →» в `project-selector.html`

**Files:**
- Modify: `hermes-web/static/project-selector.html`

**Interfaces:**
- Consumes: `p.path` (уже доступен в замыкании `renderPanel(p, detail)`,
  см. существующий код вокруг строки с `openProjectBtn`).

- [ ] **Step 1: Заменить плейсхолдер на реальную навигацию**

```javascript
// hermes-web/static/project-selector.html — найти:
//   document.getElementById('openProjectBtn').addEventListener('click', () => {
//     alert('Полноценный экран проекта появится в следующем срезе.');
//   });
// заменить на:
  document.getElementById('openProjectBtn').addEventListener('click', () => {
    location.href = 'project-workspace.html?path=' + encodeURIComponent(p.path);
  });
```

- [ ] **Step 2: Проверить вручную**

Run: `cd hermes-web/static && python3 -m http.server 8080` (или через
уже настроенный локальный запуск `hermes-web`, см. `docs/state.md`), в
браузере залогиниться, открыть панель проекта, кликнуть «Открыть
проект →».

Expected: переход на `project-workspace.html?path=<путь>` (404
странице — нормально, `project-workspace.html` появится в Task 8).

- [ ] **Step 3: Commit**

```bash
git add hermes-web/static/project-selector.html
git commit -m "feat(hermes-web): кнопка «Открыть проект» ведёт на рабочий экран"
```

---

## Task 8: `project-workspace.html` — рабочий экран на реальном API

**Files:**
- Create: `hermes-web/static/project-workspace.html` (заменяет
  клик-макет `/result/project-workspace.html` реальной версией — файл
  в `/result/` не трогаем, он остаётся историческим макетом).

**Interfaces:**
- Consumes: `apiFetch`/`requireAuth`/`readSSE` из `static/app.js` (без
  изменений), все эндпоинты из Task 6, `POST /api/chat/{id}/send` и
  `GET /api/chat/{id}/messages` (без изменений, из среза 1+2).

- [ ] **Step 1: Создать файл**

CSS — переносим как есть из кликабельного макета `/result/project-workspace.html`
(тот же `:root`, `.tree`/`.chat`/`.side`/`.overlay` — визуальный дизайн
согласован в D-009, этот срез меняет только данные и поведение, не
внешний вид), плюс несколько новых классов для сворачиваемых папок и
пикера целевой папки для загрузки.

```html
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes — рабочий экран проекта</title>
<style>
  :root{
    --sky:#12172b; --sky-deep:#0c1020; --panel:#1a2038; --panel-2:#212949;
    --panel-line:#3c4568; --text:#f8f6ef; --text-dim:#aeb7dc; --gold:#f0bb5c;
    --violet:#ad9fe6; --teal:#7fc4b2; --dim-star:#727bab;
    --c-source:#ad9fe6; --c-outer:#7fc4b2; --c-result:#f0bb5c;
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0;height:100%}
  body{
    background:var(--sky); color:var(--text);
    font-family:Georgia,"Iowan Old Style",serif;
    height:100vh; display:grid;
    grid-template-columns:260px 1fr 360px;
    grid-template-rows:56px 1fr;
    grid-template-areas:"top top top" "tree chat side";
  }
  .topbar{
    grid-area:top; border-bottom:1px solid var(--panel-line);
    display:flex; align-items:center; gap:14px; padding:0 20px;
    font-family:ui-monospace,Consolas,monospace; font-size:12.5px; color:var(--text-dim);
  }
  .topbar a{color:var(--text-dim); text-decoration:none}
  .topbar a:hover{color:var(--gold)}
  .topbar .title{color:var(--text); font-family:Georgia,serif; font-size:14.5px; font-style:italic; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:600px}

  .tree{grid-area:tree; border-right:1px solid var(--panel-line); padding:18px 14px; overflow-y:auto}
  .tree .glabel{font-family:ui-monospace,Consolas,monospace;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--text-dim);margin:14px 0 6px;display:flex;justify-content:space-between;align-items:center}
  .tree .glabel:first-child{margin-top:0}
  .new-folder-btn{background:none;border:1px solid var(--panel-line);color:var(--text-dim);border-radius:5px;font-size:10px;padding:1px 5px;cursor:pointer}
  .new-folder-btn:hover{color:var(--text);border-color:var(--gold)}
  .node{display:flex;align-items:center;gap:7px;padding:5px 6px;border-radius:6px;cursor:pointer;font-size:13px;color:var(--text-dim)}
  .node:hover{background:var(--panel);color:var(--text)}
  .node .ic{width:15px;text-align:center;flex-shrink:0;font-size:12px}
  .node.folder-source .ic{color:var(--c-source)}
  .node.folder-outer .ic{color:var(--c-outer)}
  .node.folder-result .ic{color:var(--c-result)}
  .node .name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}

  .chat{grid-area:chat; display:flex; flex-direction:column; min-height:0}
  .messages{flex:1; overflow-y:auto; padding:26px 34px; display:flex; flex-direction:column; gap:20px}
  .msg{max-width:72%; display:flex; flex-direction:column; gap:8px}
  .msg.user{align-self:flex-end; align-items:flex-end}
  .msg.agent{align-self:flex-start}
  .bubble{padding:13px 16px; border-radius:14px; font-size:14px; line-height:1.55; position:relative}
  .msg.user .bubble{background:var(--panel-2); border:1px solid var(--violet); border-bottom-right-radius:3px; white-space:pre-wrap}
  .msg.agent .bubble{background:var(--panel); border:1px solid var(--panel-line); border-bottom-left-radius:3px}
  .msg .meta{font-family:ui-monospace,Consolas,monospace;font-size:10px;color:var(--text-dim)}
  .msg.highlight-flash .bubble{animation:flashglow 1.6s ease}
  @keyframes flashglow{0%{box-shadow:0 0 0 2px var(--gold)}70%{box-shadow:0 0 0 2px var(--gold)}100%{box-shadow:0 0 0 0 transparent}}

  .md-rendered{font-size:14px;line-height:1.6}
  .md-rendered h1,.md-rendered h2,.md-rendered h3{margin:0 0 8px;font-weight:600;color:var(--text);font-family:Georgia,serif}
  .md-rendered h1{font-size:18px} .md-rendered h2{font-size:16px} .md-rendered h3{font-size:14.5px}
  .md-rendered p{margin:0 0 10px} .md-rendered p:last-child{margin-bottom:0}
  .md-rendered ul,.md-rendered ol{margin:0 0 10px;padding-left:20px} .md-rendered li{margin-bottom:3px}
  .md-rendered code{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;background:var(--sky-deep);color:var(--gold);padding:1px 5px;border-radius:4px}
  .md-rendered strong{color:var(--text);font-weight:700}
  .md-rendered table{border-collapse:collapse;width:100%;margin:6px 0 12px;font-size:13px}
  .md-rendered th,.md-rendered td{border:1px solid var(--panel-line);padding:6px 10px;text-align:left}
  .md-rendered th{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--text-dim);background:var(--sky-deep)}
  .copy-btn{position:absolute;top:8px;right:8px;background:none;border:1px solid var(--panel-line);color:var(--text-dim);font-family:ui-monospace,Consolas,monospace;font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer;opacity:0}
  .bubble:hover .copy-btn{opacity:1}
  .copy-btn:hover{color:var(--text);border-color:var(--violet)}
  .copy-btn.copied{color:var(--teal);border-color:var(--teal);opacity:1}
  .attach-row{display:flex;gap:8px;flex-wrap:wrap}
  .attach-chip{display:flex;align-items:center;gap:6px;font-family:ui-monospace,Consolas,monospace;font-size:11px;background:var(--panel);border:1px solid var(--panel-line);border-radius:8px;padding:5px 9px;color:var(--text-dim);cursor:pointer}
  .attach-chip:hover{color:var(--text);border-color:var(--gold)}
  .attach-chip::after{content:"⭳";opacity:.5;margin-left:2px}
  .attach-chip:hover::after{opacity:1}
  .attach-chip .sw{width:7px;height:7px;border-radius:50%;flex-shrink:0}
  .sw.source{background:var(--c-source)} .sw.outer{background:var(--c-outer)} .sw.result{background:var(--c-result)}

  .composer{border-top:1px solid var(--panel-line); padding:14px 22px 18px}
  .compose-attachments{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}
  .compose-attachments .thumb{width:52px;height:52px;border-radius:8px;border:1px solid var(--panel-line);background:var(--panel) center/cover no-repeat;position:relative;overflow:hidden}
  .upload-target-row{display:flex;align-items:center;gap:8px;margin-bottom:8px;font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--text-dim)}
  .upload-target-row select{background:var(--panel);color:var(--text);border:1px solid var(--panel-line);border-radius:6px;font-family:inherit;font-size:11px;padding:3px 6px}
  .compose-box{display:flex;align-items:flex-end;gap:10px;background:var(--panel);border:1px solid var(--panel-line);border-radius:14px;padding:8px 8px 8px 14px}
  .compose-box textarea{flex:1;background:none;border:none;outline:none;resize:none;color:var(--text);font-family:Georgia,serif;font-size:14px;line-height:1.5;max-height:120px;padding:8px 0}
  .icon-btn{background:none;border:1px solid var(--panel-line);color:var(--text-dim);width:36px;height:36px;border-radius:10px;cursor:pointer;flex-shrink:0;display:flex;align-items:center;justify-content:center}
  .icon-btn:hover{color:var(--text);border-color:var(--violet)}
  .send-btn{background:var(--gold);border:none;color:var(--sky-deep);width:36px;height:36px;border-radius:10px;cursor:pointer;flex-shrink:0;font-size:14px}

  .side{grid-area:side; border-left:1px solid var(--panel-line); display:flex; flex-direction:column; min-height:0}
  .side-tabs{display:flex; border-bottom:1px solid var(--panel-line)}
  .side-tabs button{flex:1;background:none;border:none;color:var(--text-dim);padding:13px 8px;cursor:pointer;font-family:ui-monospace,Consolas,monospace;font-size:11px;letter-spacing:.5px;text-transform:uppercase;border-bottom:2px solid transparent}
  .side-tabs button.on{color:var(--text);border-bottom-color:var(--gold)}
  .side-pane{flex:1;overflow-y:auto;padding:16px 18px;display:none}
  .side-pane.on{display:block}
  .log-line{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;line-height:1.7;margin-bottom:10px;color:var(--text-dim)}
  .log-line .t{color:var(--dim-star);margin-right:6px}
  .log-line.tool{color:var(--violet)}
  .log-line.tool::before{content:"→ "}
  .file-row{display:flex;align-items:flex-start;gap:9px;padding:10px 0;border-bottom:1px solid var(--panel-line)}
  .file-row .sw{width:8px;height:8px;border-radius:50%;margin-top:5px;flex-shrink:0}
  .file-row .info{flex:1;min-width:0}
  .file-row .fname{font-size:12.5px;color:var(--text);word-break:break-all}
  .file-row .fmeta{font-family:ui-monospace,Consolas,monospace;font-size:10px;color:var(--text-dim);margin-top:2px}
  .file-row .facts{display:flex;gap:4px;flex-shrink:0}
  .file-row .facts button{background:none;border:1px solid var(--panel-line);color:var(--text-dim);width:24px;height:24px;border-radius:6px;cursor:pointer;font-size:11px}
  .file-row .facts button:hover{color:var(--text);border-color:var(--violet)}
  .legend{display:flex;gap:14px;font-family:ui-monospace,Consolas,monospace;font-size:10px;color:var(--text-dim);margin-bottom:14px;flex-wrap:wrap}
  .legend span{display:flex;align-items:center;gap:5px}
  .legend .sw{width:7px;height:7px;border-radius:50%}

  .overlay{position:fixed;inset:0;background:rgba(6,8,16,.7);display:none;align-items:center;justify-content:center;z-index:10}
  .overlay.on{display:flex}
  .editor{width:640px;max-width:90vw;background:var(--panel);border:1px solid var(--panel-line);border-radius:12px;overflow:hidden}
  .editor-head{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid var(--panel-line);font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--text-dim)}
  .editor textarea{width:100%;height:340px;background:var(--sky-deep);color:var(--text);border:none;outline:none;padding:16px;font-family:ui-monospace,Consolas,monospace;font-size:12.5px;line-height:1.6;resize:none}
  .editor-foot{display:flex;justify-content:flex-end;gap:8px;padding:12px 16px;border-top:1px solid var(--panel-line)}
  .editor-foot button{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;padding:8px 14px;border-radius:8px;cursor:pointer}
</style>
</head>
<body>

<div class="topbar">
  <a href="home.html" title="на главную">🏠</a>
  <a href="project-selector.html">← к проектам</a>
  <span class="title" id="projectTitle">Загрузка…</span>
</div>

<div class="tree" id="tree"></div>

<div class="chat">
  <div class="messages" id="messages"></div>
  <div class="composer">
    <div class="compose-attachments" id="composeAttachments"></div>
    <div class="upload-target-row">
      <span>папка для вложений:</span>
      <select id="uploadTargetSelect"></select>
    </div>
    <div class="compose-box">
      <button class="icon-btn" id="attachBtn" title="прикрепить файлы">📎</button>
      <textarea id="composeInput" rows="1" placeholder="Написать Hermes… (Ctrl+V — вставить изображение из буфера)"></textarea>
      <button class="send-btn" id="sendBtn" title="отправить">➤</button>
    </div>
    <input type="file" id="fileInput" multiple style="display:none">
  </div>
</div>

<div class="side">
  <div class="side-tabs">
    <button class="on" data-tab="activity">Активность агента</button>
    <button data-tab="files">Файлы</button>
  </div>
  <div class="side-pane on" id="pane-activity"></div>
  <div class="side-pane" id="pane-files"></div>
</div>

<div class="overlay" id="overlay">
  <div class="editor">
    <div class="editor-head"><span id="editorName"></span><span>txt/md редактор</span></div>
    <textarea id="editorText"></textarea>
    <div class="editor-foot">
      <button class="icon-btn" id="closeEditorBtn">Закрыть</button>
      <button class="send-btn" id="saveEditorBtn" style="width:auto;padding:0 16px">Сохранить</button>
    </div>
  </div>
</div>

<script src="app.js"></script>
<script>
let projectPath = null;
let chatSessionId = null;
let messages = [];
let currentTree = null;
let pendingAttachments = [];

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = String(s ?? '');
  return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// --- минимальный markdown-рендерер (заголовки, жирный, код, списки, таблицы) ---
function renderMD(src){
  const lines = src.trim().split('\n');
  let html = ''; let i = 0;
  const inline = s => s.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  while(i < lines.length){
    let line = lines[i];
    if(/^\s*$/.test(line)){ i++; continue; }
    if(/^#{1,3}\s+/.test(line)){
      const level = line.match(/^#+/)[0].length;
      html += `<h${level}>${inline(line.replace(/^#{1,3}\s+/,''))}</h${level}>`;
      i++; continue;
    }
    if(/^\|/.test(line)){
      const rows = [];
      while(i < lines.length && /^\|/.test(lines[i])){ rows.push(lines[i]); i++; }
      const cells = r => r.trim().replace(/^\||\|$/g,'').split('|').map(c=>c.trim());
      const head = cells(rows[0]);
      const body = rows.slice(2).map(cells);
      html += '<table><thead><tr>' + head.map(h=>`<th>${inline(h)}</th>`).join('') + '</tr></thead><tbody>' +
        body.map(r=>'<tr>'+r.map(c=>`<td>${inline(c)}</td>`).join('')+'</tr>').join('') + '</tbody></table>';
      continue;
    }
    if(/^[-*]\s+/.test(line)){
      const items = [];
      while(i < lines.length && /^[-*]\s+/.test(lines[i])){ items.push(lines[i].replace(/^[-*]\s+/,'')); i++; }
      html += '<ul>' + items.map(it=>`<li>${inline(it)}</li>`).join('') + '</ul>';
      continue;
    }
    const para = [line]; i++;
    while(i < lines.length && !/^\s*$/.test(lines[i]) && !/^#{1,3}\s+/.test(lines[i]) && !/^\|/.test(lines[i]) && !/^[-*]\s+/.test(lines[i])){
      para.push(lines[i]); i++;
    }
    html += `<p>${inline(para.join(' '))}</p>`;
  }
  return html;
}

const ATTACH_MARKER_RE = /\n\n📎 (.+)$/;

function splitAttachments(text) {
  const m = (text || '').match(ATTACH_MARKER_RE);
  if (!m) return { text: text || '', attachments: [] };
  return { text: text.slice(0, m.index), attachments: m[1].split(',').map(s => s.trim()).filter(Boolean) };
}

function bucketOf(relativePath) {
  if (relativePath.startsWith('source/') || relativePath === 'source') return 'source';
  if (relativePath.startsWith('outer/') || relativePath === 'outer') return 'outer';
  if (relativePath.startsWith('result/') || relativePath === 'result') return 'result';
  return '';
}

function iconFor(name) {
  if (/\.(png|jpe?g|gif|webp)$/i.test(name)) return '🖼️';
  if (/\.(md|txt)$/i.test(name)) return '📄';
  if (/\.html?$/i.test(name)) return '🌐';
  return '📎';
}

function formatTime(ts) {
  const d = new Date(ts);
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

function downloadFile(relativePath) {
  const params = new URLSearchParams({ path: projectPath, file: relativePath, download: '1' });
  window.open('/api/projects/file?' + params.toString(), '_blank');
}

function jumpToMessage(idx) {
  const target = document.getElementById('msg-' + idx);
  if (!target) return;
  target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  target.classList.remove('highlight-flash'); void target.offsetWidth;
  target.classList.add('highlight-flash');
  setTimeout(() => target.classList.remove('highlight-flash'), 1700);
}

function renderMessages() {
  const el = document.getElementById('messages');
  el.innerHTML = messages.map((m, idx) => {
    if (m.role !== 'user' && m.role !== 'assistant') return '';
    const { text, attachments } = splitAttachments(m.content);
    const attachRow = attachments.length
      ? `<div class="attach-row">${attachments.map(a => `<div class="attach-chip" data-download="${escapeHtml(a)}"><span class="sw ${bucketOf(a)}"></span>${escapeHtml(a.split('/').pop())}</div>`).join('')}</div>`
      : '';
    if (m.role === 'user') {
      return `<div class="msg user" id="msg-${idx}">${attachRow}<div class="bubble">${escapeHtml(text)}</div><div class="meta">${formatTime(m.timestamp)}</div></div>`;
    }
    return `<div class="msg agent" id="msg-${idx}">
      <div class="bubble"><div class="md-src" hidden>${escapeHtml(text)}</div><div class="md-rendered">${renderMD(text || '')}</div><button class="copy-btn">⧉ md</button></div>
      ${attachRow}
      <div class="meta">${formatTime(m.timestamp)}</div>
    </div>`;
  }).join('');

  document.querySelectorAll('.copy-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const src = btn.parentElement.querySelector('.md-src').textContent.trim();
      navigator.clipboard.writeText(src).then(() => {
        btn.textContent = '✓ скопировано'; btn.classList.add('copied');
        setTimeout(() => { btn.textContent = '⧉ md'; btn.classList.remove('copied'); }, 1500);
      });
    });
  });
  document.querySelectorAll('.attach-chip').forEach(chip => {
    chip.addEventListener('click', () => downloadFile(chip.dataset.download));
  });
  el.scrollTop = el.scrollHeight;
}

function computeFileMessageIndex(tree, msgs) {
  const bySource = {};
  msgs.forEach((m, idx) => {
    if (m.role !== 'user') return;
    splitAttachments(m.content).attachments.forEach(a => { bySource[a] = idx; });
  });

  const assistantMsgs = msgs
    .map((m, idx) => ({ idx, m }))
    .filter(x => x.m.role === 'assistant' && x.m.timestamp);

  function nearestFollowing(fileMtimeIso) {
    const fileTime = new Date(fileMtimeIso).getTime();
    let best = null, bestTime = null;
    for (const { idx, m } of assistantMsgs) {
      const t = new Date(m.timestamp).getTime();
      if (t >= fileTime && (best === null || t < bestTime)) { best = idx; bestTime = t; }
    }
    return best;
  }

  const nearest = {};
  ['outer', 'result'].forEach(bucket => {
    (tree[bucket] || []).forEach(entry => {
      if (bySource[entry.relative_path] === undefined) {
        const idx = nearestFollowing(entry.mtime);
        if (idx !== null) nearest[entry.relative_path] = idx;
      }
    });
  });
  return { bySource, nearest };
}

function renderFilesTab(tree, fileIndex) {
  const rows = [];
  (tree.root_files || []).forEach(f => rows.push({ relative_path: f.name, bucket: 'root', size: f.size, mtime: f.mtime }));
  ['source', 'outer', 'result'].forEach(bucket => (tree[bucket] || []).forEach(f => rows.push({ ...f, bucket })));
  rows.sort((a, b) => (a.mtime < b.mtime ? 1 : -1));

  const legend = `<div class="legend">
    <span><span class="sw" style="background:var(--c-source)"></span>source</span>
    <span><span class="sw" style="background:var(--c-outer)"></span>outer</span>
    <span><span class="sw" style="background:var(--c-result)"></span>result</span>
  </div>`;

  document.getElementById('pane-files').innerHTML = legend + rows.map(r => {
    const idx = r.bucket === 'source' ? fileIndex.bySource[r.relative_path] : fileIndex.nearest[r.relative_path];
    const swColor = r.bucket === 'root' ? 'var(--dim-star)' : `var(--c-${r.bucket})`;
    return `<div class="file-row"><span class="sw" style="background:${swColor}"></span>
      <div class="info"><div class="fname">${escapeHtml(r.relative_path)}</div><div class="fmeta">${escapeHtml(formatTime(r.mtime) || r.mtime)} · ${r.bucket} · ${r.size} B</div></div>
      <div class="facts">
        <button title="скачать" data-download="${escapeHtml(r.relative_path)}">⭳</button>
        ${idx !== undefined ? `<button title="к сообщению" data-jump-idx="${idx}">↩</button>` : ''}
      </div>
    </div>`;
  }).join('');

  document.querySelectorAll('#pane-files [data-download]').forEach(btn => btn.addEventListener('click', () => downloadFile(btn.dataset.download)));
  document.querySelectorAll('#pane-files [data-jump-idx]').forEach(btn => btn.addEventListener('click', () => jumpToMessage(Number(btn.dataset.jumpIdx))));
}

function buildFolderTree(entries, bucket) {
  const root = { folders: {}, files: [], path: bucket };
  for (const entry of entries) {
    const parts = entry.relative_path.split('/').slice(1);
    let node = root, accPath = bucket;
    for (let i = 0; i < parts.length - 1; i++) {
      accPath += '/' + parts[i];
      if (!node.folders[parts[i]]) node.folders[parts[i]] = { folders: {}, files: [], path: accPath };
      node = node.folders[parts[i]];
    }
    node.files.push({ name: parts[parts.length - 1], entry });
  }
  return root;
}

function renderFolderNode(node, bucketClass, depth) {
  let html = '';
  Object.keys(node.folders).sort().forEach(name => {
    const child = node.folders[name];
    html += `<div class="node folder-${bucketClass}" style="padding-left:${depth * 14}px">
      <span class="ic">📁</span><span class="name">${escapeHtml(name)}</span>
      <button class="new-folder-btn" data-parent="${escapeHtml(child.path)}" title="новая папка">＋</button>
    </div>`;
    html += renderFolderNode(child, bucketClass, depth + 1);
  });
  node.files.sort((a, b) => a.name.localeCompare(b.name)).forEach(f => {
    html += `<div class="node file folder-${bucketClass}" style="padding-left:${depth * 14 + 20}px" data-relpath="${escapeHtml(f.entry.relative_path)}">
      <span class="ic">${iconFor(f.name)}</span><span class="name">${escapeHtml(f.name)}</span>
    </div>`;
  });
  return html;
}

function renderTree(tree) {
  const labels = { source: '📥 source — от человека', outer: '🔎 outer — нашёл агент', result: '✨ result — сгенерировал агент' };
  let html = (tree.root_files || []).map(f =>
    `<div class="node file" data-relpath="${escapeHtml(f.name)}"><span class="ic">📄</span><span class="name">${escapeHtml(f.name)}</span></div>`
  ).join('');

  ['source', 'outer', 'result'].forEach(bucket => {
    html += `<div class="glabel">${labels[bucket]}<button class="new-folder-btn" data-parent="${bucket}" title="новая папка">＋папка</button></div>`;
    html += renderFolderNode(buildFolderTree(tree[bucket] || [], bucket), bucket, 0);
  });

  document.getElementById('tree').innerHTML = html;

  document.querySelectorAll('.tree .node.file').forEach(n => {
    n.addEventListener('click', () => {
      const relpath = n.dataset.relpath;
      if (/\.(md|txt)$/i.test(relpath)) openEditor(relpath);
      else downloadFile(relpath);
    });
  });
  document.querySelectorAll('.new-folder-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const name = prompt('Имя новой папки:');
      if (!name) return;
      const resp = await apiFetch('/api/projects/mkdir', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: projectPath, parent: btn.dataset.parent, name }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        alert('Не удалось создать папку: ' + (body.error || resp.status));
        return;
      }
      await refreshTreeAndFiles();
    });
  });
}

function renderFolderOptions(tree) {
  const select = document.getElementById('uploadTargetSelect');
  const options = [];
  ['source', 'outer', 'result'].forEach(bucket => {
    options.push(bucket);
    const dirs = new Set();
    (tree[bucket] || []).forEach(e => {
      const parts = e.relative_path.split('/');
      for (let i = 1; i < parts.length - 1; i++) dirs.add(parts.slice(0, i + 1).join('/'));
    });
    [...dirs].sort().forEach(d => options.push(d));
  });
  const previous = select.value;
  select.innerHTML = options.map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('');
  if (options.includes(previous)) select.value = previous;
}

async function loadTreeAndRender() {
  const resp = await apiFetch('/api/projects/tree?' + new URLSearchParams({ path: projectPath }));
  if (resp.status === 401) { location.href = 'login.html'; return null; }
  currentTree = await resp.json();
  renderTree(currentTree);
  renderFolderOptions(currentTree);
  return currentTree;
}

async function refreshTreeAndFiles() {
  await loadTreeAndRender();
  if (!currentTree) return;
  renderFilesTab(currentTree, computeFileMessageIndex(currentTree, messages));
}

async function openEditor(relpath) {
  const resp = await apiFetch('/api/projects/file?' + new URLSearchParams({ path: projectPath, file: relpath }));
  if (!resp.ok) { alert('Не удалось открыть файл'); return; }
  document.getElementById('editorName').textContent = relpath;
  document.getElementById('editorText').value = await resp.text();
  document.getElementById('overlay').classList.add('on');
  document.getElementById('saveEditorBtn').onclick = () => saveEditor(relpath);
}

async function saveEditor(relpath) {
  const content = document.getElementById('editorText').value;
  const resp = await apiFetch('/api/projects/file', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: projectPath, file: relpath, content }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    alert('Не удалось сохранить: ' + (body.error || resp.status));
    return;
  }
  document.getElementById('overlay').classList.remove('on');
  await refreshTreeAndFiles();
}

document.getElementById('closeEditorBtn').addEventListener('click', () => document.getElementById('overlay').classList.remove('on'));

function clearActivity() { document.getElementById('pane-activity').innerHTML = ''; }

function appendActivity(name, payload) {
  const el = document.getElementById('pane-activity');
  const line = document.createElement('div');
  line.className = 'log-line' + (name.startsWith('tool.') ? ' tool' : '');
  const time = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const desc = payload && payload.tool_name ? `${name} — ${payload.tool_name}` : name;
  line.innerHTML = `<span class="t">${time}</span>${escapeHtml(desc)}`;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

async function uploadPending(files, targetDir) {
  for (const file of files) {
    const form = new FormData();
    form.append('path', projectPath);
    form.append('target_dir', targetDir);
    form.append('file', file, file.name);
    const resp = await apiFetch('/api/projects/upload', { method: 'POST', body: form });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      alert('Не удалось загрузить ' + file.name + ': ' + (body.error || resp.status));
      continue;
    }
    const body = await resp.json();
    pendingAttachments.push({ relative_path: body.relative_path });
    const url = URL.createObjectURL(file);
    const div = document.createElement('div');
    div.className = 'thumb';
    div.title = body.relative_path;
    div.style.backgroundImage = `url(${url})`;
    document.getElementById('composeAttachments').appendChild(div);
  }
}

async function sendMessage() {
  const input = document.getElementById('composeInput');
  const text = input.value.trim();
  if (!text && pendingAttachments.length === 0) return;
  input.value = '';

  let fullText = text;
  if (pendingAttachments.length) fullText += `\n\n📎 ${pendingAttachments.map(a => a.relative_path).join(', ')}`;
  pendingAttachments = [];
  document.getElementById('composeAttachments').innerHTML = '';

  messages.push({ role: 'user', content: fullText, timestamp: new Date().toISOString() });
  const assistantIdx = messages.length;
  messages.push({ role: 'assistant', content: '', timestamp: new Date().toISOString() });
  renderMessages();
  clearActivity();

  const resp = await apiFetch(`/api/chat/${encodeURIComponent(chatSessionId)}/send`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: fullText }),
  });
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) {
    messages[assistantIdx].content = 'Hermes временно недоступен, попробуйте ещё раз';
    renderMessages();
    return;
  }
  await readSSE(resp, (name, payload) => {
    if (name === 'assistant.delta') { messages[assistantIdx].content += payload.delta || ''; renderMessages(); }
    else if (name === 'assistant.completed' && payload.content) { messages[assistantIdx].content = payload.content; renderMessages(); }
    else if (name === 'error') { messages[assistantIdx].content = `Ошибка: ${payload.message || 'неизвестная'}`; renderMessages(); }
    else if (name !== 'done') { appendActivity(name, payload); }
  });
  await refreshTreeAndFiles();
}

document.getElementById('sendBtn').addEventListener('click', sendMessage);
document.getElementById('composeInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

const fileInput = document.getElementById('fileInput');
document.getElementById('attachBtn').addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', async () => {
  await uploadPending([...fileInput.files], document.getElementById('uploadTargetSelect').value || 'source');
  fileInput.value = '';
});
document.getElementById('composeInput').addEventListener('paste', async (e) => {
  const items = e.clipboardData ? e.clipboardData.items : [];
  const files = [];
  for (const it of items) if (it.type.startsWith('image/')) files.push(it.getAsFile());
  if (files.length) await uploadPending(files, document.getElementById('uploadTargetSelect').value || 'source');
});

document.querySelectorAll('.side-tabs button').forEach(b => {
  b.addEventListener('click', () => {
    document.querySelectorAll('.side-tabs button').forEach(x => x.classList.remove('on'));
    document.querySelectorAll('.side-pane').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    document.getElementById('pane-' + b.dataset.tab).classList.add('on');
  });
});

(async () => {
  const me = await requireAuth();
  if (!me) return;
  const requestedPath = new URLSearchParams(location.search).get('path');
  if (!requestedPath) { location.href = 'project-selector.html'; return; }

  const openResp = await apiFetch('/api/projects/open', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: requestedPath }),
  });
  if (openResp.status === 401) { location.href = 'login.html'; return; }
  if (!openResp.ok) { alert('Проект не найден'); location.href = 'project-selector.html'; return; }
  const openBody = await openResp.json();
  chatSessionId = openBody.chat_session_id;
  projectPath = openBody.project_path;
  document.getElementById('projectTitle').textContent = projectPath;

  const histResp = await apiFetch(`/api/chat/${encodeURIComponent(chatSessionId)}/messages`);
  if (histResp.ok) {
    const histBody = await histResp.json();
    messages = histBody.data.filter(m => m.role === 'user' || m.role === 'assistant');
  }
  renderMessages();
  await refreshTreeAndFiles();
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Проверить вручную (нет backend-юнит-тестов у чистого JS без сборщика — как и у `chat.html`/`project-selector.html` из прошлых срезов)**

Запустить локально `hermes-web` (см. `docs/state.md`/README прошлых
срезов — обычно `venv/bin/python run.py` с тестовым `.env`), открыть
`project-selector.html`, кликнуть «Открыть проект →» на любом
существующем проекте (например мигрированном `physics-tasks` из
Task-примеров тестов или локально созданном через «Быстрый чат»).

Expected:
- Открывается `project-workspace.html?path=...`, заголовок показывает
  путь проекта, история чата (если была) подгружается.
- Дерево слева показывает `about.md` (и `AGENTS.md`/`history.md`, если
  есть) плюс пустые `source`/`outer`/`result` с кнопками «＋папка».
- Создание папки в `source`, загрузка файла в неё (через 📎 или
  Ctrl+V), отправка сообщения — файл появляется во вкладке «Файлы»,
  чат показывает `attach-row` с чипом.
- Во время ответа агента вкладка «Активность агента» показывает
  `tool.*`/`run.*` события живьём.
- Клик по `.md`/`.txt` в дереве открывает редактор; «Сохранить»
  реально пишет файл (проверить `cat` на диске).

- [ ] **Step 3: Commit**

```bash
git add hermes-web/static/project-workspace.html
git commit -m "feat(hermes-web): рабочий экран проекта на реальном API"
```

---

## Task 9: Деплой на VPS, приёмочный тест, обновление памяти проекта

**Files:**
- Нет изменений кода — деплой существующего `hermes-web/` (уже
  разворачивается `rsync`, без `git` на проде — см. предыдущие срезы).
- Modify: `docs/state.md`, `docs/changelog.md` (после успешной приёмки).

- [ ] **Step 1: Прогнать весь тестовый набор локально перед деплоем**

Run: `cd hermes-web && venv/bin/pytest tests/ -v` (и, если venv отдельно
собран под интерпретатор сервера — тот же набор им, как в прошлых
срезах)

Expected: PASS, весь пакет (учитывая уже существовавшие тесты `project_
index`/`hermes-web` из срезов A/1+2/3ч1 — ничего не сломано)

- [ ] **Step 2: Задеплоить на VPS**

```bash
rsync -avz --exclude '__pycache__' --exclude '.pytest_cache' \
  hermes-web/ hermes@212.115.55.116:~/hermes-web/
ssh hermes@212.115.55.116 'systemctl --user restart hermes-web.service'
```

- [ ] **Step 3: Ручной приёмочный тест на `hermes.blackboxbegin.space`**

1. Открыть уже существующий (`physics-tasks`, мигрированный в срезе A)
   и созданный «Быстрым чатом» проекты через `project-selector.html` →
   «Открыть проект →» — убедиться, что видна прежняя история (если
   была) и дерево файлов.
2. Создать подпапку в `source` (например с фамилией автора учебника —
   реальный сценарий заказчика из брейнсторма), загрузить в неё файл,
   отправить сообщение с этим вложением, убедиться что агент реально
   видит файл (например, просит его проанализировать) — проверить в
   реальном ответе Hermes.
3. Понаблюдать за панелью «Активность агента» вживую во время ответа —
   tool-вызовы должны появляться по мере выполнения.
4. Отредактировать и сохранить `about.md` через оверлей-редактор,
   убедиться что переиндексация прошла (например, через RAG-поиск на
   `project-selector.html` или проверкой `updated_at` в детальной
   панели).
5. Перезагрузить страницу — убедиться что дерево и история сохранились,
   а «Активность агента» очистилась (ожидаемое эфемерное поведение).
6. Если что-то ведёт себя не так — `superpowers:systematic-debugging`,
   начиная с `journalctl --user -u hermes-web.service -n 50` и
   `journalctl --user -u hermes-gateway.service -n 50` на сервере.

- [ ] **Step 4: Обновить `docs/state.md` и `docs/changelog.md`**

Отметить срез 3 часть 2 как реализованный и выкаченный (по образцу
записей для срезов A/1+2/3ч1 в `docs/state.md`), перенести «Следующий
шаг» на под-проект C (админ-панель) — по уже зафиксированному порядку
в коммите `b826010`.

- [ ] **Step 5: Снимок в git**

```bash
bash scripts/snapshot.sh "hermes-web: срез 3 часть 2 (рабочий экран проекта) реализован и выкачен"
```
