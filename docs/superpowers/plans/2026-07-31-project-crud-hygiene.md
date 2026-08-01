# CRUD-гигиена проектов — удаление, создание из списка, теги — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать Группу A бэклога живого тестирования — три
независимые операции над проектами, которых сегодня физически нет ни в
коде, ни в UI: **A1** удаление проекта (мягкое, в `.trash/`), **A2**
создание проекта из `project-selector.html` в выбранную группу (не
только через «Быстрый чат» в `ALL`), **A3** редактирование тегов/статуса
как структурированного UI-поля (не сырого YAML-фронтматтера). Все
технические решения и оба открытых вопроса (A1 — мягкое удаление, A3 — с
автокомплитом) согласованы пользователем 2026-07-31, см.
`docs/superpowers/specs/2026-07-31-project-crud-hygiene-design.md`.

**Architecture:** Плагин `hermes-plugins/project_index/core.py` получает
две новые функции — `delete_project` (по образцу уже существующего
`move_project`: тот же двухслойный путь-контроль, `shutil.move` в
`.trash/` вместо `rmtree`) и `update_project_metadata` (узкий позиционный
патч YAML-блока `about.md`, тот же приём, что `_rewrite_title`). Веб-бэкенд
(`hermes_web/projects.py`, `hermes_web/quickchat.py`, `hermes_web/app.py`)
получает тонкие async-обёртки (`run_in_executor`, тот же паттерн, что уже
есть у `move_project`/`search_projects`) и три новых HTTP-эндпоинта.
Фронтенд (`static/project-selector.html`) получает кнопку «Удалить
проект», кнопку «+ новый проект» и редактируемые чипы тегов + переключатель
статуса — всё поверх уже существующих `renderPanel`/`renderMain`.

**Tech Stack:** Python 3.12, aiohttp, PyYAML, pytest + pytest-asyncio
(backend); ванильный JS без сборщика (фронтенд, тот же стиль, что и весь
`project-selector.html`).

## Global Constraints

- A1 — **мягкое удаление**: `shutil.move` в скрытую `user_root/.trash/`,
  никогда `shutil.rmtree`. Восстановление — вручную по SSH, отдельного
  UI/API для восстановления в этом срезе нет.
- Штамп перед именем в `.trash/` — `{дата}_{uuid8}_{leaf}` (тот же приём,
  что и у слага `create_quick_chat`) — гарантирует отсутствие коллизий при
  повторном удалении проекта с тем же именем.
- `delete_project` в плагине — **не** переиспользует `move_project` с
  фиктивной "группой" `.trash` (испортила бы уникальность имени через
  `leaving_all`/`entering_all`-логику дат-префиксов, не к месту для
  корзины) — отдельная, короткая функция.
- A2 — создание проекта **не** поднимает Hermes-сессию сразу (та же
  причина, что уже проверена ревью 2026-07-26 для похожего сценария: без
  сетевого вызова — без риска осиротевшего проекта при сбое Hermes).
  Сессия создаётся лениво при первом открытии через уже существующий
  `get_or_open_session`.
- A2 — имя папки: для группы `ALL` дата-префиксный технический слаг (как
  у «Быстрого чата»), для любой другой группы — человекочитаемый слаг из
  названия через уже существующую `projects.slugify` (не заводить второй
  slugify). Коллизия имени — чистая ошибка 400, без тихого автосуффикса.
- A3 — `_rewrite_frontmatter` патчит **только** YAML-блок `about.md`,
  остальной текст (описание/опорные точки/на чём остановились) не
  трогает — не пересобирать весь файл из отдельных полей.
- A3 — после правки тегов/статуса **обязательна** переиндексация
  (`index_update`) — `_embed_text` включает теги в текст эмбеддинга, без
  переиндексации RAG-поиск разойдётся с отображаемыми тегами.
- `list_groups` должна игнорировать скрытые директории (`.trash` и любые
  будущие служебные папки с точкой) — общее правило, не точечное
  исключение одного имени.
- Все три backend-функции переиспользуют существующий двухслойный
  путь-контроль (`resolve_project_path` + требование `about.md`), уже
  проверенный на path traversal ревью 2026-07-26 для `move_project` — не
  вводить отдельную/новую валидацию пути.
- Фронтенд-часть (Задачи 2, 4, 6) — без автоматических тестов (в
  репозитории нет JS-тестового фреймворка, тот же прецедент, что и в
  D-013/D-014/B1) — только чтение диффа построчно на ревью и разовая
  ручная проверка в браузере на живой приёмке.
- Тесты гонять из `hermes-web/`:
  `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/ -v`
  и из `hermes-plugins/`: `<venv>/bin/python3 -m pytest tests/ -v` (без
  переменной окружения — `conftest.py` там сам добавляет путь). venv:
  `/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv`
  (если недоступен — пересоздать по образцу плана
  `docs/superpowers/plans/2026-07-26-web-backend-auth-chat.md`, см.
  `docs/state.md`, раздел «Главные подводные камни»). Базовая линия перед
  этим срезом: **219 тестов `hermes-web`, 64 теста `hermes-plugins`
  проходят** (см. `docs/state.md`, точка возобновления 2026-07-31).

---

### Task 1: A1 backend — `delete_project` в плагине, обёртка, `list_groups`, HTTP-эндпоинт

**Files:**
- Modify: `hermes-plugins/project_index/core.py` (импорт `uuid`, новая
  функция `delete_project`)
- Modify: `hermes-web/hermes_web/projects.py` (обёртка `delete_project`,
  фикс `list_groups`)
- Modify: `hermes-web/hermes_web/app.py` (импорт уже есть — `projects`
  через `from . import auth, hermes_client, projects, quickchat, storage,
  workspace`; новый хендлер `handle_delete_project` + роут)
- Test: `hermes-plugins/tests/test_core.py`, `hermes-plugins/tests/test_storage.py`,
  `hermes-web/tests/test_projects.py`, `hermes-web/tests/test_app.py`

**Interfaces:**
- Consumes: `resolve_project_path(user, project_path, workspace_root) -> str`
  (уже есть, `core.py:78`), `storage.delete_project(conn, path) -> None`
  (уже есть, `project_index/storage.py:100-102`, реализована, но никем не
  вызывается — просто `DELETE FROM projects WHERE path = ?`).
- Produces:
  - `project_index_core.delete_project(user: str, project_path: str, workspace_root=WORKSPACE_ROOT, db_path=DB_PATH) -> dict`
    — возвращает `{"old_path": str, "trashed_path": str}`. Используется
    Task 1 (`projects.py`) и косвенно нигде больше в этом плане.
  - `hermes_web.projects.delete_project(user: str, project_path: str, config, db_conn) -> dict`
    — та же форма ответа, плюс переносит `chat_session.project_path` вслед
    за файлами. Используется Task 1 (`app.py`).
  - HTTP `POST /api/projects/delete` с телом `{"path": str}`, отвечает
    `{"old_path": str, "trashed_path": str}` (200) или `{"error": str}` (400).

- [ ] **Step 1: Написать падающие тесты `delete_project` в `hermes-plugins/tests/test_core.py`**

Добавить в конец файла (после `test_list_projects_for_user_does_not_return_raw_embedding`):

```python
def test_delete_project_moves_to_trash_and_removes_from_index(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/proj")
    db_path = str(tmp_path / "index.db")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: [0.1])
    core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path, api_key="key")

    result = core.delete_project("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path)

    assert not os.path.exists(str(tmp_path / "dem" / "ALL" / "proj"))
    assert os.path.isdir(result["trashed_path"])
    assert os.path.isfile(os.path.join(result["trashed_path"], "about.md"))
    assert os.path.dirname(result["trashed_path"]) == str(tmp_path / "dem" / ".trash")
    conn = core.storage.get_connection(db_path)
    assert core.storage.get_project(conn, result["old_path"]) is None


def test_delete_project_not_a_project_raises(tmp_path):
    (tmp_path / "dem" / "ALL" / "empty").mkdir(parents=True)
    with pytest.raises(core.ProjectIndexError):
        core.delete_project("dem", "dem/ALL/empty", workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"))
    assert os.path.isdir(str(tmp_path / "dem" / "ALL" / "empty"))


def test_delete_project_twice_with_same_leaf_does_not_collide(tmp_path):
    _write_project(tmp_path, "dem/ALL/proj")
    db_path = str(tmp_path / "index.db")

    result1 = core.delete_project("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path)
    _write_project(tmp_path, "dem/ALL/proj")
    result2 = core.delete_project("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path)

    assert result1["trashed_path"] != result2["trashed_path"]
    assert os.path.isdir(result1["trashed_path"])
    assert os.path.isdir(result2["trashed_path"])


def test_delete_project_cross_user_raises(tmp_path):
    _write_project(tmp_path, "dem/ALL/proj")
    (tmp_path / "rost").mkdir()
    with pytest.raises(core.ProjectIndexError):
        core.delete_project("rost", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"))
    assert os.path.isdir(str(tmp_path / "dem" / "ALL" / "proj"))
```

- [ ] **Step 2: Прогнать новые тесты, убедиться что падают**

Run: `cd hermes-plugins && <venv>/bin/python3 -m pytest tests/test_core.py -k delete_project -v`
Expected: FAIL — `AttributeError: module 'project_index.core' has no attribute 'delete_project'`.

- [ ] **Step 3: Написать падающий тест на `storage.delete_project` в `hermes-plugins/tests/test_storage.py`**

Добавить после `test_rename_path_moves_the_row`:

```python
def test_delete_project_removes_the_row(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/p/a", "т", [], "active", None, "2026-01-01T00:00:00")
    storage.delete_project(conn, "/p/a")
    assert storage.get_project(conn, "/p/a") is None
```

Эта функция (`storage.delete_project`) уже реализована (просто никогда не
вызывалась) — тест должен пройти сразу, без red-шага. Всё равно прогнать
(Step 4), чтобы убедиться, что тест реально что-то проверяет.

- [ ] **Step 4: Прогнать тест `test_delete_project_removes_the_row`**

Run: `cd hermes-plugins && <venv>/bin/python3 -m pytest tests/test_storage.py::test_delete_project_removes_the_row -v`
Expected: PASS сразу (функция уже реализована).

- [ ] **Step 5: Реализовать `delete_project` в `hermes-plugins/project_index/core.py`**

Найти блок импортов:

```python
import datetime
import os
import re
import shutil
from pathlib import Path
from typing import Optional
```

Заменить на:

```python
import datetime
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Optional
```

Найти константы после импортов (`WORKSPACE_ROOT = ...` / `DB_PATH = ...`)
и добавить рядом с ними:

```python
TRASH_DIR_NAME = ".trash"
```

Добавить новую функцию сразу после `move_project` (перед `reindex_all`):

```python
def delete_project(
    user: str,
    project_path: str,
    workspace_root: str = WORKSPACE_ROOT,
    db_path: str = DB_PATH,
) -> dict:
    root = os.path.realpath(workspace_root)
    old_path = resolve_project_path(user, project_path, workspace_root)
    if not os.path.isfile(_about_md_path(old_path)):
        raise ProjectIndexError(f"'{project_path}' не проект (нет about.md)")

    user_root = os.path.join(root, user)
    trash_dir = os.path.join(user_root, TRASH_DIR_NAME)
    os.makedirs(trash_dir, exist_ok=True)

    leaf = os.path.basename(old_path)
    stamp = f"{datetime.date.today().isoformat()}_{uuid.uuid4().hex[:8]}"
    trashed_path = os.path.join(trash_dir, f"{stamp}_{leaf}")

    shutil.move(old_path, trashed_path)

    conn = storage.get_connection(db_path)
    try:
        storage.delete_project(conn, old_path)
    finally:
        conn.close()

    return {"old_path": old_path, "trashed_path": trashed_path}
```

- [ ] **Step 6: Прогнать новые тесты `test_core.py`, убедиться что проходят**

Run: `cd hermes-plugins && <venv>/bin/python3 -m pytest tests/test_core.py -k delete_project -v`
Expected: 4 passed.

- [ ] **Step 7: Прогнать весь `hermes-plugins/tests/`, убедиться что ничего не сломалось**

Run: `cd hermes-plugins && <venv>/bin/python3 -m pytest tests/ -v`
Expected: 69 passed (64 базовых + 4 из `test_core.py` + 1 из `test_storage.py`).

- [ ] **Step 8: Написать падающие тесты обёртки `hermes_web.projects.delete_project` в `hermes-web/tests/test_projects.py`**

Добавить в конец файла:

```python
@pytest.mark.asyncio
async def test_delete_project_runs_in_executor(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    calling_thread = threading.current_thread()
    seen = {}

    def fake_delete_project(user, project_path, **kwargs):
        seen["thread"] = threading.current_thread()
        return {"old_path": "/old", "trashed_path": "/old/.trash/stamp_old"}

    monkeypatch.setattr(projects.project_index_core, "delete_project", fake_delete_project)
    result = await projects.delete_project("dem", "dem/ALL/a", config, conn)

    assert result["trashed_path"] == "/old/.trash/stamp_old"
    # delete_project ходит на диск (shutil.move) — обязано происходить вне event loop.
    assert seen["thread"] is not calling_thread
    assert seen["thread"] is not threading.main_thread()


@pytest.mark.asyncio
async def test_delete_project_updates_chat_session_path(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    old_path = str(tmp_path / "workspace" / "dem" / "ALL" / "a")
    storage.create_chat_session(conn, "chat1", "dem", old_path, "web_1", created_at=1.0)

    result = await projects.delete_project("dem", "dem/ALL/a", config, conn)

    row = storage.get_chat_session(conn, "chat1")
    assert row["project_path"] == result["trashed_path"]


def test_list_groups_excludes_trash_directory(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    user_root = tmp_path / "workspace" / "dem"
    (user_root / ".trash").mkdir(parents=True)
    (user_root / "1С").mkdir()

    groups = projects.list_groups("dem", conn, config)
    slugs = {g["slug"] for g in groups}
    assert ".trash" not in slugs
    assert "1С" in slugs
```

- [ ] **Step 9: Прогнать новые тесты `test_projects.py`, убедиться что падают**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/test_projects.py -k "delete_project or excludes_trash" -v`
Expected: 3 FAIL — `delete_project` не определена в `projects` (`AttributeError`),
`test_list_groups_excludes_trash_directory` падает на `assert ".trash" not in slugs`
(`.trash` сегодня виден как обычная группа).

- [ ] **Step 10: Реализовать обёртку `delete_project` и фикс `list_groups` в `hermes_web/projects.py`**

Найти:

```python
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

Добавить сразу после:

```python


async def delete_project(user: str, project_path: str, config, db_conn) -> dict:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        functools.partial(project_index_core.delete_project, user, project_path, **_project_index_kwargs(config)),
    )
    storage.update_chat_session_project_path(db_conn, result["old_path"], result["trashed_path"])
    return result
```

Найти в `list_groups`:

```python
    disk_slugs = set()
    if os.path.isdir(user_root):
        disk_slugs = {name for name in os.listdir(user_root) if os.path.isdir(os.path.join(user_root, name))}
    disk_slugs.add(ALL_GROUP_SLUG)
```

Заменить на:

```python
    disk_slugs = set()
    if os.path.isdir(user_root):
        disk_slugs = {
            name for name in os.listdir(user_root)
            if os.path.isdir(os.path.join(user_root, name)) and not name.startswith(".")
        }
    disk_slugs.add(ALL_GROUP_SLUG)
```

- [ ] **Step 11: Прогнать новые тесты `test_projects.py`, убедиться что проходят**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/test_projects.py -k "delete_project or excludes_trash" -v`
Expected: 3 passed.

- [ ] **Step 12: Написать падающие тесты HTTP-эндпоинта в `hermes-web/tests/test_app.py`**

Добавить в конец файла:

```python
@pytest.mark.asyncio
async def test_delete_project_requires_auth(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.post("/api/projects/delete", json={"path": "dem/ALL/a"})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_delete_project_success(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_delete_project(user, path, config, db_conn):
        assert path == "dem/ALL/a"
        return {"old_path": "/w/dem/ALL/a", "trashed_path": "/w/dem/.trash/2026-08-01_ab12cd34_a"}

    monkeypatch.setattr("hermes_web.app.projects.delete_project", fake_delete_project)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/delete", json={"path": "dem/ALL/a"})
    assert resp.status == 200
    body = await resp.json()
    assert body["trashed_path"] == "/w/dem/.trash/2026-08-01_ab12cd34_a"


@pytest.mark.asyncio
async def test_delete_project_not_a_project_returns_400(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_delete_project(user, path, config, db_conn):
        raise projects.project_index_core.ProjectIndexError("не проект (нет about.md)")

    monkeypatch.setattr("hermes_web.app.projects.delete_project", fake_delete_project)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/delete", json={"path": "dem/ALL/x"})
    assert resp.status == 400
```

- [ ] **Step 13: Прогнать новые тесты `test_app.py`, убедиться что падают**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/test_app.py -k delete_project -v`
Expected: 3 FAIL — маршрут `/api/projects/delete` не зарегистрирован
(404 вместо ожидаемых 401/200/400).

- [ ] **Step 14: Реализовать хендлер и роут в `hermes_web/app.py`**

Найти:

```python
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

Добавить сразу после:

```python


async def handle_delete_project(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    path = str(body.get("path", ""))
    try:
        result = await projects.delete_project(user["username"], path, request.app["quickchat_config"], request.app["db"])
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)
```

Найти:

```python
    app.router.add_post("/api/projects/move", handle_move_project)
```

Заменить на:

```python
    app.router.add_post("/api/projects/move", handle_move_project)
    app.router.add_post("/api/projects/delete", handle_delete_project)
```

- [ ] **Step 15: Прогнать новые тесты `test_app.py`, убедиться что проходят**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/test_app.py -k delete_project -v`
Expected: 3 passed.

- [ ] **Step 16: Прогнать весь `hermes-web/tests/`, убедиться что ничего не сломалось**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/ -v`
Expected: 225 passed (219 базовых + 3 новых в `test_projects.py` из Step 8
+ 3 новых в `test_app.py` из Step 12).

- [ ] **Step 17: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-plugins/project_index/core.py hermes-plugins/tests/test_core.py \
        hermes-plugins/tests/test_storage.py hermes-web/hermes_web/projects.py \
        hermes-web/hermes_web/app.py hermes-web/tests/test_projects.py hermes-web/tests/test_app.py
git commit -m "feat(project_index,hermes-web): удаление проекта (мягкое, в .trash/) + API"
```

---

### Task 2: A1 frontend — кнопка «Удалить проект»

**Files:**
- Modify: `hermes-web/static/project-selector.html`

**Interfaces:**
- Consumes: `POST /api/projects/delete` (Task 1) с телом `{"path": string}`,
  отвечает `{"old_path": string, "trashed_path": string}` (200) или
  `{"error": string}` (400/401).
- Produces: ничего нового для последующих задач.

- [ ] **Step 1: Добавить CSS-класс `.btn-danger`**

Найти в `<style>`:

```css
  .btn-primary{background:var(--gold);color:var(--sky-deep);border:none}
  .btn-secondary{background:none;color:var(--text-dim);border:1px solid var(--panel-line)}
  .btn-secondary:hover{color:var(--text);border-color:var(--violet)}
```

Заменить на:

```css
  .btn-primary{background:var(--gold);color:var(--sky-deep);border:none}
  .btn-secondary{background:none;color:var(--text-dim);border:1px solid var(--panel-line)}
  .btn-secondary:hover{color:var(--text);border-color:var(--violet)}
  .btn-danger{color:#e2726f;border-color:#e2726f}
  .btn-danger:hover{color:#ff8f8b;border-color:#ff8f8b}
```

- [ ] **Step 2: Добавить кнопку в `renderPanel` и обработчик клика**

Найти:

```js
    <div class="p-actions">
      <button class="btn-primary" id="openProjectBtn">Открыть проект →</button>
      <button class="btn-secondary" id="movePanelBtn">Перенести в другую группу</button>
    </div>
  `;
  document.getElementById('openProjectBtn').addEventListener('click', () => {
    location.href = 'project-workspace.html?path=' + encodeURIComponent(p.path);
  });
  document.getElementById('movePanelBtn').addEventListener('click', () => openMoveModal(p));
}
```

Заменить на:

```js
    <div class="p-actions">
      <button class="btn-primary" id="openProjectBtn">Открыть проект →</button>
      <button class="btn-secondary" id="movePanelBtn">Перенести в другую группу</button>
      <button class="btn-secondary btn-danger" id="deletePanelBtn">Удалить проект</button>
    </div>
  `;
  document.getElementById('openProjectBtn').addEventListener('click', () => {
    location.href = 'project-workspace.html?path=' + encodeURIComponent(p.path);
  });
  document.getElementById('movePanelBtn').addEventListener('click', () => openMoveModal(p));
  document.getElementById('deletePanelBtn').addEventListener('click', async () => {
    if (!confirm(`Удалить проект «${p.title}»? Будет перемещён в корзину, восстановить можно только вручную.`)) return;
    const resp = await apiFetch('/api/projects/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: p.path }),
    });
    if (resp.status === 401) { location.href = 'login.html'; return; }
    if (!resp.ok) { alert('Не удалось удалить проект'); return; }
    document.body.classList.remove('panel-open');
    state.selectedProject = null;
    await loadGroups();
    renderGroups();
    await loadProjects();
  });
}
```

- [ ] **Step 3: Прочитать изменённый файл целиком, проверить синтаксис на глаз**

`renderPanel` теперь заканчивается тремя кнопками и тремя обработчиками —
убедиться, что фигурные скобки/шаблонные строки не разъехались (частая
ошибка при точечных заменах внутри template literal).

- [ ] **Step 4: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/static/project-selector.html
git commit -m "feat(hermes-web): кнопка «Удалить проект» в панели проекта"
```

---

### Task 3: A2 backend — создание проекта из списка, HTTP-эндпоинт

**Files:**
- Modify: `hermes-web/hermes_web/quickchat.py` (импорт `projects`, новая
  функция `create_project`)
- Modify: `hermes-web/hermes_web/app.py` (новый хендлер
  `handle_create_project` + роут)
- Test: `hermes-web/tests/test_quickchat.py`, `hermes-web/tests/test_app.py`

**Interfaces:**
- Consumes: `projects.slugify(name: str) -> str` (уже есть,
  `hermes_web/projects.py:47`), `_backfill_project_scaffold(project_root: str) -> None`
  (уже есть в `quickchat.py`), `_workspace_root(config)`,
  `_project_index_kwargs(config)` (обе уже есть в `quickchat.py`).
- Produces: `quickchat.create_project(db_conn, config: Config, user: str, group: str, title: str) -> dict`
  — возвращает `{"project_path": str, "group": str}`, бросает
  `QuickChatError` на пустое название или коллизию имени. HTTP
  `POST /api/projects` с телом `{"group": str, "title": str}`, отвечает тем
  же телом (200) или `{"error": str}` (400).

- [ ] **Step 1: Написать падающие тесты `create_project` в `hermes-web/tests/test_quickchat.py`**

Добавить в конец файла:

```python
@pytest.mark.asyncio
async def test_create_project_in_group_uses_human_readable_slug(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    result = await quickchat.create_project(conn, config, "dem", "1С", "Новый проект")

    expected_leaf = quickchat.projects.slugify("Новый проект")
    assert result["group"] == "1С"
    assert result["project_path"] == str(tmp_path / "workspace" / "dem" / "1С" / expected_leaf)
    assert os.path.isfile(os.path.join(result["project_path"], "about.md"))


@pytest.mark.asyncio
async def test_create_project_in_all_uses_date_prefixed_technical_slug(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    result = await quickchat.create_project(conn, config, "dem", "ALL", "Быстрый разговор про физику")

    leaf = os.path.basename(result["project_path"])
    assert quickchat.project_index_core._DATE_PREFIX_RE.match(leaf)
    assert leaf.split("_", 1)[1].startswith("chat-")


@pytest.mark.asyncio
async def test_create_project_creates_full_scaffold(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    result = await quickchat.create_project(conn, config, "dem", "1С", "Проект")

    for name in ("about.md", "AGENTS.md", "history.md"):
        assert os.path.isfile(os.path.join(result["project_path"], name))
    for bucket in ("source", "outer", "result"):
        assert os.path.isdir(os.path.join(result["project_path"], bucket))


@pytest.mark.asyncio
async def test_create_project_indexes_it(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    result = await quickchat.create_project(conn, config, "dem", "1С", "Учёт материалов")

    indexed = project_index_core.storage.get_project(
        project_index_core.storage.get_connection(config.project_index_db_path),
        result["project_path"],
    )
    assert indexed["title"] == "Учёт материалов"


@pytest.mark.asyncio
async def test_create_project_blank_title_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    with pytest.raises(quickchat.QuickChatError):
        await quickchat.create_project(conn, config, "dem", "ALL", "   ")


@pytest.mark.asyncio
async def test_create_project_collision_raises_and_does_not_touch_disk(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    first = await quickchat.create_project(conn, config, "dem", "1С", "Проект")
    mtime_before = os.path.getmtime(first["project_path"])

    with pytest.raises(quickchat.QuickChatError):
        await quickchat.create_project(conn, config, "dem", "1С", "Проект")

    assert os.path.getmtime(first["project_path"]) == mtime_before


@pytest.mark.asyncio
async def test_create_project_group_traversal_raises_and_does_not_touch_disk(tmp_path):
    """group приходит из HTTP (POST /api/projects) — та же уязвимость, что
    ревью 2026-07-26 нашло в move_project для new_group: без валидации
    итогового пути через resolve_project_path запрос вида
    group="../rost" создал бы папку в чужом пространстве пользователя."""
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    (tmp_path / "workspace" / "rost").mkdir(parents=True)

    with pytest.raises(quickchat.QuickChatError):
        await quickchat.create_project(conn, config, "dem", "../rost", "Угнанный проект")

    assert list((tmp_path / "workspace" / "rost").iterdir()) == []
```

- [ ] **Step 2: Прогнать новые тесты, убедиться что падают**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/test_quickchat.py -k create_project -v`
Expected: 7 FAIL — 6 с `AttributeError: module 'hermes_web.quickchat' has no attribute 'create_project'`,
плюс `test_create_project_group_traversal_raises_and_does_not_touch_disk` тоже
FAIL той же причиной (функция ещё не существует — падает на самом вызове,
не на отсутствии проверки, это ожидаемо на этом шаге).

- [ ] **Step 3: Реализовать `create_project` в `hermes_web/quickchat.py`**

Найти строку импорта:

```python
from . import hermes_client, permissions, storage, workspace
```

Заменить на:

```python
from . import hermes_client, permissions, projects, storage, workspace
```

Найти конец функции `_backfill_project_scaffold` (перед
`def _project_index_kwargs(config: Config) -> dict:`) и добавить после неё,
перед `async def create_quick_chat(...)`:

```python
async def create_project(db_conn, config: Config, user: str, group: str, title: str) -> dict:
    title = title.strip()
    if not title:
        raise QuickChatError("название проекта не может быть пустым")

    if group == "ALL":
        today = datetime.date.today().isoformat()
        leaf = f"{today}_chat-{uuid.uuid4().hex[:8]}"
    else:
        leaf = projects.slugify(title)

    # group приходит из HTTP — тот же двухслойный путь-контроль, что уже
    # проверен ревью 2026-07-26 для move_project's new_group: путь назначения
    # обязан резолвиться и проверяться ДО os.makedirs, иначе group="../rost"
    # создаёт проект в чужом пространстве пользователя.
    project_rel_path = os.path.join(user, group, leaf)
    try:
        project_abs_path = project_index_core.resolve_project_path(user, project_rel_path, _workspace_root(config))
    except project_index_core.ProjectIndexError as exc:
        raise QuickChatError(str(exc)) from exc

    if os.path.exists(project_abs_path):
        raise QuickChatError(f"в группе '{group}' уже есть проект с именем '{leaf}'")

    os.makedirs(project_abs_path, exist_ok=True)
    with open(os.path.join(project_abs_path, "about.md"), "w", encoding="utf-8") as fh:
        fh.write(ABOUT_MD_PLACEHOLDER.format(title=title))
    _backfill_project_scaffold(project_abs_path)

    loop = asyncio.get_running_loop()
    index_result = await loop.run_in_executor(
        None, functools.partial(project_index_core.index_update, user, project_rel_path, **_project_index_kwargs(config)),
    )

    return {"project_path": index_result["path"], "group": group}
```

Порядок функций в файле должен остаться: `_backfill_project_scaffold` →
`create_project` (новая) → `_project_index_kwargs` → `_workspace_root` →
`_sandbox_project_path` → `_new_hermes_session` → ... → `create_quick_chat`.
`create_project` использует `_workspace_root`/`_project_index_kwargs`,
объявленные ниже по файлу в исходном порядке — в Python это допустимо (обе
функции — top-level, разрешаются во время вызова, не во время определения).

- [ ] **Step 4: Прогнать новые тесты, убедиться что проходят**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/test_quickchat.py -k create_project -v`
Expected: 7 passed.

- [ ] **Step 5: Написать падающие тесты HTTP-эндпоинта в `hermes-web/tests/test_app.py`**

Добавить в конец файла:

```python
@pytest.mark.asyncio
async def test_create_project_requires_auth(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.post("/api/projects", json={"group": "ALL", "title": "x"})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_create_project_success(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_create_project(db_conn, config, user, group, title):
        assert group == "1С"
        assert title == "Новый проект"
        return {"project_path": "/w/dem/1С/novyy-proekt", "group": "1С"}

    monkeypatch.setattr("hermes_web.app.quickchat.create_project", fake_create_project)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects", json={"group": "1С", "title": "Новый проект"})
    assert resp.status == 200
    body = await resp.json()
    assert body["project_path"] == "/w/dem/1С/novyy-proekt"


@pytest.mark.asyncio
async def test_create_project_blank_title_returns_400(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_create_project(db_conn, config, user, group, title):
        raise quickchat.QuickChatError("название проекта не может быть пустым")

    monkeypatch.setattr("hermes_web.app.quickchat.create_project", fake_create_project)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects", json={"group": "ALL", "title": ""})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_create_project_group_traversal_returns_400(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_create_project(db_conn, config, user, group, title):
        raise quickchat.QuickChatError(f"'{user}/{group}/x' не принадлежит пространству пользователя '{user}'")

    monkeypatch.setattr("hermes_web.app.quickchat.create_project", fake_create_project)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects", json={"group": "../rost", "title": "Угнанный проект"})
    assert resp.status == 400
```

- [ ] **Step 6: Прогнать новые тесты, убедиться что падают**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/test_app.py -k create_project -v`
Expected: 4 FAIL — маршрут `POST /api/projects` не зарегистрирован (404).

- [ ] **Step 7: Реализовать хендлер и роут в `hermes_web/app.py`**

Найти:

```python
async def handle_list_projects(request: web.Request) -> web.Response:
```

Добавить непосредственно перед ней:

```python
async def handle_create_project(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    group = str(body.get("group", "ALL"))
    title = str(body.get("title", ""))
    try:
        result = await quickchat.create_project(request.app["db"], request.app["quickchat_config"], user["username"], group, title)
    except quickchat.QuickChatError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)


```

Найти:

```python
    app.router.add_get("/api/projects", handle_list_projects)
```

Заменить на:

```python
    app.router.add_get("/api/projects", handle_list_projects)
    app.router.add_post("/api/projects", handle_create_project)
```

- [ ] **Step 8: Прогнать новые тесты, убедиться что проходят**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/test_app.py -k create_project -v`
Expected: 4 passed.

- [ ] **Step 9: Прогнать весь `hermes-web/tests/`, убедиться что ничего не сломалось**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/ -v`
Expected: 236 passed (225 из Task 1 + 7 новых в `test_quickchat.py` из
Step 1 + 4 новых в `test_app.py` из Step 5).

- [ ] **Step 10: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/hermes_web/quickchat.py hermes-web/hermes_web/app.py \
        hermes-web/tests/test_quickchat.py hermes-web/tests/test_app.py
git commit -m "feat(hermes-web): создание проекта из списка в выбранную группу + API"
```

---

### Task 4: A2 frontend — кнопка «+ новый проект»

**Files:**
- Modify: `hermes-web/static/project-selector.html`

**Interfaces:**
- Consumes: `POST /api/projects` (Task 3) с телом `{"group": string, "title": string}`,
  отвечает `{"project_path": string, "group": string}` (200) или
  `{"error": string}` (400/401).
- Produces: ничего нового для последующих задач.

- [ ] **Step 1: Добавить кнопку в `.mainhead`**

Найти:

```html
  <div class="mainhead">
    <span class="emoji-lg" id="headEmoji">🗂️</span>
    <h2 id="headName">…</h2>
    <span id="headCount"></span>
    <button class="edit-group-btn" id="editGroupBtn">⚙️ настроить группу</button>
  </div>
```

Заменить на:

```html
  <div class="mainhead">
    <span class="emoji-lg" id="headEmoji">🗂️</span>
    <h2 id="headName">…</h2>
    <span id="headCount"></span>
    <button class="edit-group-btn" id="editGroupBtn">⚙️ настроить группу</button>
    <button class="btn-primary" id="addProjectBtn" style="margin-left:8px;padding:6px 14px;font-family:ui-monospace,Consolas,monospace;font-size:11px;border-radius:20px">+ новый проект</button>
  </div>
```

- [ ] **Step 2: Добавить обработчик клика**

Найти:

```js
document.getElementById('moveCancel').addEventListener('click', () => {
  document.getElementById('moveOverlay').classList.remove('on');
});
```

Добавить сразу после:

```js

document.getElementById('addProjectBtn').addEventListener('click', async () => {
  const title = prompt('Название нового проекта:');
  if (!title || !title.trim()) return;
  const resp = await apiFetch('/api/projects', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group: state.group, title }),
  });
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) { const err = await resp.json().catch(() => ({})); alert(err.error || 'Не удалось создать проект'); return; }
  const created = await resp.json();
  location.href = 'project-workspace.html?path=' + encodeURIComponent(created.project_path);
});
```

- [ ] **Step 3: Добавить видимость кнопки в `renderMain`**

Найти:

```js
  document.getElementById('editGroupBtn').style.display = (everywhere || searching) ? 'none' : 'inline-block';
```

Заменить на:

```js
  document.getElementById('editGroupBtn').style.display = (everywhere || searching) ? 'none' : 'inline-block';
  document.getElementById('addProjectBtn').style.display = (everywhere || searching) ? 'none' : 'inline-block';
```

- [ ] **Step 4: Прочитать изменённый файл целиком, проверить, что кнопка появляется в `.mainhead`, а обработчик — рядом с `moveCancel`**

- [ ] **Step 5: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/static/project-selector.html
git commit -m "feat(hermes-web): кнопка «+ новый проект» в списке проектов"
```

---

### Task 5: A3 backend — редактирование тегов/статуса в плагине, обёртка, HTTP-эндпоинт

**Files:**
- Modify: `hermes-plugins/project_index/core.py` (`_rewrite_frontmatter`,
  `update_project_metadata`)
- Modify: `hermes-web/hermes_web/projects.py` (обёртка `update_project_metadata`)
- Modify: `hermes-web/hermes_web/app.py` (хендлер
  `handle_update_project_metadata` + роут)
- Test: `hermes-plugins/tests/test_core.py`, `hermes-web/tests/test_projects.py`,
  `hermes-web/tests/test_app.py`

**Interfaces:**
- Consumes: `yaml.safe_load`/`yaml.safe_dump` (уже импортирован `yaml` в
  `core.py`), `_about_md_path`, `resolve_project_path`, `index_update`,
  `get_project_detail` (все уже есть в `core.py`).
- Produces: `project_index_core.update_project_metadata(user, project_path, tags=None, status=None, workspace_root=WORKSPACE_ROOT, db_path=DB_PATH, api_key=None) -> dict`
  — возвращает тот же формат, что и `get_project_detail`
  (`title/description/points/now/tags/status/path/group`).
  `hermes_web.projects.update_project_metadata(user, project_path, config, tags=None, status=None) -> dict`
  — тот же формат. HTTP `POST /api/projects/metadata` с телом
  `{"path": str, "tags": list|null, "status": str|null}`, отвечает тем же
  форматом (200) или `{"error": str}` (400).

- [ ] **Step 1: Написать падающие тесты `_rewrite_frontmatter`/`update_project_metadata` в `hermes-plugins/tests/test_core.py`**

Добавить в конец файла:

```python
ABOUT_MD_WITH_TAGS = """---
tags: [excel, работа]
status: active
---

# Название проекта
Тест

# Краткое описание
Описание

# Опорные точки
пункт

# На чём остановились
ничего
"""


def test_rewrite_frontmatter_updates_tags_preserves_status_and_body(tmp_path):
    project_dir = _write_project(tmp_path, "dem/ALL/proj", about_content=ABOUT_MD_WITH_TAGS)
    core._rewrite_frontmatter(str(project_dir), tags=["новый"])
    about = core._read_about(str(project_dir))
    assert about["tags"] == ["новый"]
    assert about["status"] == "active"
    assert about["title"] == "Тест"
    assert about["points"] == "пункт"


def test_rewrite_frontmatter_updates_status_only_preserves_tags(tmp_path):
    project_dir = _write_project(tmp_path, "dem/ALL/proj", about_content=ABOUT_MD_WITH_TAGS)
    core._rewrite_frontmatter(str(project_dir), status="archived")
    about = core._read_about(str(project_dir))
    assert about["status"] == "archived"
    assert about["tags"] == ["excel", "работа"]


def test_rewrite_frontmatter_missing_frontmatter_raises(tmp_path):
    project_dir = tmp_path / "dem" / "ALL" / "proj"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text("# Название проекта\nX\n", encoding="utf-8")
    with pytest.raises(core.ProjectIndexError):
        core._rewrite_frontmatter(str(project_dir), tags=["x"])


def test_update_project_metadata_updates_tags_and_reindexes(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/proj", about_content=ABOUT_MD_WITH_TAGS)
    db_path = str(tmp_path / "index.db")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: [0.2])

    result = core.update_project_metadata(
        "dem", "dem/ALL/proj", tags=["новый"], workspace_root=str(tmp_path), db_path=db_path, api_key="key",
    )

    assert result["tags"] == ["новый"]
    conn = core.storage.get_connection(db_path)
    row = core.storage.get_project(conn, result["path"])
    assert row["tags"] == ["новый"]
    assert row["embedding"] == pytest.approx([0.2])


def test_update_project_metadata_not_a_project_raises(tmp_path):
    (tmp_path / "dem" / "ALL" / "empty").mkdir(parents=True)
    with pytest.raises(core.ProjectIndexError):
        core.update_project_metadata(
            "dem", "dem/ALL/empty", tags=["x"], workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"),
        )
```

- [ ] **Step 2: Прогнать новые тесты, убедиться что падают**

Run: `cd hermes-plugins && <venv>/bin/python3 -m pytest tests/test_core.py -k "rewrite_frontmatter or update_project_metadata" -v`
Expected: 5 FAIL — `AttributeError` (обе функции ещё не существуют).

- [ ] **Step 3: Реализовать `_rewrite_frontmatter` и `update_project_metadata` в `hermes-plugins/project_index/core.py`**

Найти конец функции `move_project` (перед `def reindex_all(`) и добавить
после неё:

```python


def _rewrite_frontmatter(project_dir: str, tags: list | None = None, status: str | None = None) -> None:
    about_path = _about_md_path(project_dir)
    with open(about_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if not text.startswith("---"):
        raise ProjectIndexError("about.md: отсутствует YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ProjectIndexError("about.md: некорректный YAML frontmatter")

    frontmatter = yaml.safe_load(parts[1]) or {}
    if tags is not None:
        frontmatter["tags"] = tags
    if status is not None:
        frontmatter["status"] = status

    new_frontmatter_text = yaml.safe_dump(frontmatter, allow_unicode=True, default_flow_style=False)
    updated = f"---\n{new_frontmatter_text}---{parts[2]}"
    with open(about_path, "w", encoding="utf-8") as fh:
        fh.write(updated)


def update_project_metadata(
    user: str,
    project_path: str,
    tags: list | None = None,
    status: str | None = None,
    workspace_root: str = WORKSPACE_ROOT,
    db_path: str = DB_PATH,
    api_key: Optional[str] = None,
) -> dict:
    resolved = resolve_project_path(user, project_path, workspace_root)
    if not os.path.isfile(_about_md_path(resolved)):
        raise ProjectIndexError(f"'{project_path}' не проект (нет about.md)")

    _rewrite_frontmatter(resolved, tags=tags, status=status)
    index_update(user, project_path, workspace_root, db_path, api_key)
    return get_project_detail(user, project_path, workspace_root)
```

- [ ] **Step 4: Прогнать новые тесты, убедиться что проходят**

Run: `cd hermes-plugins && <venv>/bin/python3 -m pytest tests/test_core.py -k "rewrite_frontmatter or update_project_metadata" -v`
Expected: 5 passed.

- [ ] **Step 5: Прогнать весь `hermes-plugins/tests/`, убедиться что ничего не сломалось**

Run: `cd hermes-plugins && <venv>/bin/python3 -m pytest tests/ -v`
Expected: 74 passed (69 из Task 1 + 5 новых).

- [ ] **Step 6: Написать падающие тесты обёртки в `hermes-web/tests/test_projects.py`**

Добавить в конец файла:

```python
@pytest.mark.asyncio
async def test_update_project_metadata_runs_in_executor(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    calling_thread = threading.current_thread()
    seen = {}

    def fake_update_project_metadata(user, project_path, tags=None, status=None, **kwargs):
        seen["thread"] = threading.current_thread()
        return {"title": "т", "description": "d", "points": "", "now": "", "tags": tags or [], "status": status or "active", "path": "/p", "group": "ALL"}

    monkeypatch.setattr(projects.project_index_core, "update_project_metadata", fake_update_project_metadata)
    result = await projects.update_project_metadata("dem", "dem/ALL/a", config, tags=["x"])

    assert result["tags"] == ["x"]
    assert seen["thread"] is not calling_thread
    assert seen["thread"] is not threading.main_thread()


@pytest.mark.asyncio
async def test_update_project_metadata_updates_tags_on_disk(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")

    result = await projects.update_project_metadata("dem", "dem/ALL/a", config, tags=["новый"])

    assert result["tags"] == ["новый"]
    detail = projects.get_project_detail("dem", "dem/ALL/a", config)
    assert detail["tags"] == ["новый"]
```

- [ ] **Step 7: Прогнать новые тесты, убедиться что падают**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/test_projects.py -k update_project_metadata -v`
Expected: 2 FAIL — `AttributeError: module 'hermes_web.projects' has no attribute 'update_project_metadata'`.

- [ ] **Step 8: Реализовать обёртку в `hermes_web/projects.py`**

Найти конец функции `move_project` (конец файла) и добавить после неё:

```python


async def update_project_metadata(user: str, project_path: str, config, tags=None, status=None) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        functools.partial(
            project_index_core.update_project_metadata, user, project_path,
            tags=tags, status=status, **_project_index_kwargs(config),
        ),
    )
```

- [ ] **Step 9: Прогнать новые тесты, убедиться что проходят**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/test_projects.py -k update_project_metadata -v`
Expected: 2 passed.

- [ ] **Step 10: Написать падающие тесты HTTP-эндпоинта в `hermes-web/tests/test_app.py`**

Добавить в конец файла:

```python
@pytest.mark.asyncio
async def test_update_project_metadata_requires_auth(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.post("/api/projects/metadata", json={"path": "dem/ALL/a", "tags": ["x"]})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_update_project_metadata_success(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_update_project_metadata(user, path, config, tags=None, status=None):
        assert path == "dem/ALL/a"
        assert tags == ["физика", "задачник"]
        return {"title": "т", "description": "d", "points": "", "now": "", "tags": tags, "status": "active", "path": "/w/dem/ALL/a", "group": "ALL"}

    monkeypatch.setattr("hermes_web.app.projects.update_project_metadata", fake_update_project_metadata)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/metadata", json={"path": "dem/ALL/a", "tags": ["физика", "задачник"]})
    assert resp.status == 200
    body = await resp.json()
    assert body["tags"] == ["физика", "задачник"]


@pytest.mark.asyncio
async def test_update_project_metadata_not_found_returns_400(aiohttp_client, app_and_conn, monkeypatch):
    async def fake_update_project_metadata(user, path, config, tags=None, status=None):
        raise projects.project_index_core.ProjectIndexError("не проект (нет about.md)")

    monkeypatch.setattr("hermes_web.app.projects.update_project_metadata", fake_update_project_metadata)
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/metadata", json={"path": "dem/ALL/x", "tags": []})
    assert resp.status == 400
```

- [ ] **Step 11: Прогнать новые тесты, убедиться что падают**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/test_app.py -k update_project_metadata -v`
Expected: 3 FAIL — маршрут `/api/projects/metadata` не зарегистрирован (404).

- [ ] **Step 12: Реализовать хендлер и роут в `hermes_web/app.py`**

Найти хендлер `handle_delete_project`, добавленный в Task 1 (Step 14):

```python
async def handle_delete_project(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    path = str(body.get("path", ""))
    try:
        result = await projects.delete_project(user["username"], path, request.app["quickchat_config"], request.app["db"])
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)
```

Добавить сразу после него:

```python


async def handle_update_project_metadata(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    path = str(body.get("path", ""))
    tags = body.get("tags")
    status = body.get("status")
    try:
        result = await projects.update_project_metadata(user["username"], path, request.app["quickchat_config"], tags=tags, status=status)
    except projects.project_index_core.ProjectIndexError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response(result)
```

Затем найти:

```python
    app.router.add_post("/api/projects/move", handle_move_project)
    app.router.add_post("/api/projects/delete", handle_delete_project)
```

Заменить на:

```python
    app.router.add_post("/api/projects/move", handle_move_project)
    app.router.add_post("/api/projects/delete", handle_delete_project)
    app.router.add_post("/api/projects/metadata", handle_update_project_metadata)
```

- [ ] **Step 13: Прогнать новые тесты, убедиться что проходят**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/test_app.py -k update_project_metadata -v`
Expected: 3 passed.

- [ ] **Step 14: Прогнать весь `hermes-web/tests/`, убедиться что ничего не сломалось**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/python3 -m pytest tests/ -v`
Expected: 241 passed (236 из Task 3 + 2 новых в `test_projects.py` из
Step 6 + 3 новых в `test_app.py` из Step 10).

- [ ] **Step 15: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-plugins/project_index/core.py hermes-plugins/tests/test_core.py \
        hermes-web/hermes_web/projects.py hermes-web/hermes_web/app.py \
        hermes-web/tests/test_projects.py hermes-web/tests/test_app.py
git commit -m "feat(project_index,hermes-web): редактирование тегов/статуса проекта + API"
```

---

### Task 6: A3 frontend — редактируемые чипы тегов и переключатель статуса

**Files:**
- Modify: `hermes-web/static/project-selector.html`

**Interfaces:**
- Consumes: `POST /api/projects/metadata` (Task 5) с телом
  `{"path": string, "tags"?: string[], "status"?: string}`, отвечает тем же
  форматом, что и `GET /api/projects/detail` (200) или `{"error": string}` (400/401).
- Produces: ничего нового — последняя задача плана.

- [ ] **Step 1: Добавить CSS для редактируемых чипов**

Найти:

```css
  .p-tags{display:flex;gap:6px;flex-wrap:wrap}
  .p-tags span{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;color:#e7e2fa;background:rgba(173,159,230,.24);border:1px solid rgba(173,159,230,.65);padding:3px 9px;border-radius:20px}
```

Заменить на:

```css
  .p-tags{display:flex;gap:6px;flex-wrap:wrap}
  .p-tags span{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;color:#e7e2fa;background:rgba(173,159,230,.24);border:1px solid rgba(173,159,230,.65);padding:3px 9px;border-radius:20px}
  .p-tags-edit{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}
  .p-tags-edit span{font-family:ui-monospace,Consolas,monospace;font-size:10.5px;color:#e7e2fa;background:rgba(173,159,230,.24);border:1px solid rgba(173,159,230,.65);padding:3px 4px 3px 9px;border-radius:20px;display:inline-flex;align-items:center;gap:4px}
  .tag-remove{background:none;border:none;color:inherit;cursor:pointer;font-size:11px;padding:0 3px;opacity:.75}
  .tag-remove:hover{opacity:1}
  .tag-add-row{display:flex;gap:6px}
  .tag-add-row input{flex:1;background:var(--sky-deep);border:1px solid var(--panel-line);border-radius:8px;padding:6px 10px;color:var(--text);font-family:ui-monospace,Consolas,monospace;font-size:11px}
  .tag-add-row button{font-family:ui-monospace,Consolas,monospace;font-size:12px;padding:6px 12px;border-radius:8px;cursor:pointer;background:none;color:var(--text-dim);border:1px solid var(--panel-line)}
  .tag-add-row button:hover{color:var(--text);border-color:var(--violet)}
  #statusBadge{cursor:pointer}
```

- [ ] **Step 2: Заменить статичный блок статуса и тегов в `renderPanel` на редактируемый**

Найти:

```js
  document.getElementById('panelInner').innerHTML = `
    <button class="close" onclick="document.body.classList.remove('panel-open')">✕ закрыть</button>
    <span class="p-status ${escapeHtml(p.status)}">${escapeHtml(p.status)}</span>
    <h2>${escapeHtml(p.title)}</h2>
    <div class="p-group">${escapeHtml(pg.emoji || '🗂️')} ${escapeHtml(pg.display_name)}</div>
    <div class="p-block"><div class="lbl">Краткое описание</div><p>${escapeHtml(p.description)}</p></div>
    <div class="p-block"><div class="lbl">Опорные точки</div><p>${escapeHtml(points)}</p></div>
    <div class="p-block"><div class="lbl">На чём остановились</div><p>${escapeHtml(now)}</p></div>
    <div class="p-block"><div class="lbl">Tags</div><div class="p-tags">${p.tags.map(t => '<span>#' + escapeHtml(t) + '</span>').join('') || '<span style="opacity:.5">— нет —</span>'}</div></div>
    <div class="p-actions">
      <button class="btn-primary" id="openProjectBtn">Открыть проект →</button>
      <button class="btn-secondary" id="movePanelBtn">Перенести в другую группу</button>
      <button class="btn-secondary btn-danger" id="deletePanelBtn">Удалить проект</button>
    </div>
  `;
  document.getElementById('openProjectBtn').addEventListener('click', () => {
    location.href = 'project-workspace.html?path=' + encodeURIComponent(p.path);
  });
  document.getElementById('movePanelBtn').addEventListener('click', () => openMoveModal(p));
  document.getElementById('deletePanelBtn').addEventListener('click', async () => {
    if (!confirm(`Удалить проект «${p.title}»? Будет перемещён в корзину, восстановить можно только вручную.`)) return;
    const resp = await apiFetch('/api/projects/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: p.path }),
    });
    if (resp.status === 401) { location.href = 'login.html'; return; }
    if (!resp.ok) { alert('Не удалось удалить проект'); return; }
    document.body.classList.remove('panel-open');
    state.selectedProject = null;
    await loadGroups();
    renderGroups();
    await loadProjects();
  });
}
```

Заменить на:

```js
  document.getElementById('panelInner').innerHTML = `
    <button class="close" onclick="document.body.classList.remove('panel-open')">✕ закрыть</button>
    <span class="p-status ${escapeHtml(p.status)}" id="statusBadge" title="кликните, чтобы переключить active/archived">${escapeHtml(p.status)}</span>
    <h2>${escapeHtml(p.title)}</h2>
    <div class="p-group">${escapeHtml(pg.emoji || '🗂️')} ${escapeHtml(pg.display_name)}</div>
    <div class="p-block"><div class="lbl">Краткое описание</div><p>${escapeHtml(p.description)}</p></div>
    <div class="p-block"><div class="lbl">Опорные точки</div><p>${escapeHtml(points)}</p></div>
    <div class="p-block"><div class="lbl">На чём остановились</div><p>${escapeHtml(now)}</p></div>
    <div class="p-block">
      <div class="lbl">Tags</div>
      <div class="p-tags-edit" id="tagsEdit"></div>
      <div class="tag-add-row">
        <input id="newTagInput" list="tagSuggestions" placeholder="добавить тег…">
        <datalist id="tagSuggestions"></datalist>
        <button id="addTagBtn" type="button">+</button>
      </div>
    </div>
    <div class="p-actions">
      <button class="btn-primary" id="openProjectBtn">Открыть проект →</button>
      <button class="btn-secondary" id="movePanelBtn">Перенести в другую группу</button>
      <button class="btn-secondary btn-danger" id="deletePanelBtn">Удалить проект</button>
    </div>
  `;
  document.getElementById('openProjectBtn').addEventListener('click', () => {
    location.href = 'project-workspace.html?path=' + encodeURIComponent(p.path);
  });
  document.getElementById('movePanelBtn').addEventListener('click', () => openMoveModal(p));
  document.getElementById('deletePanelBtn').addEventListener('click', async () => {
    if (!confirm(`Удалить проект «${p.title}»? Будет перемещён в корзину, восстановить можно только вручную.`)) return;
    const resp = await apiFetch('/api/projects/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: p.path }),
    });
    if (resp.status === 401) { location.href = 'login.html'; return; }
    if (!resp.ok) { alert('Не удалось удалить проект'); return; }
    document.body.classList.remove('panel-open');
    state.selectedProject = null;
    await loadGroups();
    renderGroups();
    await loadProjects();
  });

  let editingTags = [...p.tags];

  function renderTagsEdit(){
    const wrap = document.getElementById('tagsEdit');
    wrap.innerHTML = editingTags.map(t =>
      `<span>#${escapeHtml(t)} <button class="tag-remove" data-tag="${escapeHtml(t)}" type="button">×</button></span>`
    ).join('') || '<span style="opacity:.5">— нет —</span>';
    wrap.querySelectorAll('.tag-remove').forEach(btn => {
      btn.addEventListener('click', () => {
        editingTags = editingTags.filter(t => t !== btn.dataset.tag);
        renderTagsEdit();
        saveTags();
      });
    });
  }

  function renderTagSuggestions(){
    const allTags = new Set();
    projects.forEach(pr => pr.tags.forEach(t => allTags.add(t)));
    const dl = document.getElementById('tagSuggestions');
    dl.innerHTML = [...allTags].map(t => `<option value="${escapeHtml(t)}">`).join('');
  }

  async function saveTags(){
    const resp = await apiFetch('/api/projects/metadata', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: p.path, tags: editingTags }),
    });
    if (resp.status === 401) { location.href = 'login.html'; return; }
    if (!resp.ok) { alert('Не удалось сохранить теги'); return; }
    const updated = await resp.json();
    p.tags = updated.tags;
    editingTags = [...updated.tags];
    const idx = projects.findIndex(x => x.path === p.path);
    if (idx !== -1) projects[idx].tags = updated.tags;
  }

  document.getElementById('addTagBtn').addEventListener('click', () => {
    const input = document.getElementById('newTagInput');
    const val = input.value.trim();
    if (!val || editingTags.includes(val)) return;
    editingTags.push(val);
    input.value = '';
    renderTagsEdit();
    saveTags();
  });

  document.getElementById('statusBadge').addEventListener('click', async () => {
    const newStatus = p.status === 'archived' ? 'active' : 'archived';
    const resp = await apiFetch('/api/projects/metadata', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: p.path, status: newStatus }),
    });
    if (resp.status === 401) { location.href = 'login.html'; return; }
    if (!resp.ok) { alert('Не удалось сохранить статус'); return; }
    const updated = await resp.json();
    p.status = updated.status;
    const idx = projects.findIndex(x => x.path === p.path);
    if (idx !== -1) projects[idx].status = updated.status;
    const badge = document.getElementById('statusBadge');
    badge.textContent = p.status;
    badge.className = 'p-status' + (p.status === 'archived' ? ' archived' : '');
    renderMain();
  });

  renderTagsEdit();
  renderTagSuggestions();
}
```

Обратить внимание: `editingTags`/`renderTagsEdit`/`renderTagSuggestions`/
`saveTags` объявлены **внутри** `renderPanel` (используют замыкание над
`p`) — при каждом вызове `renderPanel` (включая повторный вызов из
`openPanel` после подгрузки `detail`) они пересоздаются заново, старые
обработчики уничтожаются вместе со старыми DOM-узлами (`innerHTML`
целиком переписывает `panelInner`), поэтому дублирования слушателей не
возникает.

- [ ] **Step 3: Прочитать изменённый файл целиком, сверить, что `renderPanel` синтаксически корректна**

Особое внимание — вложенные шаблонные строки и то, что `renderTagsEdit()`/
`renderTagSuggestions()` вызываются в конце функции (после регистрации всех
обработчиков), а не до определения.

- [ ] **Step 4: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/static/project-selector.html
git commit -m "feat(hermes-web): редактируемые теги (с автокомплитом) и переключатель статуса"
```

---

## После реализации (не отдельная задача — ручные шаги)

1. **Финальное ревью всей ветки** — по конвенции проекта
   (subagent-driven-development), отдельный проход самой мощной моделью
   поверх всех 6 задач целиком, до деплоя. Обратить внимание ревьюера на:
   - двухслойный путь-контроль во всех трёх новых операциях (тот же
     `resolve_project_path` + `about.md`, что уже проверен на path
     traversal 2026-07-26 — убедиться, что не появилось нового способа
     обойти его через `group`/`title`/`path` в новых эндпоинтах);
   - `.trash/` действительно скрыта от `list_groups` и от обычного
     листинга проектов (`list_projects_filtered` фильтрует по префиксу
     пути пользователя — `.trash/...` формально попадает под тот же
     префикс и физически МОЖЕТ попасть в список, если что-то туда
     проиндексирует; сегодня `delete_project` явно удаляет строку из
     индекса при переносе, но стоит явно проверить, что случайный будущий
     вызов `reindex_all`/ручной `index_update` над файлом внутри `.trash/`
     не воскресит удалённый проект в списке — если да, обсудить с
     пользователем, нужен ли фильтр по префиксу `.trash/` в
     `list_projects_filtered`, это не было явно решено в спеке);
   - `create_project` не даёт создать проект с именем группы `.trash`
     (косвенно защищено тем, что `group` в `create_project` не
     валидируется отдельно — стоит проверить, не открывает ли это способ
     создать проект внутри `.trash/`, если пользователь передаст
     `group=".trash"` в `POST /api/projects`).
2. **Деплой на VPS** — **два разных пакета**, `~/.hermes/plugins/project_index/core.py`
   (рестарт **обоих**: `hermes-web.service` и `hermes-gateway.service`) и
   `hermes_web/{app,projects,quickchat}.py` + `static/project-selector.html`
   (рестарт только `hermes-web.service`) — см. спек, раздел «Деплой».
   Сделать резервную копию каждого файла в `~/.hermes-web-backups/`/
   `~/.hermes/backups/` перед `rsync`, как и в предыдущих срезах.
3. **Живая приёмка — по диску сервера (`ls -la`), не только по UI**
   (тот же урок B1/D-014): одноразовый `qa_temp`.
   - **Удаление**: создать тестовый проект, удалить его через UI,
     подтвердить `ls -la ~/workspace/qa_temp/` — папка реально пропала из
     группы и появилась внутри `~/workspace/qa_temp/.trash/` с
     префиксом-штампом; подтвердить, что `.trash` не отображается как
     группа в сайдбаре.
   - **Создание**: создать проект из `project-selector.html` в конкретной
     группе (не `ALL`), подтвердить `ls -la` — папка появилась с полным
     скаффолдом (`about.md`/`AGENTS.md`/`history.md`/`source/outer/result`)
     в правильной группе, с человекочитаемым слагом; открыть его сразу
     после создания — рабочий экран открывается, Hermes-сессия
     поднимается лениво без ошибки.
   - **Теги/статус**: открыть существующий проект, добавить тег через
     автокомплит и вручную, удалить тег, переключить статус — на каждом
     шаге подтвердить и в UI, и через `cat about.md` на сервере, что
     YAML-фронтматтер обновился, а остальные секции (описание/опорные
     точки/на чём остановились) не пострадали побайтово.
   - `qa_temp` и все его тестовые проекты удалить с сервера после
     проверки (включая содержимое `.trash/`, если оно осталось от теста
     удаления).
4. **`docs/state.md`/`docs/changelog.md`/`git snapshot.sh`** — как после
   каждого шага проекта (см. `CLAUDE.md`).
