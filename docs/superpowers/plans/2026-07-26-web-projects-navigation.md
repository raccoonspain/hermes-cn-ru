# Веб-бэкенд Hermes — навигация по проектам (срез 3, часть 1) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать и выкатить на VPS экран «Работа с проектами» (`project-selector.html`) — список Групп слева, отфильтрованный список Проектов справа (по умолчанию: не старше месяца + `active`), RAG-поиск, панель `about.md`, создание/редактирование/закрепление групп, перенос проекта между группами.

**Architecture:** Расширяем уже задеплоенный плагин `project_index` (`hermes-plugins/project_index/`) быстрой SQL-фильтрацией по времени активности и статусу вместо обхода диска — таблица `projects` получает колонку `description`, `updated_at` начинает означать mtime `about.md`, а не время индексации. Новый модуль `hermes_web/projects.py` в уже существующем пакете `hermes-web` — бизнес-логика Групп/Проектов (слаги, фильтры, обёртки над `project_index.core`), параллельно уже существующему `quickchat.py`. Новые маршруты в уже существующем `app.py`. Новая статика `project-selector.html` (адаптация кликабельного макета `/result/project-selector.html` под реальные эндпоинты) + включение двух плиток в уже задеплоенном `home.html`.

**Tech Stack:** То же самое, что и в срезе 1+2 — Python 3.11 (венв Hermes на сервере) / 3.12 (локально), `aiohttp`, `pytest` + `pytest-aiohttp`, без сборщика на фронте.

## Global Constraints

Точные значения — копия из спека (`docs/superpowers/specs/2026-07-26-web-projects-navigation-design.md`), обязательны для всех задач ниже:

- `project_index/storage.py`: таблица `projects` получает колонку `description TEXT NOT NULL DEFAULT ''` через `ALTER TABLE` при отсутствии (существующий `index.db` на сервере нельзя дропать — там реальные данные).
- `project_index/core.py`: `index_update` пишет в `updated_at` значение `os.path.getmtime(about.md)` (переведённое в ISO через `datetime.utcfromtimestamp`), а не время вызова функции. Повторный вызов без изменения файла не должен менять `updated_at`.
- `parse_about_md` дополнительно извлекает `points` («Опорные точки») и `now` («На чём остановились») — обе необязательные, по умолчанию `""`, в отличие от `title`/`description` (их отсутствие — `ProjectIndexError`, как и раньше).
- Новые функции `project_index/core.py`: `list_projects_for_user(user, workspace_root=WORKSPACE_ROOT, db_path=DB_PATH, updated_since: str | None = None, status: str | None = None, group: str | None = None)` (чтение только из SQL, `updated_since` — ISO-строка нижней границы `updated_at`, включительно; `status=None`/`group=None`/`group="*"` — без фильтра) и `get_project_detail(user, project_path, workspace_root=WORKSPACE_ROOT)` (единственное место, где `about.md` читается с диска в этом срезе, только по явному запросу одного проекта).
- Новая таблица `hermes-web.db`: `group_meta(user, slug, display_name, emoji, pinned, created_at)`, `PRIMARY KEY (user, slug)`. `slug` = имя папки на диске, никогда не переименовывается редактированием.
- Диапазоны времени (query-параметр `since`, дни от текущего момента): `week`=7, `month`=30, `quarter`=90, `half_year`=182, `year`=365, `all`=без фильтра.
- API-эндпоинты `hermes-web` (все под активной веб-сессией, 401 без неё — уже готовый `auth_middleware`/`_require_user` из среза 1+2):
  `GET /api/groups`, `POST /api/groups {name, emoji}`, `PUT /api/groups/{slug} {display_name?, emoji?, pinned?}`,
  `GET /api/projects?group=&since=&status=` (дефолты на сервере: `group=*`, `since=month`, `status=active`),
  `GET /api/projects/detail?path=`, `POST /api/projects/search {query}`, `POST /api/projects/move {path, new_group?, new_name?}`.
- Фронтенд всегда явно шлёт `since=month&status=active` при первой загрузке страницы (двойная защита вместе с серверным дефолтом).
- `move_project`/`search_similar`/`index_update` внутри `project_index.core` синхронные и могут дойти до реального HTTP-вызова (эмбеддинг через wormsoft.ru) — при вызове из `hermes-web`'s async-хендлеров всегда через `loop.run_in_executor` (тот же паттерн, что уже применён в `quickchat.create_quick_chat` после финального ревью среза 1+2), иначе однопоточный aiohttp-процесс замораживается для всех пользователей разом.
- Полноценный `project-workspace.html` — вне рамок; кнопка «Открыть проект →» — плейсхолдер (`alert`), без перехода.
- Тесты — `pytest`, локальный венв `/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv` (уже создан и содержит `aiohttp==3.14.1`, `argon2-cffi==25.1.0`, `pytest==9.0.2`, `pytest-aiohttp==1.1.0`, `pytest-asyncio==1.4.0`, `PyYAML==6.0.3` — ничего доустанавливать не нужно). `PROJECT_INDEX_PLUGIN_DIR` уже проставляется тестовым `conftest.py` обоих пакетов (`hermes-plugins/tests/conftest.py`, `hermes-web/tests/conftest.py`).
- Деплой — `rsync`, без `git` на проде (как и раньше). Изменения в `project_index` требуют перезапуска `hermes-gateway.service` (плагин живёт внутри процесса гейтвея); изменения в `hermes-web` — перезапуска `hermes-web.service`.

---

## Task 1: `project_index` — фильтруемый листинг, `description`, mtime как `updated_at`

**Files:**
- Modify: `hermes-plugins/project_index/storage.py`
- Modify: `hermes-plugins/project_index/core.py`
- Test: `hermes-plugins/tests/test_storage.py`
- Test: `hermes-plugins/tests/test_core.py`

**Interfaces:**
- Consumes: ничего нового извне — расширяет уже существующие `parse_about_md`/`index_update`/`search_similar`/`resolve_project_path` (все в `core.py`, уже задеплоены).
- Produces: `storage.upsert_project(conn, path, title, tags, status, embedding, updated_at, description="")` (новый последний параметр, с дефолтом — существующие позиционные вызовы не ломаются), `storage.list_projects_filtered(conn, workspace_root, user, updated_since=None, status=None, group=None) -> list[dict]`, `core.list_projects_for_user(user, workspace_root=WORKSPACE_ROOT, db_path=DB_PATH, updated_since=None, status=None, group=None) -> list[dict]` (каждый элемент — `path/title/description/tags/status/updated_at/group`), `core.get_project_detail(user, project_path, workspace_root=WORKSPACE_ROOT) -> dict` (`title/description/points/now/tags/status/path/group`). Используются в Task 3 (`hermes_web/projects.py`).

- [ ] **Step 1: Написать падающие тесты в `hermes-plugins/tests/test_storage.py`** (дописать в конец файла)

```python
def test_upsert_project_stores_description(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(
        conn, "/p/a", "т", [], "active", None, "2026-01-01T00:00:00", description="краткое описание",
    )
    row = storage.get_project(conn, "/p/a")
    assert row["description"] == "краткое описание"


def test_upsert_project_description_defaults_to_empty_string(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/p/a", "т", [], "active", None, "2026-01-01T00:00:00")
    row = storage.get_project(conn, "/p/a")
    assert row["description"] == ""


def test_init_db_migrates_existing_table_without_description_column(tmp_path):
    import sqlite3

    db_path = str(tmp_path / "index.db")
    old_conn = sqlite3.connect(db_path)
    old_conn.execute(
        """
        CREATE TABLE projects (
            path TEXT PRIMARY KEY, title TEXT NOT NULL, tags TEXT NOT NULL,
            status TEXT NOT NULL, embedding BLOB, updated_at TEXT NOT NULL
        )
        """
    )
    old_conn.execute(
        "INSERT INTO projects (path, title, tags, status, embedding, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("/p/a", "старый", "[]", "active", None, "2026-01-01T00:00:00"),
    )
    old_conn.commit()
    old_conn.close()

    conn = storage.get_connection(db_path)
    row = storage.get_project(conn, "/p/a")
    assert row["title"] == "старый"
    assert row["description"] == ""


def test_list_projects_filtered_by_status(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/a", "a", [], "active", None, "2026-01-01T00:00:00")
    storage.upsert_project(conn, "/workspace/dem/ALL/b", "b", [], "archived", None, "2026-01-01T00:00:00")
    result = storage.list_projects_filtered(conn, "/workspace", "dem", status="active")
    assert {p["path"] for p in result} == {"/workspace/dem/ALL/a"}


def test_list_projects_filtered_by_updated_since(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/old", "old", [], "active", None, "2020-01-01T00:00:00")
    storage.upsert_project(conn, "/workspace/dem/ALL/new", "new", [], "active", None, "2026-07-01T00:00:00")
    result = storage.list_projects_filtered(conn, "/workspace", "dem", updated_since="2026-01-01T00:00:00")
    assert {p["path"] for p in result} == {"/workspace/dem/ALL/new"}


def test_list_projects_filtered_by_group(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/a", "a", [], "active", None, "t")
    storage.upsert_project(conn, "/workspace/dem/1С/b", "b", [], "active", None, "t")
    result = storage.list_projects_filtered(conn, "/workspace", "dem", group="ALL")
    assert {p["path"] for p in result} == {"/workspace/dem/ALL/a"}


def test_list_projects_filtered_group_star_means_everywhere(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/a", "a", [], "active", None, "t")
    storage.upsert_project(conn, "/workspace/dem/1С/b", "b", [], "active", None, "t")
    result = storage.list_projects_filtered(conn, "/workspace", "dem", group="*")
    assert {p["path"] for p in result} == {"/workspace/dem/ALL/a", "/workspace/dem/1С/b"}


def test_list_projects_filtered_scoped_to_user(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/a", "a", [], "active", None, "t")
    storage.upsert_project(conn, "/workspace/rost/ALL/b", "b", [], "active", None, "t")
    result = storage.list_projects_filtered(conn, "/workspace", "dem")
    assert {p["path"] for p in result} == {"/workspace/dem/ALL/a"}
```

- [ ] **Step 2: Запустить — убедиться, что падают**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-plugins/tests/test_storage.py -v
```

Expected: `TypeError` на `description=` (неизвестный аргумент) и `AttributeError: module 'project_index.storage' has no attribute 'list_projects_filtered'`.

- [ ] **Step 3: Править `hermes-plugins/project_index/storage.py`**

В `init_db`, сразу после `CREATE TABLE IF NOT EXISTS projects (...)` и перед `conn.commit()`:

```python
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(projects)")}
    if "description" not in existing_cols:
        conn.execute("ALTER TABLE projects ADD COLUMN description TEXT NOT NULL DEFAULT ''")
```

Заменить сигнатуру и тело `upsert_project`:

```python
def upsert_project(
    conn: sqlite3.Connection,
    path: str,
    title: str,
    tags: list,
    status: str,
    embedding: Optional[list],
    updated_at: str,
    description: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO projects (path, title, tags, status, embedding, updated_at, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            title=excluded.title,
            tags=excluded.tags,
            status=excluded.status,
            embedding=excluded.embedding,
            updated_at=excluded.updated_at,
            description=excluded.description
        """,
        (
            path,
            title,
            json.dumps(tags, ensure_ascii=False),
            status,
            pack_embedding(embedding) if embedding is not None else None,
            updated_at,
            description,
        ),
    )
    conn.commit()
```

В `_row_to_dict` добавить `"description": row["description"],` (любая строка после `"title": row["title"],` подходит).

Добавить `import os` в начало файла (нужен на следующем шаге для `list_projects_filtered`).

Добавить в конец файла:

```python
def list_projects_filtered(
    conn: sqlite3.Connection,
    workspace_root: str,
    user: str,
    updated_since: Optional[str] = None,
    status: Optional[str] = None,
    group: Optional[str] = None,
) -> list:
    query = "SELECT * FROM projects"
    clauses = []
    params: list = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if updated_since:
        clauses.append("updated_at >= ?")
        params.append(updated_since)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    rows = [_row_to_dict(r) for r in conn.execute(query, params).fetchall()]

    user_prefix = f"{os.path.realpath(workspace_root).rstrip('/')}/{user}/"
    rows = [r for r in rows if r["path"].startswith(user_prefix)]
    if group and group != "*":
        group_prefix = f"{user_prefix}{group}/"
        rows = [r for r in rows if r["path"].startswith(group_prefix)]
    return rows
```

- [ ] **Step 4: Запустить — тесты `test_storage.py` должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-plugins/tests/test_storage.py -v
```

Expected: все тесты, включая уже существующие, `passed` (12 старых + 6 новых = 18).

- [ ] **Step 5: Написать падающие тесты в `hermes-plugins/tests/test_core.py`** (дописать в конец файла; добавить `import datetime` в импорты наверху файла, если его там ещё нет)

```python
def test_parse_about_md_extracts_points_and_now():
    result = core.parse_about_md(ABOUT_MD_FULL)
    assert result["points"] == "- начали с чистого листа"
    assert result["now"] == "Заказали цемент"


def test_parse_about_md_missing_points_and_now_default_to_empty_string():
    result = core.parse_about_md(ABOUT_MD_NO_FRONTMATTER)
    assert result["points"] == ""
    assert result["now"] == ""


def test_index_update_uses_about_md_mtime_not_call_time(tmp_path):
    project_dir = _write_project(tmp_path, "dem/ALL/proj")
    about_path = project_dir / "about.md"
    fixed_mtime = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
    os.utime(about_path, (fixed_mtime, fixed_mtime))
    db_path = str(tmp_path / "index.db")

    result = core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path)

    conn = core.storage.get_connection(db_path)
    row = core.storage.get_project(conn, result["path"])
    assert row["updated_at"].startswith("2020-01-01")


def test_index_update_repeated_call_without_change_keeps_updated_at(tmp_path):
    project_dir = _write_project(tmp_path, "dem/ALL/proj")
    fixed_mtime = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
    os.utime(project_dir / "about.md", (fixed_mtime, fixed_mtime))
    db_path = str(tmp_path / "index.db")

    core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path)
    result = core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path)

    conn = core.storage.get_connection(db_path)
    row = core.storage.get_project(conn, result["path"])
    assert row["updated_at"].startswith("2020-01-01")


def test_index_update_stores_description(tmp_path):
    _write_project(tmp_path, "dem/ALL/proj")
    db_path = str(tmp_path / "index.db")
    result = core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path)
    conn = core.storage.get_connection(db_path)
    row = core.storage.get_project(conn, result["path"])
    assert row["description"] == "Ведём таблицу закупок и остатков по стройке гаража"


def test_list_projects_for_user_includes_group_and_description(tmp_path):
    _write_project(tmp_path, "dem/ALL/a")
    _write_project(tmp_path, "dem/1С/b")
    db_path = str(tmp_path / "index.db")
    core.index_update("dem", "dem/ALL/a", workspace_root=str(tmp_path), db_path=db_path)
    core.index_update("dem", "dem/1С/b", workspace_root=str(tmp_path), db_path=db_path)

    result = core.list_projects_for_user("dem", workspace_root=str(tmp_path), db_path=db_path)
    by_group = {p["group"] for p in result}
    assert by_group == {"ALL", "1С"}
    assert all(p["description"] == "Ведём таблицу закупок и остатков по стройке гаража" for p in result)


def test_list_projects_for_user_filters_by_since_and_status(tmp_path):
    old_dir = _write_project(tmp_path, "dem/ALL/old")
    _write_project(tmp_path, "dem/ALL/new")
    db_path = str(tmp_path / "index.db")
    old_mtime = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
    os.utime(old_dir / "about.md", (old_mtime, old_mtime))
    core.index_update("dem", "dem/ALL/old", workspace_root=str(tmp_path), db_path=db_path)
    core.index_update("dem", "dem/ALL/new", workspace_root=str(tmp_path), db_path=db_path)

    result = core.list_projects_for_user(
        "dem", workspace_root=str(tmp_path), db_path=db_path, updated_since="2025-01-01T00:00:00",
    )
    assert {p["path"] for p in result} == {str(tmp_path / "dem" / "ALL" / "new")}


def test_get_project_detail_includes_points_now_and_group(tmp_path):
    _write_project(tmp_path, "dem/ALL/proj")
    detail = core.get_project_detail("dem", "dem/ALL/proj", workspace_root=str(tmp_path))
    assert detail["title"] == "Учёт стройматериалов для гаража"
    assert detail["points"] == "- начали с чистого листа"
    assert detail["now"] == "Заказали цемент"
    assert detail["group"] == "ALL"
    assert detail["path"] == str(tmp_path / "dem" / "ALL" / "proj")


def test_get_project_detail_rejects_other_user(tmp_path):
    (tmp_path / "dem").mkdir()
    _write_project(tmp_path, "rost/ALL/proj")
    with pytest.raises(core.ProjectIndexError):
        core.get_project_detail("dem", "rost/ALL/proj", workspace_root=str(tmp_path))


def test_search_similar_includes_group(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/proj")
    db_path = str(tmp_path / "index.db")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: [1.0, 0.0])
    core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path, api_key="key")

    result = core.search_similar("dem", "гараж", workspace_root=str(tmp_path), db_path=db_path, api_key="key")
    assert result["results"][0]["group"] == "ALL"
```

- [ ] **Step 6: Запустить — убедиться, что новые тесты падают, старые ещё проходят**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-plugins/tests/test_core.py -v
```

Expected: новые тесты `FAILED`/`ERROR` (`AttributeError`/неверный `updated_at`), уже существующие — `passed`.

- [ ] **Step 7: Править `hermes-plugins/project_index/core.py`**

Добавить константы рядом с `_TITLE_SECTION`/`_DESCRIPTION_SECTION`:

```python
_POINTS_SECTION = "Опорные точки"
_NOW_SECTION = "На чём остановились"
```

В `parse_about_md`, после строк `title = ...`/`description = ...`, добавить:

```python
    points = sections.get(_POINTS_SECTION, "").strip()
    now = sections.get(_NOW_SECTION, "").strip()
```

И расширить возвращаемый словарь:

```python
    return {
        "title": title,
        "description": description,
        "points": points,
        "now": now,
        "tags": list(frontmatter.get("tags") or []),
        "status": str(frontmatter.get("status") or "active"),
    }
```

Добавить новую приватную функцию рядом с `_read_about`:

```python
def _project_group(user: str, workspace_root: str, path: str) -> str:
    root = os.path.realpath(workspace_root)
    rel = os.path.relpath(path, os.path.join(root, user))
    return rel.split(os.sep)[0]
```

В `index_update` заменить строку `updated_at=datetime.datetime.utcnow().isoformat(),` (внутри вызова `storage.upsert_project`) на вычисление из mtime **перед** вызовом `storage.upsert_project`, и передать `description`:

```python
    updated_at = datetime.datetime.utcfromtimestamp(
        os.path.getmtime(_about_md_path(resolved))
    ).isoformat()

    conn = storage.get_connection(db_path)
    try:
        storage.upsert_project(
            conn,
            path=resolved,
            title=about["title"],
            description=about["description"],
            tags=about["tags"],
            status=about["status"],
            embedding=embedding,
            updated_at=updated_at,
        )
    finally:
        conn.close()
```

(Полностью заменяет прежний блок `conn = storage.get_connection(db_path) ... conn.close()` внутри `index_update` — тело функции до и после этого блока не меняется.)

В `search_similar`, заменить `return {"results": results, "message": ""}` на:

```python
    results = [{**r, "group": _project_group(user, workspace_root, r["path"])} for r in results]
    return {"results": results, "message": ""}
```

Добавить в конец файла:

```python
def list_projects_for_user(
    user: str,
    workspace_root: str = WORKSPACE_ROOT,
    db_path: str = DB_PATH,
    updated_since: Optional[str] = None,
    status: Optional[str] = None,
    group: Optional[str] = None,
) -> list:
    conn = storage.get_connection(db_path)
    try:
        rows = storage.list_projects_filtered(
            conn, workspace_root, user, updated_since=updated_since, status=status, group=group,
        )
    finally:
        conn.close()
    return [{**r, "group": _project_group(user, workspace_root, r["path"])} for r in rows]


def get_project_detail(user: str, project_path: str, workspace_root: str = WORKSPACE_ROOT) -> dict:
    resolved = resolve_project_path(user, project_path, workspace_root)
    about = _read_about(resolved)
    return {**about, "path": resolved, "group": _project_group(user, workspace_root, resolved)}
```

- [ ] **Step 8: Запустить полный набор `project_index` — всё должно пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-plugins/tests/ -v
```

Expected: все тесты `passed` (существующие + ~18 новых в `test_storage.py`/`test_core.py`).

- [ ] **Step 9: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-plugins/
git commit -m "feat(project_index): фильтруемый листинг проектов, description в индексе, updated_at = mtime about.md"
```

---

## Task 2: `hermes-web/storage.py` — метаданные групп

**Files:**
- Modify: `hermes-web/hermes_web/storage.py`
- Test: `hermes-web/tests/test_storage.py`

**Interfaces:**
- Produces: `get_group_meta(conn, user, slug) -> dict | None`, `upsert_group_meta(conn, user, slug, display_name, emoji, pinned, created_at) -> None`, `list_group_meta(conn, user) -> list[dict]`, `update_chat_session_project_path(conn, old_path, new_path) -> None`. Используются в Task 3 (`projects.py`).

- [ ] **Step 1: Написать падающие тесты** (дописать в конец `hermes-web/tests/test_storage.py`)

```python
def test_group_meta_missing_returns_none(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    assert storage.get_group_meta(conn, "dem", "dom-i-remont") is None


def test_group_meta_roundtrip(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.upsert_group_meta(conn, "dem", "dom-i-remont", "Дом и ремонт", "🏠", True, created_at="2026-07-26T10:00:00")
    row = storage.get_group_meta(conn, "dem", "dom-i-remont")
    assert row["display_name"] == "Дом и ремонт"
    assert row["emoji"] == "🏠"
    assert bool(row["pinned"]) is True


def test_upsert_group_meta_updates_existing_row(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.upsert_group_meta(conn, "dem", "it", "IT", "🖥️", False, created_at="2026-07-26T10:00:00")
    storage.upsert_group_meta(conn, "dem", "it", "IT / DevOps", "🖥️", True, created_at="2026-07-26T10:00:00")
    row = storage.get_group_meta(conn, "dem", "it")
    assert row["display_name"] == "IT / DevOps"
    assert bool(row["pinned"]) is True


def test_list_group_meta_scoped_to_user(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.upsert_group_meta(conn, "dem", "it", "IT", "🖥️", False, created_at="t")
    storage.upsert_group_meta(conn, "rost", "eng", "Английский", "🇬🇧", False, created_at="t")
    rows = storage.list_group_meta(conn, "dem")
    assert [r["slug"] for r in rows] == ["it"]


def test_update_chat_session_project_path_moves_reference(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/old/path", "web_1", created_at=1.0)
    storage.update_chat_session_project_path(conn, "/old/path", "/new/path")
    row = storage.get_chat_session(conn, "chat1")
    assert row["project_path"] == "/new/path"


def test_update_chat_session_project_path_noop_when_no_match(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    storage.create_chat_session(conn, "chat1", "dem", "/old/path", "web_1", created_at=1.0)
    storage.update_chat_session_project_path(conn, "/other/path", "/new/path")
    row = storage.get_chat_session(conn, "chat1")
    assert row["project_path"] == "/old/path"
```

- [ ] **Step 2: Запустить — убедиться, что падают**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_storage.py -v
```

Expected: `AttributeError` на отсутствующие функции.

- [ ] **Step 3: Править `hermes-web/hermes_web/storage.py`**

В `init_db`, перед финальным `conn.commit()`, добавить создание новой таблицы:

```python
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS group_meta (
            user TEXT NOT NULL,
            slug TEXT NOT NULL,
            display_name TEXT NOT NULL,
            emoji TEXT NOT NULL DEFAULT '',
            pinned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user, slug)
        )
        """
    )
```

Добавить в конец файла:

```python
def get_group_meta(conn: sqlite3.Connection, user: str, slug: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM group_meta WHERE user = ? AND slug = ?", (user, slug)
    ).fetchone()
    return dict(row) if row else None


def upsert_group_meta(
    conn: sqlite3.Connection, user: str, slug: str, display_name: str, emoji: str, pinned: bool, created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO group_meta (user, slug, display_name, emoji, pinned, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user, slug) DO UPDATE SET
            display_name=excluded.display_name,
            emoji=excluded.emoji,
            pinned=excluded.pinned
        """,
        (user, slug, display_name, emoji, int(pinned), created_at),
    )
    conn.commit()


def list_group_meta(conn: sqlite3.Connection, user: str) -> list:
    rows = conn.execute("SELECT * FROM group_meta WHERE user = ?", (user,)).fetchall()
    return [dict(r) for r in rows]


def update_chat_session_project_path(conn: sqlite3.Connection, old_path: str, new_path: str) -> None:
    conn.execute(
        "UPDATE chat_sessions SET project_path = ? WHERE project_path = ?", (new_path, old_path)
    )
    conn.commit()
```

- [ ] **Step 4: Запустить — все тесты должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_storage.py -v
```

Expected: все тесты `passed` (8 старых + 6 новых = 14).

- [ ] **Step 5: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/
git commit -m "feat(hermes-web): хранение метаданных групп (эмодзи/имя/закрепление)"
```

---

## Task 3: `hermes_web/projects.py` — бизнес-логика Групп/Проектов

**Files:**
- Create: `hermes-web/hermes_web/projects.py`
- Test: `hermes-web/tests/test_projects.py`

**Interfaces:**
- Consumes: `storage.get_group_meta/upsert_group_meta/list_group_meta/update_chat_session_project_path` (Task 2), `project_index.core.list_projects_for_user/get_project_detail/search_similar/move_project` (Task 1, уже задеплоенный плагин — импортируется тем же способом, что и в `quickchat.py`), `quickchat.Config` (уже существует — переиспользуется как есть: этому модулю нужны только поля `workspace_root`/`project_index_db_path`/`wormsoft_api_key`, поля `hermes_base_url`/`hermes_api_key` не используются).
- Produces: `ProjectsError(Exception)`, `slugify(name: str) -> str`, `TIME_RANGE_DAYS: dict`, `parse_since(since: str, now: datetime.datetime) -> str | None`, `list_groups(user, db_conn, config) -> list[dict]`, `create_group(user, name, emoji, db_conn, config) -> dict`, `update_group(user, slug, db_conn, config, display_name=None, emoji=None, pinned=None) -> dict`, `list_projects(user, db_conn, config, group="*", since="month", status="active") -> list[dict]`, `get_project_detail(user, project_path, config) -> dict`, `async search_projects(user, query, config) -> dict`, `async move_project(user, project_path, config, db_conn, new_group=None, new_name=None) -> dict`. Используются в Task 4 (`app.py`).

- [ ] **Step 1: Написать падающий тест `hermes-web/tests/test_projects.py`**

```python
import datetime
import os
import sys

import pytest

sys.path.insert(0, os.environ["PROJECT_INDEX_PLUGIN_DIR"])
from project_index import core as project_index_core  # noqa: E402

from hermes_web import projects, storage
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


def _write_project(tmp_path, config, rel_dir, mtime=None):
    project_dir = tmp_path / "workspace" / rel_dir
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(ABOUT_MD, encoding="utf-8")
    if mtime is not None:
        os.utime(project_dir / "about.md", (mtime, mtime))
    user = rel_dir.split("/")[0]
    project_index_core.index_update(
        user, rel_dir, workspace_root=config.workspace_root, db_path=config.project_index_db_path,
    )
    return project_dir


def test_slugify_transliterates_russian_and_dashes():
    assert projects.slugify("Дом и ремонт") == "dom-i-remont"


def test_slugify_blank_name_falls_back_to_group():
    assert projects.slugify("   ") == "group"


def test_list_groups_always_includes_all(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    groups = projects.list_groups("dem", conn, config)
    assert [g["slug"] for g in groups] == ["ALL"]
    assert groups[0]["display_name"] == "ALL"
    assert groups[0]["project_count"] == 0


def test_create_group_creates_folder_and_meta(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    result = projects.create_group("dem", "Дом и ремонт", "🏠", conn, config)
    assert result["slug"] == "dom-i-remont"
    assert os.path.isdir(os.path.join(config.workspace_root, "dem", "dom-i-remont"))
    by_slug = {g["slug"]: g for g in projects.list_groups("dem", conn, config)}
    assert by_slug["dom-i-remont"]["display_name"] == "Дом и ремонт"
    assert by_slug["dom-i-remont"]["emoji"] == "🏠"


def test_create_group_dedupes_slug_collision(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    projects.create_group("dem", "IT", "🖥️", conn, config)
    second = projects.create_group("dem", "IT", "🖥️", conn, config)
    assert second["slug"] == "it-2"


def test_update_group_changes_display_name_and_pin(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    result = projects.update_group("dem", "ALL", conn, config, display_name="Неразобранное", pinned=True)
    assert result["display_name"] == "Неразобранное"
    assert result["pinned"] is True
    by_slug = {g["slug"]: g for g in projects.list_groups("dem", conn, config)}
    assert by_slug["ALL"]["display_name"] == "Неразобранное"


def test_update_group_partial_update_keeps_other_fields(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    projects.update_group("dem", "ALL", conn, config, display_name="Неразобранное", emoji="📦")
    result = projects.update_group("dem", "ALL", conn, config, pinned=True)
    assert result["display_name"] == "Неразобранное"
    assert result["emoji"] == "📦"
    assert result["pinned"] is True


def test_update_group_unknown_slug_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    with pytest.raises(projects.ProjectsError):
        projects.update_group("dem", "nope", conn, config, display_name="x")


def test_list_projects_defaults_to_month_and_active(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    old_mtime = (datetime.datetime.utcnow() - datetime.timedelta(days=400)).timestamp()
    _write_project(tmp_path, config, "dem/ALL/old", mtime=old_mtime)
    _write_project(tmp_path, config, "dem/ALL/new")

    result = projects.list_projects("dem", conn, config)
    assert {p["path"] for p in result} == {str(tmp_path / "workspace" / "dem" / "ALL" / "new")}


def test_list_projects_since_all_includes_old(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    old_mtime = (datetime.datetime.utcnow() - datetime.timedelta(days=400)).timestamp()
    _write_project(tmp_path, config, "dem/ALL/old", mtime=old_mtime)

    result = projects.list_projects("dem", conn, config, since="all", status="all")
    assert len(result) == 1


def test_list_projects_filters_by_group(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    _write_project(tmp_path, config, "dem/1С/b")

    result = projects.list_projects("dem", conn, config, group="1С", since="all", status="all")
    assert [p["group"] for p in result] == ["1С"]


def test_list_projects_unknown_since_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    with pytest.raises(projects.ProjectsError):
        projects.list_projects("dem", conn, config, since="decade")


def test_get_project_detail_returns_group_and_points(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    detail = projects.get_project_detail("dem", "dem/ALL/a", config)
    assert detail["title"] == "Тест"
    assert detail["group"] == "ALL"


@pytest.mark.asyncio
async def test_search_projects_runs_in_executor_and_delegates_to_core(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    def fake_search_similar(user, query, **kwargs):
        assert user == "dem"
        assert query == "гараж"
        return {"results": [], "message": ""}

    monkeypatch.setattr(projects.project_index_core, "search_similar", fake_search_similar)
    result = await projects.search_projects("dem", "гараж", config)
    assert result == {"results": [], "message": ""}


@pytest.mark.asyncio
async def test_move_project_updates_chat_session_path(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    old_path = str(tmp_path / "workspace" / "dem" / "ALL" / "a")
    storage.create_chat_session(conn, "chat1", "dem", old_path, "web_1", created_at=1.0)

    result = await projects.move_project("dem", "dem/ALL/a", config, conn, new_group="ALL", new_name="b")

    row = storage.get_chat_session(conn, "chat1")
    assert row["project_path"] == result["new_path"]


@pytest.mark.asyncio
async def test_move_project_collision_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    _write_project(tmp_path, config, "dem/1С/a")

    with pytest.raises(project_index_core.ProjectIndexError):
        await projects.move_project("dem", "dem/ALL/a", config, conn, new_group="1С")
```

- [ ] **Step 2: Запустить — убедиться, что падают**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_projects.py -v
```

Expected: `ModuleNotFoundError: No module named 'hermes_web.projects'`.

- [ ] **Step 3: Написать `hermes-web/hermes_web/projects.py`**

```python
"""Группы и Проекты: слаги, серверная фильтрация по времени/статусу, поиск,
перенос. Обёртка над уже задеплоенным project_index.core — так же, как
quickchat.py, но без создания Hermes-сессий и без похода в Hermes API server
(этому модулю не нужны hermes_base_url/hermes_api_key из quickchat.Config,
только workspace_root/project_index_db_path/wormsoft_api_key).

sys.path-манипуляция для PROJECT_INDEX_PLUGIN_DIR продублирована из
quickchat.py намеренно: reaching into another module's private setup would
be more fragile than three self-contained lines here (идемпотентно — если
quickchat.py уже вставил путь, повторная вставка no-op).
"""
from __future__ import annotations

import asyncio
import datetime
import functools
import os
import re
import sys
from typing import Optional

from . import storage

_PROJECT_INDEX_DIR = os.environ.get("PROJECT_INDEX_PLUGIN_DIR")
if _PROJECT_INDEX_DIR and _PROJECT_INDEX_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_INDEX_DIR)

from project_index import core as project_index_core  # noqa: E402

ALL_GROUP_SLUG = "ALL"

TIME_RANGE_DAYS = {"week": 7, "month": 30, "quarter": 90, "half_year": 182, "year": 365}

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


class ProjectsError(Exception):
    """Raised for expected, user-facing failures (unknown group/since range)."""


def slugify(name: str) -> str:
    lowered = name.strip().lower()
    transliterated = "".join(_TRANSLIT.get(ch, ch) for ch in lowered)
    slug = re.sub(r"[^a-z0-9]+", "-", transliterated).strip("-")
    return slug or "group"


def parse_since(since: str, now: datetime.datetime) -> Optional[str]:
    if since is None or since == "all":
        return None
    days = TIME_RANGE_DAYS.get(since)
    if days is None:
        raise ProjectsError(f"неизвестный диапазон времени: {since}")
    return (now - datetime.timedelta(days=days)).isoformat()


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


def _workspace_kwargs(config) -> dict:
    """Like _project_index_kwargs but without api_key — for the read-only
    listing calls (list_projects_for_user), which take no api_key parameter
    at all (they never touch embeddings, only the already-computed SQL
    columns). Passing api_key into them would raise TypeError."""
    kwargs: dict = {}
    if config.workspace_root is not None:
        kwargs["workspace_root"] = config.workspace_root
    if config.project_index_db_path is not None:
        kwargs["db_path"] = config.project_index_db_path
    return kwargs


def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat()


def _project_counts_by_group(user: str, config) -> dict:
    all_projects = project_index_core.list_projects_for_user(user, **_workspace_kwargs(config))
    counts: dict = {}
    for p in all_projects:
        counts[p["group"]] = counts.get(p["group"], 0) + 1
    return counts


def list_groups(user: str, db_conn, config) -> list:
    root = _workspace_root(config)
    user_root = os.path.join(root, user)
    disk_slugs = set()
    if os.path.isdir(user_root):
        disk_slugs = {name for name in os.listdir(user_root) if os.path.isdir(os.path.join(user_root, name))}
    disk_slugs.add(ALL_GROUP_SLUG)

    meta_by_slug = {row["slug"]: row for row in storage.list_group_meta(db_conn, user)}
    counts = _project_counts_by_group(user, config)

    groups = []
    for slug in sorted(disk_slugs):
        meta = meta_by_slug.get(slug)
        groups.append({
            "slug": slug,
            "display_name": meta["display_name"] if meta else slug,
            "emoji": meta["emoji"] if meta else "",
            "pinned": bool(meta["pinned"]) if meta else False,
            "project_count": counts.get(slug, 0),
        })
    return groups


def create_group(user: str, name: str, emoji: str, db_conn, config) -> dict:
    existing_slugs = {g["slug"] for g in list_groups(user, db_conn, config)}
    base_slug = slugify(name)
    slug = base_slug
    i = 2
    while slug in existing_slugs:
        slug = f"{base_slug}-{i}"
        i += 1

    os.makedirs(os.path.join(_workspace_root(config), user, slug), exist_ok=False)
    display_name = name.strip()
    storage.upsert_group_meta(db_conn, user, slug, display_name, emoji, False, created_at=_now_iso())
    return {"slug": slug, "display_name": display_name, "emoji": emoji, "pinned": False, "project_count": 0}


def update_group(
    user: str, slug: str, db_conn, config, display_name=None, emoji=None, pinned=None,
) -> dict:
    by_slug = {g["slug"]: g for g in list_groups(user, db_conn, config)}
    if slug not in by_slug:
        raise ProjectsError(f"неизвестная группа: {slug}")
    current = by_slug[slug]

    new_display_name = display_name if display_name is not None else current["display_name"]
    new_emoji = emoji if emoji is not None else current["emoji"]
    new_pinned = pinned if pinned is not None else current["pinned"]

    storage.upsert_group_meta(db_conn, user, slug, new_display_name, new_emoji, new_pinned, created_at=_now_iso())
    return {
        "slug": slug, "display_name": new_display_name, "emoji": new_emoji,
        "pinned": new_pinned, "project_count": current["project_count"],
    }


def list_projects(user: str, db_conn, config, group: str = "*", since: str = "month", status: str = "active") -> list:
    updated_since = parse_since(since, datetime.datetime.utcnow())
    filter_status = None if status == "all" else status
    return project_index_core.list_projects_for_user(
        user, updated_since=updated_since, status=filter_status, group=group, **_workspace_kwargs(config),
    )


def get_project_detail(user: str, project_path: str, config) -> dict:
    return project_index_core.get_project_detail(user, project_path, workspace_root=_workspace_root(config))


async def search_projects(user: str, query: str, config) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, functools.partial(project_index_core.search_similar, user, query, **_project_index_kwargs(config)),
    )


async def move_project(user: str, project_path: str, config, db_conn, new_group=None, new_name=None) -> dict:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        functools.partial(
            project_index_core.move_project, user, project_path,
            new_group=new_group, new_name=new_name, **_project_index_kwargs(config),
        ),
    )
    storage.update_chat_session_project_path(db_conn, result["old_path"], result["new_path"])
    return result
```

- [ ] **Step 4: Запустить — все тесты должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_projects.py -v
```

Expected: `18 passed`.

- [ ] **Step 5: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/
git commit -m "feat(hermes-web): projects.py — группы, фильтрация проектов, поиск, перенос"
```

---

## Task 4: `app.py` — маршруты Групп/Проектов

**Files:**
- Modify: `hermes-web/hermes_web/app.py`
- Test: `hermes-web/tests/test_app.py`

**Interfaces:**
- Consumes: `projects.list_groups/create_group/update_group/list_projects/get_project_detail/search_projects/move_project/ProjectsError` (Task 3), `projects.project_index_core.ProjectIndexError` (доступ через уже импортированный в `projects.py` `project_index_core`), уже существующие `_require_user`/`auth_middleware`/`create_app` (срез 1+2).
- Produces: 7 новых маршрутов на уже существующем `create_app`. Ничего нового не используется дальше в этом плане (Task 5 — фронтенд, потребляет эти маршруты как HTTP API, не как Python-интерфейс).

- [ ] **Step 1: Написать падающий тест** (дописать в `hermes-web/tests/test_app.py`; добавить `from hermes_web import projects` в импорты наверху файла, рядом с уже существующим `from hermes_web import auth, quickchat, storage`)

```python
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
```

- [ ] **Step 2: Запустить — убедиться, что падают**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_app.py -v -k "groups or projects_ or search_projects or move_project"
```

Expected: `404 Not Found` вместо ожидаемых статусов (маршруты ещё не зарегистрированы).

- [ ] **Step 3: Править `hermes-web/hermes_web/app.py`**

Заменить строку импорта `from . import auth, hermes_client, quickchat, storage` на:

```python
from . import auth, hermes_client, projects, quickchat, storage
```

Добавить новые хендлеры (после `handle_get_messages`, перед `async def _on_startup`):

```python
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
```

В `create_app`, после строки `app.router.add_get("/api/chat/{chat_session_id}/messages", handle_get_messages)` и **перед** `app.router.add_get("/", handle_root)`, добавить:

```python
    app.router.add_get("/api/groups", handle_list_groups)
    app.router.add_post("/api/groups", handle_create_group)
    app.router.add_put("/api/groups/{slug}", handle_update_group)
    app.router.add_get("/api/projects", handle_list_projects)
    app.router.add_get("/api/projects/detail", handle_project_detail)
    app.router.add_post("/api/projects/search", handle_search_projects)
    app.router.add_post("/api/projects/move", handle_move_project)
```

- [ ] **Step 4: Запустить весь `test_app.py` — все тесты должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/test_app.py -v
```

Expected: все тесты `passed` (существующие из среза 1+2 + 11 новых).

- [ ] **Step 5: Запустить весь набор `hermes-web` — регрессии быть не должно**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/pytest hermes-web/tests/ -v
```

Expected: все тесты `passed`.

- [ ] **Step 6: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/
git commit -m "feat(hermes-web): маршруты /api/groups и /api/projects"
```

---

## Task 5: Фронтенд — `project-selector.html` + включение плиток в `home.html`

**Files:**
- Create: `hermes-web/static/project-selector.html`
- Modify: `hermes-web/static/home.html`

**Interfaces:** нет (статика, потребляет HTTP API из Task 4 через `fetch`/`apiFetch` из уже существующего `app.js`).

- [ ] **Step 1: Создать `hermes-web/static/project-selector.html`**

Взять `/home/deploy/hermes-cn-ru/result/project-selector.html` за основу (тот же `<style>` блок — без изменений, экран уже согласован с заказчиком, D-009). Меняется разметка (добавлен ряд фильтров «давность» и попап переноса, у кнопки «+ новая группа» появляется `id`) и полностью весь `<script>` (данные приходят с бэкенда, а не из захардкоженных массивов):

```html
<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Проекты — Hermes</title>
<style>
  :root{
    --sky:#12172b;
    --sky-deep:#0c1020;
    --panel:#1a2038;
    --panel-2:#212949;
    --panel-line:#3c4568;
    --text:#f8f6ef;
    --text-dim:#aeb7dc;
    --gold:#f0bb5c;
    --violet:#ad9fe6;
    --teal:#7fc4b2;
    --dim-star:#727bab;
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0;height:100%}
  body{
    background:
      radial-gradient(1px 1px at 20% 30%, #fff8, transparent),
      radial-gradient(1px 1px at 65% 15%, #fff6, transparent),
      radial-gradient(1.5px 1.5px at 82% 60%, #fff9, transparent),
      radial-gradient(1px 1px at 40% 80%, #fff5, transparent),
      radial-gradient(1px 1px at 12% 65%, #fff7, transparent),
      radial-gradient(1.5px 1.5px at 92% 30%, #fff6, transparent),
      linear-gradient(180deg, var(--sky-deep), var(--sky) 40%);
    color:var(--text);
    font-family:Georgia,"Iowan Old Style",serif;
    height:100vh;
    display:grid;
    grid-template-columns:270px 1fr 0px;
    transition:grid-template-columns .22s ease;
  }
  body.panel-open{grid-template-columns:270px 1fr 440px}

  aside.groups{
    border-right:1px solid var(--panel-line);
    padding:26px 18px;
    display:flex;
    flex-direction:column;
    min-height:0;
    overflow:hidden;
  }
  .brand{font-family:ui-monospace,Consolas,monospace;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--text-dim)}
  aside.groups h1{font-size:21px;font-weight:400;font-style:italic;margin:4px 0 16px}

  .group-search{
    display:flex;align-items:center;gap:8px;
    background:var(--panel);border:1px solid var(--panel-line);border-radius:8px;
    padding:8px 10px;margin-bottom:16px;flex-shrink:0;
  }
  .group-search input{
    flex:1;background:none;border:none;outline:none;color:var(--text);
    font-family:Georgia,serif;font-size:13px;
  }
  .group-search svg{flex-shrink:0;opacity:.6}

  .glabel{
    font-family:ui-monospace,Consolas,monospace;font-size:10px;letter-spacing:1.5px;
    text-transform:uppercase;color:var(--text-dim);margin:10px 0 6px;flex-shrink:0;
  }
  .grouplist{display:flex;flex-direction:column;gap:1px;overflow-y:auto}
  .grouplist.pinned{flex-shrink:0;max-height:210px}
  .grouplist.rest{flex:1;min-height:0}
  .glist-wrap{display:flex;flex-direction:column;min-height:0;flex:1}

  .grow{
    display:flex;align-items:center;gap:10px;
    padding:9px 10px;border-radius:8px;cursor:pointer;
    color:var(--text-dim);font-size:14px;
  }
  .grow:hover{background:var(--panel)}
  .grow.active{background:var(--panel-2);color:var(--text)}
  .grow .emoji{font-size:15px;width:18px;text-align:center;flex-shrink:0}
  .grow .gname{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .grow .n{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;color:var(--text-dim);flex-shrink:0}
  .grow .pin{
    opacity:0;flex-shrink:0;background:none;border:none;color:var(--gold);
    cursor:pointer;font-size:12px;padding:2px;
  }
  .grow:hover .pin{opacity:.7}
  .grow .pin:hover{opacity:1 !important}
  .grow .pin.is-pinned{opacity:.9;color:var(--gold)}

  .divider{height:1px;background:var(--panel-line);margin:14px 0;flex-shrink:0}
  .grow.everywhere{flex-shrink:0;font-weight:400;color:var(--text-dim)}
  .grow.everywhere.active{background:var(--panel-2);color:var(--gold);border:1px solid var(--gold)}
  .grow.everywhere .n{color:var(--gold)}

  .add-group{
    margin-top:14px;flex-shrink:0;
    font-family:ui-monospace,Consolas,monospace;font-size:11.5px;
    color:var(--text-dim);background:none;border:1px dashed var(--panel-line);
    border-radius:8px;padding:9px;cursor:pointer;width:100%;
  }
  .add-group:hover{color:var(--text);border-color:var(--violet)}

  main{padding:30px 34px 40px;overflow-y:auto;min-height:0}
  .mainhead{display:flex;align-items:baseline;gap:12px;margin-bottom:20px}
  .mainhead .emoji-lg{font-size:26px}
  .mainhead h2{font-size:25px;font-weight:400;font-style:italic;margin:0}
  .mainhead span{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--text-dim)}

  .filters{
    background:var(--panel);border:1px solid var(--panel-line);border-radius:12px;
    padding:16px 18px;margin-bottom:26px;display:flex;flex-direction:column;gap:12px;
  }
  .rag-row{display:flex;align-items:center;gap:10px}
  .rag-row svg{opacity:.6;flex-shrink:0}
  .rag-row input{
    flex:1;background:none;border:none;outline:none;color:var(--text);
    font-family:Georgia,serif;font-style:italic;font-size:14px;
  }
  .rag-row .hint{font-family:ui-monospace,Consolas,monospace;font-size:9.5px;color:var(--dim-star);letter-spacing:.5px;text-transform:uppercase;flex-shrink:0}

  .filter-row2{display:flex;align-items:center;gap:16px;flex-wrap:wrap;padding-top:10px;border-top:1px solid var(--panel-line)}
  .tagcloud{display:flex;gap:6px;flex-wrap:wrap;flex:1}
  .tagbtn{
    font-family:ui-monospace,Consolas,monospace;font-size:10.5px;color:#e7e2fa;
    background:rgba(173,159,230,.24);border:1px solid rgba(173,159,230,.65);
    padding:4px 9px;border-radius:20px;cursor:pointer;
  }
  .tagbtn.on{background:var(--violet);color:var(--sky-deep);border-color:var(--violet)}
  .tagbtn.mini{cursor:default;font-size:9.5px;padding:3px 7px}

  .statusgroup,.timegroup{display:flex;gap:2px;background:var(--sky-deep);border:1px solid var(--panel-line);border-radius:20px;padding:2px;flex-shrink:0}
  .statusgroup button,.timegroup button{
    font-family:ui-monospace,Consolas,monospace;font-size:10.5px;color:var(--text-dim);
    background:none;border:none;padding:5px 11px;border-radius:16px;cursor:pointer;
  }
  .statusgroup button.on,.timegroup button.on{background:var(--gold);color:var(--sky-deep)}
  .reset-btn{
    font-family:ui-monospace,Consolas,monospace;font-size:10.5px;color:var(--text-dim);
    background:none;border:1px solid var(--panel-line);border-radius:20px;padding:5px 11px;cursor:pointer;flex-shrink:0;
  }
  .reset-btn:hover{color:var(--text);border-color:var(--violet)}

  .filters.searching .tagcloud,.filters.searching .statusgroup,.filters.searching .timegroup{display:none}

  .edit-group-btn{
    margin-left:auto;font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--text-dim);
    background:none;border:1px solid var(--panel-line);border-radius:20px;padding:6px 12px;cursor:pointer;flex-shrink:0;
  }
  .edit-group-btn:hover{color:var(--text);border-color:var(--violet)}

  .tilesize{display:flex;align-items:center;gap:8px;flex-shrink:0;color:var(--text-dim)}
  .tilesize input[type=range]{width:90px;accent-color:var(--gold)}

  .list{
    display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--tile-min,230px),1fr));
    gap:12px;align-content:start;
  }
  .prow{
    display:flex;flex-direction:column;gap:8px;
    padding:14px 15px;border-radius:12px;cursor:pointer;
    border:1px solid var(--panel-line);background:var(--panel);
    min-height:0;
  }
  .prow:hover{border-color:var(--violet)}
  .prow.selected{background:var(--panel-2);border-color:var(--gold)}
  .prow .rowhead{display:flex;align-items:baseline;gap:7px}
  .prow .mark{color:var(--gold);font-size:12px;flex-shrink:0}
  .prow .mark.dim{color:var(--dim-star)}
  .prow .grp-hint{
    margin-left:auto;font-family:ui-monospace,Consolas,monospace;font-size:9px;
    color:var(--text-dim);white-space:nowrap;flex-shrink:0;
  }
  .prow .body h3{margin:0;font-size:14.5px;font-weight:400;color:var(--text);line-height:1.35}
  .prow .body p{
    margin:0;font-size:12px;color:var(--text-dim);line-height:1.5;
    display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  }
  .prow .foot{display:flex;align-items:center;gap:6px;margin-top:auto;flex-wrap:wrap}
  .prow .body .tags{display:flex;gap:5px;flex-wrap:wrap;flex:1}
  .prow .status{font-family:ui-monospace,Consolas,monospace;font-size:9.5px;color:var(--teal);white-space:nowrap;flex-shrink:0}
  .prow .status.archived{color:var(--dim-star)}

  .empty{color:var(--text-dim);font-family:ui-monospace,Consolas,monospace;font-size:12.5px;padding:30px 4px}

  .panel3{
    border-left:1px solid var(--panel-line);
    background:var(--sky-deep);
    overflow:hidden;
    display:flex;flex-direction:column;
  }
  body.panel-open .panel3{overflow-y:auto}
  .panel3-inner{padding:32px 30px;width:440px}
  .panel3 .close{
    background:none;border:none;color:var(--text-dim);cursor:pointer;
    font-family:ui-monospace,Consolas,monospace;font-size:11px;margin-bottom:18px;
  }
  .panel3 .close:hover{color:var(--text)}
  .panel3 .p-status{
    display:inline-block;font-family:ui-monospace,Consolas,monospace;font-size:10.5px;
    color:var(--teal);border:1px solid var(--teal);padding:2px 8px;border-radius:20px;margin-bottom:14px;
  }
  .panel3 .p-status.archived{color:var(--dim-star);border-color:var(--dim-star)}
  .panel3 h2{font-size:23px;font-weight:400;margin:0 0 4px;line-height:1.3}
  .panel3 .p-group{font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--text-dim);margin-bottom:22px}
  .p-block{margin-bottom:22px}
  .p-block .lbl{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;letter-spacing:1.5px;text-transform:uppercase;color:var(--violet);margin-bottom:7px}
  .p-block p{margin:0;font-size:14.5px;line-height:1.65;color:var(--text)}
  .p-tags{display:flex;gap:6px;flex-wrap:wrap}
  .p-tags span{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;color:#e7e2fa;background:rgba(173,159,230,.24);border:1px solid rgba(173,159,230,.65);padding:3px 9px;border-radius:20px}
  .p-actions{display:flex;flex-direction:column;gap:8px;margin-top:26px}
  .p-actions button{
    font-family:ui-monospace,Consolas,monospace;font-size:12px;padding:11px;border-radius:8px;cursor:pointer;
  }
  .btn-primary{background:var(--gold);color:var(--sky-deep);border:none}
  .btn-secondary{background:none;color:var(--text-dim);border:1px solid var(--panel-line)}
  .btn-secondary:hover{color:var(--text);border-color:var(--violet)}

  .overlay{position:fixed;inset:0;background:rgba(6,8,16,.72);display:none;align-items:center;justify-content:center;z-index:10}
  .overlay.on{display:flex}
  .modal{width:420px;max-width:90vw;background:var(--panel);border:1px solid var(--panel-line);border-radius:14px;padding:26px;max-height:82vh;overflow-y:auto}
  .modal h3{margin:0 0 20px;font-weight:400;font-style:italic;font-size:19px}
  .modal-top{display:flex;align-items:center;gap:14px;margin-bottom:22px}
  .emoji-preview{
    width:52px;height:52px;flex-shrink:0;border-radius:12px;background:var(--sky-deep);
    display:flex;align-items:center;justify-content:center;font-size:26px;border:1px solid var(--panel-line);
  }
  .modal input[type=text]{
    flex:1;background:var(--sky-deep);border:1px solid var(--panel-line);border-radius:8px;
    padding:10px 12px;color:var(--text);font-family:Georgia,serif;font-size:14px;
  }
  .modal label{display:block;font-family:ui-monospace,Consolas,monospace;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--text-dim);margin:16px 0 8px}
  .emoji-cat{margin-bottom:12px}
  .emoji-cat-label{font-family:ui-monospace,Consolas,monospace;font-size:10px;color:var(--text-dim);margin-bottom:6px}
  .emoji-grid{display:flex;flex-wrap:wrap;gap:6px}
  .emoji-opt{
    width:34px;height:34px;font-size:17px;background:var(--sky-deep);border:1px solid var(--panel-line);
    border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;
  }
  .emoji-opt:hover{border-color:var(--violet)}
  .emoji-opt.selected{border-color:var(--gold);background:var(--panel-2)}
  .custom-emoji-row{display:flex;align-items:center;gap:10px}
  .custom-emoji-row input{width:90px;text-align:center;font-size:18px}
  .modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:22px}
  .modal-actions button{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;padding:9px 16px;border-radius:8px;cursor:pointer}
  .ghost-btn{background:none;color:var(--text-dim);border:1px solid var(--panel-line);width:100%;text-align:left}
  .ghost-btn:hover{color:var(--text);border-color:var(--violet)}
  #moveGroupList{display:flex;flex-direction:column;gap:6px;max-height:320px;overflow-y:auto}
</style>
</head>
<body>

<aside class="groups">
  <div class="brand" style="display:flex;align-items:center;justify-content:space-between">Hermes <a href="home.html" style="color:var(--text-dim);text-decoration:none" title="на главную">🏠</a></div>
  <h1>Группы</h1>

  <div class="group-search">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
    <input id="groupSearch" type="text" placeholder="искать группу…">
  </div>

  <div id="everywhereRow" class="grow everywhere"><span class="emoji">🔭</span><span class="gname">Искать везде</span><span class="n" id="everywhereN"></span></div>
  <div class="divider" style="margin:10px 0"></div>

  <div class="glist-wrap">
    <div class="glabel">Закреплённые</div>
    <div class="grouplist pinned" id="pinnedList"></div>
    <div class="divider"></div>
    <div class="glabel">Все группы</div>
    <div class="grouplist rest" id="restList"></div>
  </div>

  <button class="add-group" id="addGroupBtn">+ новая группа</button>
</aside>

<main>
  <div class="mainhead">
    <span class="emoji-lg" id="headEmoji">🗂️</span>
    <h2 id="headName">…</h2>
    <span id="headCount"></span>
    <button class="edit-group-btn" id="editGroupBtn">⚙️ настроить группу</button>
  </div>

  <div class="filters" id="filters">
    <div class="rag-row">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input id="ragSearch" type="text" placeholder="поискать похожие проекты по смыслу…">
      <span class="hint">RAG</span>
    </div>
    <div class="filter-row2">
      <div class="tagcloud" id="tagCloud"></div>
      <div class="statusgroup" id="statusGroup">
        <button data-status="all">ALL</button>
        <button data-status="active" class="on">active</button>
        <button data-status="archived">archived</button>
      </div>
      <div class="timegroup" id="timeGroup">
        <button data-since="week">неделя</button>
        <button data-since="month" class="on">месяц</button>
        <button data-since="quarter">квартал</button>
        <button data-since="half_year">полгода</button>
        <button data-since="year">год</button>
        <button data-since="all">всё время</button>
      </div>
      <button class="reset-btn" id="resetFilters" title="сбросить поиск, теги и фильтры">✕ сбросить</button>
      <div class="tilesize" title="размер плиток">
        <span>🔳</span><input type="range" id="tileSize" min="180" max="360" step="10" value="230">
      </div>
    </div>
  </div>

  <div class="list" id="projectList"></div>
  <div class="empty" id="emptyMsg" style="display:none">— в этой выборке ничего нет —</div>
</main>

<div class="panel3">
  <div class="panel3-inner" id="panelInner"></div>
</div>

<div class="overlay" id="groupEditorOverlay">
  <div class="modal">
    <h3 id="groupEditorTitle">Настроить группу</h3>
    <div class="modal-top">
      <div class="emoji-preview" id="emojiPreview">🗂️</div>
      <input type="text" id="groupNameInput" placeholder="название группы">
    </div>
    <label>Эмодзи по смыслу</label>
    <div id="emojiCategories"></div>
    <label>Своё (вставьте из буфера, Ctrl+V)</label>
    <div class="custom-emoji-row">
      <input type="text" id="customEmojiInput" maxlength="4" placeholder="😀">
    </div>
    <div class="modal-actions">
      <button class="ghost-btn" id="groupEditorCancel" style="width:auto">Отмена</button>
      <button class="btn-primary" id="groupEditorSave" style="padding:9px 16px">Сохранить</button>
    </div>
  </div>
</div>

<div class="overlay" id="moveOverlay">
  <div class="modal" style="width:320px">
    <h3>Перенести в группу</h3>
    <div id="moveGroupList"></div>
    <div class="modal-actions">
      <button class="ghost-btn" id="moveCancel" style="width:auto">Отмена</button>
    </div>
  </div>
</div>

<script src="app.js"></script>
<script>
let groups = [];
let projects = [];
let searchResults = null;

const state = { group: 'ALL', status: 'active', since: 'month', tags: new Set(), ragQuery: '', groupQuery: '', selectedProject: null };

function debounce(fn, ms){
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

async function loadGroups(){
  const resp = await apiFetch('/api/groups');
  if(resp.status === 401){ location.href = 'login.html'; return; }
  const body = await resp.json();
  groups = body.groups;
}

async function loadProjects(){
  const params = new URLSearchParams({ group: state.group, since: state.since, status: state.status });
  const resp = await apiFetch('/api/projects?' + params.toString());
  if(resp.status === 401){ location.href = 'login.html'; return; }
  const body = await resp.json();
  projects = body.projects;
  renderMain();
}

function resetFilters(){
  state.status = 'active'; state.since = 'month'; state.tags.clear(); state.ragQuery = '';
  document.getElementById('ragSearch').value = '';
  searchResults = null;
  [...document.getElementById('statusGroup').children].forEach(b => b.classList.remove('on'));
  document.getElementById('statusGroup').querySelector('[data-status="active"]').classList.add('on');
  [...document.getElementById('timeGroup').children].forEach(b => b.classList.remove('on'));
  document.getElementById('timeGroup').querySelector('[data-since="month"]').classList.add('on');
}

function groupRow(g){
  const row = document.createElement('div');
  row.className = 'grow' + (g.slug === state.group ? ' active' : '');
  row.innerHTML = `<span class="emoji">${g.emoji || '🗂️'}</span><span class="gname">${g.display_name}</span><span class="n">${g.project_count}</span><button class="pin ${g.pinned ? 'is-pinned' : ''}" title="закрепить">${g.pinned ? '★' : '☆'}</button>`;
  row.addEventListener('click', async (e) => {
    if(e.target.classList.contains('pin')){
      await apiFetch('/api/groups/' + encodeURIComponent(g.slug), {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned: !g.pinned }),
      });
      await loadGroups();
      renderGroups();
      return;
    }
    state.group = g.slug; state.selectedProject = null;
    document.body.classList.remove('panel-open');
    resetFilters();
    renderGroups();
    await loadProjects();
  });
  return row;
}

function renderGroups(){
  document.getElementById('everywhereRow').classList.toggle('active', state.group === '*');
  const q = state.groupQuery.trim().toLowerCase();
  const match = g => g.display_name.toLowerCase().includes(q);
  const pinnedEl = document.getElementById('pinnedList');
  const restEl = document.getElementById('restList');
  pinnedEl.innerHTML = ''; restEl.innerHTML = '';
  groups.filter(g => g.pinned && match(g)).forEach(g => pinnedEl.appendChild(groupRow(g)));
  groups.filter(g => !g.pinned && match(g)).forEach(g => restEl.appendChild(groupRow(g)));
  document.getElementById('everywhereN').textContent = groups.reduce((sum, g) => sum + g.project_count, 0);
}

function renderPanel(p, detail){
  document.body.classList.add('panel-open');
  const pg = groups.find(x => x.slug === p.group) || { emoji: '🗂️', display_name: p.group };
  const points = detail ? (detail.points || '— нет —') : 'Загрузка…';
  const now = detail ? (detail.now || '— нет —') : 'Загрузка…';
  document.getElementById('panelInner').innerHTML = `
    <button class="close" onclick="document.body.classList.remove('panel-open')">✕ закрыть</button>
    <span class="p-status ${p.status}">${p.status}</span>
    <h2>${p.title}</h2>
    <div class="p-group">${pg.emoji || '🗂️'} ${pg.display_name}</div>
    <div class="p-block"><div class="lbl">Краткое описание</div><p>${p.description}</p></div>
    <div class="p-block"><div class="lbl">Опорные точки</div><p>${points}</p></div>
    <div class="p-block"><div class="lbl">На чём остановились</div><p>${now}</p></div>
    <div class="p-block"><div class="lbl">Tags</div><div class="p-tags">${p.tags.map(t => '<span>#' + t + '</span>').join('') || '<span style="opacity:.5">— нет —</span>'}</div></div>
    <div class="p-actions">
      <button class="btn-primary" id="openProjectBtn">Открыть проект →</button>
      <button class="btn-secondary" id="movePanelBtn">Перенести в другую группу</button>
    </div>
  `;
  document.getElementById('openProjectBtn').addEventListener('click', () => {
    alert('Полноценный экран проекта появится в следующем срезе.');
  });
  document.getElementById('movePanelBtn').addEventListener('click', () => openMoveModal(p));
}

async function openPanel(p){
  state.selectedProject = p.path;
  renderMain();
  renderPanel(p, null);
  const params = new URLSearchParams({ path: p.path });
  const resp = await apiFetch('/api/projects/detail?' + params.toString());
  if(resp.ok){
    renderPanel(p, await resp.json());
  }
}

function openMoveModal(p){
  const list = document.getElementById('moveGroupList');
  list.innerHTML = '';
  groups.filter(g => g.slug !== p.group).forEach(g => {
    const btn = document.createElement('button');
    btn.className = 'ghost-btn';
    btn.textContent = `${g.emoji || '🗂️'} ${g.display_name}`;
    btn.addEventListener('click', async () => {
      const resp = await apiFetch('/api/projects/move', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: p.path, new_group: g.slug }),
      });
      document.getElementById('moveOverlay').classList.remove('on');
      if(!resp.ok){ alert('Не удалось перенести проект'); return; }
      document.body.classList.remove('panel-open');
      await loadGroups();
      renderGroups();
      await loadProjects();
    });
    list.appendChild(btn);
  });
  document.getElementById('moveOverlay').classList.add('on');
}

document.getElementById('moveCancel').addEventListener('click', () => {
  document.getElementById('moveOverlay').classList.remove('on');
});

function renderMain(){
  const searching = searchResults !== null;
  document.getElementById('filters').classList.toggle('searching', searching);

  let list = searching ? searchResults.slice() : projects.slice();
  const scopeTotal = list.length;
  if(!searching && state.tags.size) list = list.filter(p => p.tags.some(t => state.tags.has(t)));

  const everywhere = state.group === '*';
  const g = everywhere
    ? { emoji: '🔭', display_name: 'Искать везде — все группы' }
    : (groups.find(x => x.slug === state.group) || { emoji: '🗂️', display_name: state.group });
  document.getElementById('headEmoji').textContent = g.emoji || '🗂️';
  document.getElementById('headName').textContent = g.display_name;
  document.getElementById('editGroupBtn').style.display = (everywhere || searching) ? 'none' : 'inline-block';
  document.getElementById('headCount').textContent = searching ? `${list.length} похожих по смыслу` : `${list.length} из ${scopeTotal}`;

  const cloud = document.getElementById('tagCloud');
  cloud.innerHTML = '';
  if(!searching){
    const tagSet = new Set();
    projects.forEach(p => p.tags.forEach(t => tagSet.add(t)));
    [...tagSet].forEach(t => {
      const b = document.createElement('button');
      b.className = 'tagbtn' + (state.tags.has(t) ? ' on' : '');
      b.textContent = '#' + t;
      b.addEventListener('click', () => {
        state.tags.has(t) ? state.tags.delete(t) : state.tags.add(t);
        renderMain();
      });
      cloud.appendChild(b);
    });
  }

  const listEl = document.getElementById('projectList');
  listEl.innerHTML = '';
  document.getElementById('emptyMsg').style.display = list.length ? 'none' : 'block';
  list.forEach(p => {
    const pg = groups.find(x => x.slug === p.group) || { emoji: '🗂️', display_name: p.group };
    const row = document.createElement('div');
    row.className = 'prow' + (state.selectedProject === p.path ? ' selected' : '');
    row.innerHTML = `
      <div class="rowhead">
        <span class="mark ${p.status === 'archived' ? 'dim' : ''}">${p.status === 'archived' ? '✧' : '✦'}</span>
        ${(everywhere || searching) ? `<span class="grp-hint">${pg.emoji || '🗂️'} ${pg.display_name}</span>` : ''}
      </div>
      <div class="body"><h3>${p.title}</h3><p>${p.description}</p></div>
      <div class="foot">
        <div class="tags">${p.tags.map(t => '<span class="tagbtn mini">#' + t + '</span>').join('')}</div>
        <span class="status ${p.status}">${p.status}</span>
      </div>
    `;
    row.addEventListener('click', () => openPanel(p));
    listEl.appendChild(row);
  });
}

document.getElementById('everywhereRow').addEventListener('click', async () => {
  state.group = '*'; state.selectedProject = null;
  document.body.classList.remove('panel-open');
  resetFilters();
  renderGroups();
  await loadProjects();
});

document.getElementById('resetFilters').addEventListener('click', async () => {
  resetFilters();
  await loadProjects();
});

document.getElementById('tileSize').addEventListener('input', e => {
  document.documentElement.style.setProperty('--tile-min', e.target.value + 'px');
});

document.getElementById('groupSearch').addEventListener('input', e => { state.groupQuery = e.target.value; renderGroups(); });

document.getElementById('ragSearch').addEventListener('input', debounce(async (e) => {
  const q = e.target.value.trim();
  state.ragQuery = q;
  if(!q){ searchResults = null; renderMain(); return; }
  const resp = await apiFetch('/api/projects/search', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: q }),
  });
  if(!resp.ok){ searchResults = []; renderMain(); return; }
  const body = await resp.json();
  searchResults = body.results;
  renderMain();
}, 400));

document.getElementById('statusGroup').addEventListener('click', async (e) => {
  if(e.target.tagName !== 'BUTTON') return;
  state.status = e.target.dataset.status;
  [...document.getElementById('statusGroup').children].forEach(b => b.classList.remove('on'));
  e.target.classList.add('on');
  await loadProjects();
});

document.getElementById('timeGroup').addEventListener('click', async (e) => {
  if(e.target.tagName !== 'BUTTON') return;
  state.since = e.target.dataset.since;
  [...document.getElementById('timeGroup').children].forEach(b => b.classList.remove('on'));
  e.target.classList.add('on');
  await loadProjects();
});

const EMOJI_CATS = {
  'Работа / IT': ['🖥️','💻','🧰','🔧','⚙️','📊','🗂️','📁'],
  'Дом и быт':   ['🏠','🍲','🧹','🚗','🩺','🌿'],
  'Учёба и языки':['📚','🎓','🇬🇧','🇨🇳','✏️','🧠'],
  'Финансы':     ['💰','💳','📈','🧾'],
  'Путешествия и хобби':['✈️','🎨','🎮','📷','⚽'],
  'Разное':      ['⭐','📌','🔭','🗃️','❔'],
};

let editingGroupSlug = null;
let pendingEmoji = null;

function renderEmojiGrid(){
  const wrap = document.getElementById('emojiCategories');
  wrap.innerHTML = '';
  Object.entries(EMOJI_CATS).forEach(([cat, list]) => {
    const catDiv = document.createElement('div');
    catDiv.className = 'emoji-cat';
    const grid = document.createElement('div');
    grid.className = 'emoji-grid';
    list.forEach(e => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'emoji-opt' + (e === pendingEmoji ? ' selected' : '');
      b.textContent = e;
      b.addEventListener('click', () => {
        pendingEmoji = e;
        document.getElementById('emojiPreview').textContent = e;
        document.getElementById('customEmojiInput').value = '';
        renderEmojiGrid();
      });
      grid.appendChild(b);
    });
    catDiv.innerHTML = `<div class="emoji-cat-label">${cat}</div>`;
    catDiv.appendChild(grid);
    wrap.appendChild(catDiv);
  });
}

document.getElementById('editGroupBtn').addEventListener('click', () => {
  if(state.group === '*') return;
  const g = groups.find(x => x.slug === state.group);
  editingGroupSlug = g.slug;
  pendingEmoji = g.emoji || '🗂️';
  document.getElementById('groupEditorTitle').textContent = 'Настроить группу';
  document.getElementById('groupNameInput').value = g.display_name;
  document.getElementById('emojiPreview').textContent = pendingEmoji;
  document.getElementById('customEmojiInput').value = '';
  renderEmojiGrid();
  document.getElementById('groupEditorOverlay').classList.add('on');
});

document.getElementById('addGroupBtn').addEventListener('click', () => {
  editingGroupSlug = null;
  pendingEmoji = '🗂️';
  document.getElementById('groupEditorTitle').textContent = 'Новая группа';
  document.getElementById('groupNameInput').value = '';
  document.getElementById('emojiPreview').textContent = pendingEmoji;
  document.getElementById('customEmojiInput').value = '';
  renderEmojiGrid();
  document.getElementById('groupEditorOverlay').classList.add('on');
});

document.getElementById('customEmojiInput').addEventListener('input', e => {
  const v = e.target.value.trim();
  if(v){ pendingEmoji = v; document.getElementById('emojiPreview').textContent = v; }
});

document.getElementById('groupEditorCancel').addEventListener('click', () => {
  document.getElementById('groupEditorOverlay').classList.remove('on');
});

document.getElementById('groupEditorSave').addEventListener('click', async () => {
  const name = document.getElementById('groupNameInput').value.trim();
  if(!name) return;
  document.getElementById('groupEditorOverlay').classList.remove('on');
  if(editingGroupSlug === null){
    const resp = await apiFetch('/api/groups', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, emoji: pendingEmoji }),
    });
    if(!resp.ok){ alert('Не удалось создать группу'); return; }
    const created = await resp.json();
    state.group = created.slug;
  } else {
    const resp = await apiFetch('/api/groups/' + encodeURIComponent(editingGroupSlug), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: name, emoji: pendingEmoji }),
    });
    if(!resp.ok){ alert('Не удалось сохранить группу'); return; }
  }
  await loadGroups();
  renderGroups();
  await loadProjects();
});

(async () => {
  const me = await requireAuth();
  if (!me) return;
  await loadGroups();
  renderGroups();
  await loadProjects();
  if(location.hash === '#everywhere'){
    document.getElementById('everywhereRow').click();
  }
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Править `hermes-web/static/home.html`** — включить плитку «Работа с проектами» и плитку «Искать по всем темам»

Заменить (строки 72-76):

```html
    <a class="tile primary disabled" href="#" onclick="return false">
      <span class="ic">📂</span>
      <h3>Работа с проектами</h3>
      <p>Все группы и темы — скоро (следующий срез).</p>
    </a>
```

на:

```html
    <a class="tile primary" href="project-selector.html">
      <span class="ic">📂</span>
      <h3>Работа с проектами</h3>
      <p>Группы, поиск по смыслу, перенос между темами.</p>
    </a>
```

Заменить (строки 84-89):

```html
    <a class="tile disabled" href="#" onclick="return false">
      <span class="soon">скоро</span>
      <span class="ic">🔭</span>
      <h3>Искать по всем темам</h3>
      <p>Скоро — вместе с «Работой с проектами».</p>
    </a>
```

на:

```html
    <a class="tile" href="project-selector.html#everywhere">
      <span class="ic">🔭</span>
      <h3>Искать по всем темам</h3>
      <p>Сразу открыть поиск по всем группам и проектам.</p>
    </a>
```

- [ ] **Step 3: Ручная проверка локально**

```bash
cd /home/deploy/hermes-cn-ru/hermes-web
API_SERVER_KEY=dummy HERMES_WEB_COOKIE_SECURE=false PROJECT_INDEX_PLUGIN_DIR=../hermes-plugins \
  /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3 run.py
```

В другом терминале: `curl -s localhost:8643/project-selector.html | head -5` — должна вернуться разметка страницы. Остановить (`Ctrl+C`) после проверки — полная проверка с реальным логином и данными делается на VPS в Task 6.

- [ ] **Step 4: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/
git commit -m "feat(hermes-web): project-selector.html подключён к реальному API, плитки в home.html включены"
```

---

## Task 6: Развёртывание на VPS и приёмочный тест

**Files:**
- Deploy (rsync, не git): `hermes-plugins/project_index/` → `hermes@212.115.55.116:~/.hermes/plugins/project_index/`, `hermes-web/` → `hermes@212.115.55.116:~/hermes-web/`
- Modify (в этом репозитории): `docs/state.md`, `docs/changelog.md`

**Interfaces:** нет новых — операционная задача поверх уже протестированного кода Task 1-5.

- [ ] **Step 1: Скопировать обновлённый `project_index` на сервер (без `__pycache__`)**

```bash
rsync -av --exclude='__pycache__' --exclude='*.pyc' --exclude='index.db' \
  /home/deploy/hermes-cn-ru/hermes-plugins/project_index/ \
  -e "ssh -i ~/.ssh/id_ed25519_hermes_user" \
  hermes@212.115.55.116:~/.hermes/plugins/project_index/
```

(`index.db` намеренно исключён — на сервере уже есть настоящий индекс с реальными проектами `dem`/`rost`, перезаписывать его файлом из rsync нельзя; миграция колонки `description` произойдёт автоматически при следующем обращении к `get_connection`, см. Task 1.)

- [ ] **Step 2: Перезапустить `hermes-gateway.service` (плагин `project_index` живёт внутри его процесса)**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  systemctl --user restart hermes-gateway.service
  sleep 2
  systemctl --user status hermes-gateway.service --no-pager | head -5
'
```

Expected: `Active: active (running)`.

- [ ] **Step 3: Скопировать обновлённый `hermes-web` на сервер (без `tests/`, `__pycache__`, `.db`)**

```bash
rsync -av --exclude='__pycache__' --exclude='*.pyc' --exclude='*.db' --exclude='tests' \
  /home/deploy/hermes-cn-ru/hermes-web/ \
  -e "ssh -i ~/.ssh/id_ed25519_hermes_user" \
  hermes@212.115.55.116:~/hermes-web/
```

- [ ] **Step 4: Прогнать тесты на сервере реальным интерпретатором**

```bash
scp -i ~/.ssh/id_ed25519_hermes_user -r hermes-web/tests hermes@212.115.55.116:~/hermes-web/
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  cd ~/hermes-web && PROJECT_INDEX_PLUGIN_DIR=/home/hermes/.hermes/plugins \
  ~/.hermes/hermes-agent/venv/bin/python3.11 -m pytest tests/ -v
'
```

Expected: все тесты `passed` (45 из среза 1+2 + новые из Task 2-4 этого плана).

`project_index` на сервере деплоится без каталога `tests/` (как и в под-проекте A) — отдельный прогон его тестов на сервере не нужен: они уже прогнаны локально реальным (пиновым) окружением в Task 1, Step 8, а серверный код идентичен благодаря `rsync` без модификаций в пути.

- [ ] **Step 5: Перезапустить `hermes-web.service`**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  systemctl --user restart hermes-web.service
  sleep 2
  systemctl --user status hermes-web.service --no-pager | head -8
'
```

Expected: `Active: active (running)`.

- [ ] **Step 6: Приёмочный тест — реальный логин и список проектов через домен**

```bash
curl -s -c /tmp/hermes-web-cookies.txt -X POST https://hermes.blackboxbegin.space/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"dem","password":"<пароль dem, сгенерированный в срезе 1+2>"}'
```

Expected: `{"username": "dem", "role": "owner", "display_name": "Дмитрий"}`.

```bash
curl -s -b /tmp/hermes-web-cookies.txt "https://hermes.blackboxbegin.space/api/groups"
curl -s -b /tmp/hermes-web-cookies.txt "https://hermes.blackboxbegin.space/api/projects?group=ALL&since=month&status=active"
```

Expected: в `/api/groups` — минимум группа `ALL`; в `/api/projects` — проекты, созданные через «Быстрый чат» в срезе 1+2 (если создавались в последний месяц) с непустым `description`.

Затем — глазами через браузер (не curl): открыть `https://hermes.blackboxbegin.space/home.html`, войти под `dem`, кликнуть «Работа с проектами», убедиться что список отображается, кликнуть «+ новая группа», создать тестовую группу «Тест», перенести в неё любой проект через панель `about.md` → «Перенести в другую группу», перезагрузить страницу и убедиться, что группа и перенос сохранились, переключить фильтр «давность» на «всё время» и убедиться, что список не сужается ошибочно.

- [ ] **Step 7: Убрать тестовую группу, если создавалась при ручной проверке**

Если в Step 6 создавалась группа «Тест» — перенести проект обратно (через тот же UI) и удалить пустую папку на сервере вручную:

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 'rmdir ~/workspace/dem/test 2>/dev/null || true'
rm -f /tmp/hermes-web-cookies.txt
```

(Строку `group_meta` для пустой удалённой группы можно оставить — не мешает, аналогично мелким тестовым остаткам после приёмки среза 1+2.)

- [ ] **Step 8: Обновить `docs/state.md` и `docs/changelog.md`**

В `state.md`: отметить срез 3, часть 1 («Группы/Проекты — навигация») как выполненную и выкаченную, со ссылкой на этот план; следующий шаг — срез 3, часть 2 (полноценный `project-workspace.html`) или под-проект C (админ-панель).

В `changelog.md`: новая запись за дату выполнения — что реализовано (фильтруемый листинг в `project_index`, метаданные групп, `project-selector.html`), что проверено (реальный список групп/проектов на домене, создание группы, перенос проекта).

- [ ] **Step 9: Commit и snapshot**

```bash
cd /home/deploy/hermes-cn-ru
git add docs/state.md docs/changelog.md
bash scripts/snapshot.sh "hermes-web: срез 3 (Группы/Проекты — навигация) реализован и выкачен на hermes.blackboxbegin.space"
```

---

## Self-Review (сверка со спеком)

- Расширение `project_index` (описание/mtime как `updated_at`/фильтруемый листинг/детали проекта) — покрыто Task 1.
- Метаданные групп (`group_meta`, slug не переименовывается) — покрыто Task 2.
- Слаги с транслитерацией, создание/редактирование/закрепление групп, дефолтный фильтр `month`+`active`, серверная фильтрация по времени и статусу — покрыто Task 3, Task 4.
- Все 7 эндпоинтов спека (`GET/POST /api/groups`, `PUT /api/groups/{slug}`, `GET /api/projects`, `GET /api/projects/detail`, `POST /api/projects/search`, `POST /api/projects/move`) — покрыто Task 4.
- `move_project`/`search_similar` через `run_in_executor` (не блокируют event loop) — покрыто Task 3.
- Обновление `chat_sessions.project_path` при переносе проекта — покрыто Task 2 (`update_chat_session_project_path`) + Task 3 (`move_project` вызывает её).
- Фронтенд: список групп/проектов с реального бэкенда, ряд фильтров «давность», попап создания/редактирования группы, попап переноса, ленивая подгрузка «Опорные точки»/«На чём остановились», RAG-поиск через `/api/projects/search`, «Открыть проект» — плейсхолдер — покрыто Task 5.
- Включение плиток в `home.html` — покрыто Task 5, Step 2.
- Автоархивация «старше года» — сознательно не реализована ни одной задачей (вне рамок спека).
- Полноценный `project-workspace.html` — сознательно не тронут (вне рамок спека, отдельный следующий план).
- Деплой (rsync `project_index` + `hermes-web`, перезапуск обоих сервисов, приёмочный тест на домене) — покрыто Task 6.
