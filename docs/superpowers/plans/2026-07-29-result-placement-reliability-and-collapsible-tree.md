# Диагностика размещения файлов + ручной перенос + сворачиваемое дерево — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать A1+A2 (диагностическое логирование + общее действие
«переместить/переименовать» на любом файле/папке любого bucket'а), Часть B
(сворачиваемые вложенные папки, по умолчанию свёрнуто) и Часть C (файлы вне
`source/outer/result` можно читать и редактировать, не только скачивать) —
все решения согласованы с пользователем 2026-07-29, см.
`docs/superpowers/specs/2026-07-29-result-placement-reliability-and-collapsible-tree-design.md`.

**Architecture:** Backend (`hermes_web/workspace.py`, `hermes_web/quickchat.py`,
`hermes_web/app.py`) получает: (1) `logging`-вызов в `quickchat.send_message`
на каждый ход; (2) новую функцию `move_entry` + HTTP-эндпоинт
`POST /api/projects/move-entry`, переиспользующую уже существующий паттерн
защиты пути (`resolve_file_path`); (3) снятие ограничения
`_require_within_bucket` в `save_file`. Фронтенд
(`static/project-workspace.html`) получает: кнопку «→» на каждом узле дерева
(вызывает новый эндпоинт), кликабельный треугольник-тоггл на папках с
персистентным (`localStorage` по проекту) состоянием, и правку клика по
`misc`-файлам, чтобы `.md`/`.txt` открывались в редакторе, как и везде.

**Tech Stack:** Python 3.12 / aiohttp (backend), ванильный JS без сборщика
(фронтенд, тот же стиль, что и весь `project-workspace.html`), pytest +
pytest-asyncio (тесты).

## Global Constraints

- A3 (дополнительное усиление формулировки системного сообщения) — **не
  делаем** в этом срезе (решение пользователя, см. спек).
- A2 — это ОБЩЕЕ действие «переместить/переименовать», работающее на любом
  файле/папке в любом bucket'е (`source`/`outer`/`result`/`misc`), а не узкая
  кнопка «в result/» только для `misc`. Не вводить отдельного узкого действия
  «в result» — один и тот же эндпоинт/UI для всех случаев.
- Часть B — дефолт при каждом открытии проекта: **все папки свёрнуты**.
  `localStorage` хранит только пути, которые пользователь явно развернул
  (отклонения от дефолта), а не факт «сворачивал ли вообще».
- Часть C — чтение (`read_file`) уже не ограничено bucket'ом, менять не нужно.
  Меняется только `save_file`: убрать вызов `_require_within_bucket`, оставить
  проверку расширения (`EDITABLE_EXTENSIONS`) и защиту от path traversal
  (`resolve_file_path`, которая никуда не убирается).
- Новый HTTP-эндпоинт называть `/api/projects/move-entry` — `/api/projects/move`
  уже занят под перенос ПРОЕКТА между группами (`hermes_web/projects.py`,
  не трогать).
- Логирование A1 — через стандартный `logging` (модуль `logging`, не print/
  stdout), не логировать текст системного сообщения целиком — только
  `chat_session_id`, `result_target` и булев флаг «усиление добавлено».
- Все новые backend-функции переиспользуют существующие исключения
  `WorkspaceError`/`WorkspaceCollisionError` и существующий HTTP-маппинг
  статусов (400/409/404), установленный `handle_project_mkdir`/
  `handle_project_upload` — не вводить новые типы ошибок или коды статусов.
- Фронтенд-часть (Части B, C-frontend, A2-frontend) — без автоматических
  тестов, только ручная проверка (в этом репозитории нет JS-тестового
  фреймворка — тот же прецедент, что и в D-013/предыдущих срезах).
- Тесты гонять из `hermes-web/`:
  `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/pytest tests/ -q`
  (venv — уже существующий под scratchpad предыдущей сессии, либо создать
  свежий по образцу плана 2026-07-26, если недоступен: aiohttp, argon2-cffi,
  pytest, pytest-asyncio). Базовая линия перед этим срезом: **175 тестов
  проходят**.

---

### Task 1: A1 — логирование `result_target`/факта усиления на каждый ход

**Files:**
- Modify: `hermes-web/hermes_web/quickchat.py`
- Test: `hermes-web/tests/test_quickchat.py`

**Interfaces:**
- Consumes: существующие `send_message(db_conn, http_session, config, chat_session_id, text, result_target=None)`,
  `_is_valid_result_target(result_target) -> bool` (уже есть, ничего не меняется в сигнатуре).
- Produces: ничего нового для других задач — чисто диагностика (лог-запись),
  не влияет на возвращаемое значение/побочные эффекты `send_message`.

- [ ] **Step 1: Написать падающий тест на логирование при валидном `result_target`**

Добавить в конец `tests/test_quickchat.py`:

```python
@pytest.mark.asyncio
async def test_send_message_logs_result_target_and_reinforcement(tmp_path, monkeypatch, caplog):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    host_project_path = str(tmp_path / "workspace" / "dem" / "ALL" / "2026-07-26_x")
    storage.create_chat_session(conn, "chat1", "dem", host_project_path, "web_x", created_at=1.0)

    async def fake_stream_chat(http_session, base_url, api_key, hermes_session_id, message, system_message=None):
        yield "done", {}

    monkeypatch.setattr(quickchat.hermes_client, "stream_chat", fake_stream_chat)

    with caplog.at_level("INFO", logger="hermes_web.quickchat"):
        async for _ in quickchat.send_message(
            conn, http_session=None, config=config, chat_session_id="chat1", text="привет",
            result_target="result/kirik",
        ):
            pass

    assert "chat_session_id=chat1" in caplog.text
    assert "result_target='result/kirik'" in caplog.text
    assert "reinforced=True" in caplog.text
```

- [ ] **Step 2: Написать падающий тест на логирование при отсутствии `result_target`**

Добавить туда же:

```python
@pytest.mark.asyncio
async def test_send_message_logs_missing_result_target_as_not_reinforced(tmp_path, monkeypatch, caplog):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    host_project_path = str(tmp_path / "workspace" / "dem" / "ALL" / "2026-07-26_y")
    storage.create_chat_session(conn, "chat2", "dem", host_project_path, "web_y", created_at=1.0)

    async def fake_stream_chat(http_session, base_url, api_key, hermes_session_id, message, system_message=None):
        yield "done", {}

    monkeypatch.setattr(quickchat.hermes_client, "stream_chat", fake_stream_chat)

    with caplog.at_level("INFO", logger="hermes_web.quickchat"):
        async for _ in quickchat.send_message(
            conn, http_session=None, config=config, chat_session_id="chat2", text="привет",
        ):
            pass

    assert "chat_session_id=chat2" in caplog.text
    assert "result_target=None" in caplog.text
    assert "reinforced=False" in caplog.text
```

- [ ] **Step 3: Прогнать тесты, убедиться что падают**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/pytest tests/test_quickchat.py -k logs_result_target -v`
Expected: FAIL — сейчас `send_message` ничего не логирует, `caplog.text` пуст.

- [ ] **Step 4: Реализовать логирование**

В `hermes_web/quickchat.py` добавить импорт и логгер сразу после существующих
импортов (после строки `from project_index import core as project_index_core`):

```python
import logging

logger = logging.getLogger(__name__)
```

В `send_message` — добавить вызов лога сразу после `await permissions.ensure_ownership(...)`,
перед `async for name, payload in hermes_client.stream_chat(...)`:

```python
    reinforced = bool(result_target and _is_valid_result_target(result_target))
    logger.info(
        "chat_session_id=%s result_target=%r reinforced=%s",
        chat_session_id, result_target, reinforced,
    )
```

- [ ] **Step 5: Прогнать тесты, убедиться что проходят**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/pytest tests/test_quickchat.py -v`
Expected: PASS, все тесты файла зелёные (включая два новых).

- [ ] **Step 6: Commit**

```bash
git add hermes-web/hermes_web/quickchat.py hermes-web/tests/test_quickchat.py
git commit -m "feat(hermes-web): логировать result_target и факт усиления системного сообщения на каждый ход (A1)"
```

---

### Task 2: Часть C (backend) — `save_file` больше не отклоняет пути вне source/outer/result

**Files:**
- Modify: `hermes-web/hermes_web/workspace.py`
- Test: `hermes-web/tests/test_workspace.py`

**Interfaces:**
- Consumes: существующий `save_file(user, project_path, relative_path, content, config)`,
  `_require_within_bucket(project_root, candidate)` (остаётся, но перестаёт
  вызываться из `save_file` — используется только в `make_dir`/`save_upload`,
  которые эта задача не трогает).
- Produces: ничего нового для других задач.

- [ ] **Step 1: Заменить устаревший тест на тест нового поведения**

В `tests/test_workspace.py` заменить существующий тест (сейчас проверяет
отказ — после этой задачи `misc`-путь должен сохраняться успешно):

```python
@pytest.mark.asyncio
async def test_save_file_allows_path_outside_bucket(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")

    result = await workspace.save_file("dem", "dem/ALL/a", "note.txt", "текст вне бакетов", config)
    assert (project_dir / "note.txt").read_text(encoding="utf-8") == "текст вне бакетов"
    assert result["reindexed"] is False
```

(заменяет прежний `test_save_file_rejects_path_outside_bucket`, который
проверял `pytest.raises(workspace.WorkspaceError)` для того же вызова —
поведение изменилось намеренно, это и есть Часть C).

- [ ] **Step 2: Добавить регрессионный тест на path traversal через save_file**

Добавить рядом:

```python
@pytest.mark.asyncio
async def test_save_file_rejects_traversal_outside_project(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        await workspace.save_file("dem", "dem/ALL/a", "../../etc/passwd.txt", "x", config)
```

- [ ] **Step 3: Прогнать тесты, убедиться в ожидаемом состоянии**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/pytest tests/test_workspace.py -k "save_file_allows_path_outside_bucket or save_file_rejects_traversal_outside_project" -v`
Expected: `test_save_file_allows_path_outside_bucket` FAILS (код ещё отклоняет
путь вне bucket'а через `_require_within_bucket`), `test_save_file_rejects_traversal_outside_project`
PASSES уже сейчас (защита `resolve_file_path` не зависит от этой задачи).

- [ ] **Step 4: Убрать вызов `_require_within_bucket` из `save_file`**

В `hermes_web/workspace.py`, в функции `save_file`, убрать строки:

```python
    if relative_path not in ROOT_EDITABLE_FILES:
        _require_within_bucket(project_root, candidate)
```

(остальное тело функции — проверка расширения, `resolve_file_path`,
`os.makedirs`/запись, реиндексация `about.md` — не меняется).

- [ ] **Step 5: Прогнать тесты, убедиться что проходят**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/pytest tests/test_workspace.py -v`
Expected: PASS, весь файл зелёный (включая старые тесты `make_dir`/`save_upload`,
которые всё ещё используют `_require_within_bucket` и не должны были
пострадать).

- [ ] **Step 6: Commit**

```bash
git add hermes-web/hermes_web/workspace.py hermes-web/tests/test_workspace.py
git commit -m "fix(hermes-web): save_file больше не отклоняет пути вне source/outer/result (Часть C)"
```

---

### Task 3: A2 (backend) — функция `move_entry`

**Files:**
- Modify: `hermes-web/hermes_web/workspace.py`
- Test: `hermes-web/tests/test_workspace.py`

**Interfaces:**
- Consumes: `resolve_file_path`, `permissions.ensure_ownership_sync`,
  `WorkspaceError`, `WorkspaceCollisionError`, `BUCKETS`, `ROOT_EDITABLE_FILES`
  (все уже существуют в этом же файле).
- Produces: `move_entry(user: str, project_path: str, source: str, dest_dir: str, new_name: str | None, config) -> dict`
  — возвращает `{"relative_path": <новый относительный путь>}`. Task 4
  (HTTP-эндпоинт) вызывает эту функцию напрямую с теми же именами параметров.

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_workspace.py`:

```python
def test_move_entry_moves_file_between_buckets(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    result = workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", "result", None, config)

    assert result["relative_path"] == "result/note.txt"
    assert (project_dir / "result" / "note.txt").read_text(encoding="utf-8") == "текст"
    assert not (project_dir / "source" / "note.txt").exists()


def test_move_entry_renames_file(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    result = workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", "source", "renamed.txt", config)

    assert result["relative_path"] == "source/renamed.txt"
    assert (project_dir / "source" / "renamed.txt").exists()
    assert not (project_dir / "source" / "note.txt").exists()


def test_move_entry_moves_folder_with_contents(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    nested = project_dir / "outer" / "topic"
    nested.mkdir(parents=True)
    (nested / "a.txt").write_text("a", encoding="utf-8")

    result = workspace.move_entry("dem", "dem/ALL/a", "outer/topic", "result", None, config)

    assert result["relative_path"] == "result/topic"
    assert (project_dir / "result" / "topic" / "a.txt").read_text(encoding="utf-8") == "a"
    assert not (project_dir / "outer" / "topic").exists()


def test_move_entry_allows_source_outside_buckets(tmp_path):
    """A2 обобщён: работает и для файлов из misc (вне source/outer/result), не только для них в result/."""
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "loose.html").write_text("<html></html>", encoding="utf-8")

    result = workspace.move_entry("dem", "dem/ALL/a", "loose.html", "result", None, config)

    assert result["relative_path"] == "result/loose.html"
    assert (project_dir / "result" / "loose.html").exists()
    assert not (project_dir / "loose.html").exists()


def test_move_entry_allows_dest_outside_buckets(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    result = workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", ".", None, config)

    assert result["relative_path"] == "note.txt"
    assert (project_dir / "note.txt").exists()


def test_move_entry_rejects_missing_source(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.move_entry("dem", "dem/ALL/a", "source/nope.txt", "result", None, config)


def test_move_entry_rejects_traversal_in_source(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.move_entry("dem", "dem/ALL/a", "../../etc/passwd", "result", None, config)


def test_move_entry_rejects_traversal_in_dest_dir(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")
    with pytest.raises(workspace.WorkspaceError):
        workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", "../../../etc", None, config)


def test_move_entry_collision_raises(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("1", encoding="utf-8")
    (project_dir / "result").mkdir()
    (project_dir / "result" / "note.txt").write_text("2", encoding="utf-8")

    with pytest.raises(workspace.WorkspaceCollisionError):
        workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", "result", None, config)


def test_move_entry_rejects_bucket_dir_itself(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    with pytest.raises(workspace.WorkspaceError):
        workspace.move_entry("dem", "dem/ALL/a", "source", "result", None, config)


def test_move_entry_rejects_about_md(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.move_entry("dem", "dem/ALL/a", "about.md", "result", None, config)


def test_move_entry_ensures_ownership_before_write(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    calls = []
    monkeypatch.setattr(workspace.permissions, "ensure_ownership_sync", lambda root: calls.append(root))

    workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", "result", None, config)

    assert calls == [str(project_dir)]
```

- [ ] **Step 2: Прогнать тесты, убедиться что падают**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/pytest tests/test_workspace.py -k move_entry -v`
Expected: FAIL с `AttributeError: module 'hermes_web.workspace' has no attribute 'move_entry'`.

- [ ] **Step 3: Реализовать `move_entry`**

Добавить в конец `hermes_web/workspace.py` (после `save_upload`):

```python
def move_entry(user: str, project_path: str, source: str, dest_dir: str, new_name: str | None, config) -> dict:
    project_root, source_candidate = resolve_file_path(user, project_path, source, config)
    permissions.ensure_ownership_sync(project_root)

    if not os.path.exists(source_candidate):
        raise WorkspaceError(f"'{source}' не найден")
    if source_candidate == project_root or source in ROOT_EDITABLE_FILES:
        raise WorkspaceError(f"'{source}' нельзя перемещать")
    for bucket in BUCKETS:
        if source_candidate == os.path.join(project_root, bucket):
            raise WorkspaceError(f"'{source}' нельзя перемещать — это сам bucket '{bucket}'")

    name = new_name if new_name else os.path.basename(source_candidate)
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise WorkspaceError(f"недопустимое имя: '{name}'")

    _, dest_dir_candidate = resolve_file_path(user, project_path, dest_dir, config)
    target = os.path.realpath(os.path.join(dest_dir_candidate, name))
    if target != dest_dir_candidate and not target.startswith(dest_dir_candidate + os.sep):
        raise WorkspaceError(f"недопустимое имя: '{name}'")
    if os.path.exists(target):
        raise WorkspaceCollisionError(f"'{name}' уже существует в целевой папке")

    os.makedirs(dest_dir_candidate, exist_ok=True)
    try:
        os.rename(source_candidate, target)
    except OSError as exc:
        raise WorkspaceError(f"не удалось переместить '{source}': {exc}") from exc

    return {"relative_path": os.path.relpath(target, project_root)}
```

(Файл уже начинается с `from __future__ import annotations` — аннотация
`new_name: str | None` работает без импорта `typing.Optional`.)

- [ ] **Step 4: Прогнать тесты, убедиться что проходят**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/pytest tests/test_workspace.py -v`
Expected: PASS, весь файл зелёный.

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/workspace.py hermes-web/tests/test_workspace.py
git commit -m "feat(hermes-web): move_entry — перенос/переименование файла или папки между любыми bucket'ами (A2, backend)"
```

---

### Task 4: A2 (HTTP) — эндпоинт `POST /api/projects/move-entry`

**Files:**
- Modify: `hermes-web/hermes_web/app.py`
- Test: `hermes-web/tests/test_app.py`

**Interfaces:**
- Consumes: `workspace.move_entry(user, project_path, source, dest_dir, new_name, config)` (Task 3).
- Produces: маршрут `POST /api/projects/move-entry`, тело запроса
  `{"path": <project_path>, "source": <rel_path>, "dest_dir": <rel_path>, "new_name": <str|null>}`,
  ответ `{"relative_path": <str>}` (200), `{"error": <str>}` (400/404/409).
  Task 6 (фронтенд) вызывает этот эндпоинт с теми же именами полей.

- [ ] **Step 1: Написать падающие тесты**

Найти в `tests/test_app.py` секцию `_seed_project`-based тестов (рядом с
`test_project_mkdir_*`) и добавить туда:

```python
@pytest.mark.asyncio
async def test_project_move_entry_moves_file(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/move-entry", json={
        "path": "dem/ALL/a", "source": "source/note.txt", "dest_dir": "result", "new_name": None,
    })
    assert resp.status == 200
    body = await resp.json()
    assert body["relative_path"] == "result/note.txt"
    assert (project_dir / "result" / "note.txt").exists()


@pytest.mark.asyncio
async def test_project_move_entry_renames(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/move-entry", json={
        "path": "dem/ALL/a", "source": "source/note.txt", "dest_dir": "source", "new_name": "renamed.txt",
    })
    assert resp.status == 200
    assert (project_dir / "source" / "renamed.txt").exists()


@pytest.mark.asyncio
async def test_project_move_entry_collision_returns_409(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("1", encoding="utf-8")
    (project_dir / "result").mkdir()
    (project_dir / "result" / "note.txt").write_text("2", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/move-entry", json={
        "path": "dem/ALL/a", "source": "source/note.txt", "dest_dir": "result", "new_name": None,
    })
    assert resp.status == 409


@pytest.mark.asyncio
async def test_project_move_entry_missing_source_returns_400(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/move-entry", json={
        "path": "dem/ALL/a", "source": "source/nope.txt", "dest_dir": "result", "new_name": None,
    })
    assert resp.status == 400


@pytest.mark.asyncio
async def test_project_move_entry_cross_user_returns_404(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})
    resp = await client.post("/api/projects/move-entry", json={
        "path": "dem/ALL/a", "source": "source/note.txt", "dest_dir": "result", "new_name": None,
    })
    assert resp.status == 404
    assert (project_dir / "source" / "note.txt").exists()


@pytest.mark.asyncio
async def test_project_move_entry_requires_auth(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.post("/api/projects/move-entry", json={
        "path": "dem/ALL/a", "source": "source/note.txt", "dest_dir": "result", "new_name": None,
    })
    assert resp.status == 401
```

- [ ] **Step 2: Прогнать тесты, убедиться что падают**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/pytest tests/test_app.py -k move_entry -v`
Expected: FAIL — маршрут ещё не зарегистрирован (404 на всё, включая тест
ожидающий 200/409/400).

- [ ] **Step 3: Добавить обработчик и маршрут**

В `hermes_web/app.py`, сразу после `handle_project_mkdir` (перед
`handle_project_upload`), добавить:

```python
async def handle_project_move_entry(request: web.Request) -> web.Response:
    user = _require_user(request)
    body = await request.json()
    path = str(body.get("path", ""))
    source = str(body.get("source", ""))
    dest_dir = str(body.get("dest_dir", ""))
    new_name = body.get("new_name")
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
```

И зарегистрировать маршрут рядом с остальными `/api/projects/*`, сразу
после `app.router.add_post("/api/projects/mkdir", handle_project_mkdir)`:

```python
    app.router.add_post("/api/projects/move-entry", handle_project_move_entry)
```

- [ ] **Step 4: Прогнать тесты, убедиться что проходят**

Run: `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins <venv>/bin/pytest tests/test_app.py -v`
Expected: PASS, весь файл зелёный.

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/app.py hermes-web/tests/test_app.py
git commit -m "feat(hermes-web): POST /api/projects/move-entry — HTTP-эндпоинт для move_entry (A2)"
```

---

### Task 5: Часть C (frontend) — клик по `.md`/`.txt` в misc открывает редактор

**Files:**
- Modify: `hermes-web/static/project-workspace.html`

**Interfaces:**
- Consumes: уже существующие `openEditor(relpath)`/`downloadFile(relpath)`.
- Produces: ничего нового для других задач.

- [ ] **Step 1: Убрать специальный случай для `misc` в обработчике клика**

В `renderTree()` найти (около строки 483-490):

```js
  document.querySelectorAll('.tree .node.file').forEach(n => {
    n.addEventListener('click', () => {
      const relpath = n.dataset.relpath;
      if (n.classList.contains('folder-misc')) { downloadFile(relpath); return; }
      if (/\.(md|txt)$/i.test(relpath)) openEditor(relpath);
      else downloadFile(relpath);
    });
  });
```

Заменить на:

```js
  document.querySelectorAll('.tree .node.file').forEach(n => {
    n.addEventListener('click', () => {
      const relpath = n.dataset.relpath;
      if (/\.(md|txt)$/i.test(relpath)) openEditor(relpath);
      else downloadFile(relpath);
    });
  });
```

- [ ] **Step 2: Ручная проверка (в этом репозитории нет JS-тестового фреймворка)**

Открыть рабочий экран проекта, в котором есть `.md`/`.txt` файл вне
`source/outer/result` (раздел «🗂 остальное») — убедиться, что клик открывает
редактор (`openEditor`), а не скачивание; сохранение через редактор должно
пройти успешно (это уже обеспечено Task 2). Клик по файлу с другим
расширением в том же разделе — по-прежнему скачивает.

- [ ] **Step 3: Commit**

```bash
git add hermes-web/static/project-workspace.html
git commit -m "fix(hermes-web): .md/.txt в разделе 'остальное' открываются в редакторе, как и везде (Часть C, frontend)"
```

---

### Task 6: Часть B + A2 (frontend) — сворачиваемое дерево + кнопка «переместить»

**Files:**
- Modify: `hermes-web/static/project-workspace.html`

**Interfaces:**
- Consumes: `POST /api/projects/move-entry` (Task 4), существующие
  `apiFetch`, `escapeHtml`, `currentTree`, `projectPath`, `refreshTreeAndFiles`,
  `renderTree`.
- Produces: ничего нового для других задач — терминальная фронтенд-задача
  этого среза.

Обе части (B и A2-UI) меняют одну и ту же функцию `renderFolderNode` —
делаются одним шагом, чтобы не оставлять функцию в противоречивом
промежуточном состоянии между двумя отдельными задачами.

- [ ] **Step 1: CSS для треугольника, счётчика и кнопки «переместить»**

Рядом с существующим блоком `.new-folder-btn` (около строки 36-37) добавить:

```css
  .node .tri{width:10px;text-align:center;flex-shrink:0;font-size:9px;color:var(--text-dim)}
  .node .fcount{font-size:10px;color:var(--text-dim)}
  .move-btn{background:none;border:1px solid var(--panel-line);color:var(--text-dim);border-radius:5px;font-size:10px;padding:1px 5px;cursor:pointer}
  .move-btn:hover{color:var(--text);border-color:var(--violet)}
```

- [ ] **Step 2: Состояние свёрнутости — глобальная переменная + localStorage**

Рядом с `let projectPath = null;` (строка 176) добавить:

```js
let expandedPaths = new Set();
```

Перед `function renderFolderNode(node, bucketClass, depth) {` добавить:

```js
function expandedStorageKey() {
  return `hermes-web:tree-expanded:${projectPath}`;
}

function loadExpandedPaths() {
  try {
    const raw = localStorage.getItem(expandedStorageKey());
    return new Set(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
}

function saveExpandedPaths() {
  localStorage.setItem(expandedStorageKey(), JSON.stringify([...expandedPaths]));
}

function countEntries(node) {
  let count = node.files.length;
  Object.values(node.folders).forEach(child => { count += 1 + countEntries(child); });
  return count;
}
```

В IIFE в конце файла, сразу после `projectPath = openBody.project_path;`
(строка 804), добавить:

```js
  expandedPaths = loadExpandedPaths();
```

- [ ] **Step 3: Переписать `renderFolderNode` — треугольник, счётчик, кнопка «переместить»**

**Важно (найдено финальным ревью 2026-07-29, Finding 2):** `child.path` в
`buildMiscTree` — синтетический ключ группировки (строка начинается с
`'misc/'`, которого не существует на диске — `misc` тут только подпись
раздела "остального" в этом файле). Он годится как opaque-ключ для
`data-toggle-path` (localStorage), но НЕ годится для `data-move` — это
значение уходит на сервер как `source`/резолвится как реальный путь, и
`misc/<папка>` там не существует, move всегда падает 400 "не найдено".
Поэтому заодно с этим шагом `buildMiscTree` должна класть на каждый папочный
узел ещё и `realPath` — реальный относительный путь без префикса `'misc/'`
(`parts.slice(0, i + 1).join('/')`), а `renderFolderNode` — использовать
`child.realPath ?? child.path` для `data-move` (для `buildFolderTree`,
дерева source/outer/result, `realPath` не выставляется, там `path` и так
реальный путь — `?? child.path` просто оставляет прежнее поведение).
`path` при этом не меняется, чтобы не терять уже сохранённые ключи
`expandedPaths` из localStorage.

Заменить всю функцию:

```js
function renderFolderNode(node, bucketClass, depth) {
  let html = '';
  const canCreate = bucketClass !== 'misc';
  Object.keys(node.folders).sort().forEach(name => {
    const child = node.folders[name];
    const expanded = expandedPaths.has(child.path);
    const hiddenCount = expanded ? 0 : countEntries(child);
    html += `<div class="node folder-${bucketClass}" style="padding-left:${depth * 14}px" data-toggle-path="${escapeHtml(child.path)}">
      <span class="tri">${expanded ? '▼' : '▶'}</span><span class="ic">📁</span><span class="name">${escapeHtml(name)}</span>${hiddenCount ? ` <span class="fcount">(${hiddenCount})</span>` : ''}
      <button class="move-btn" data-move="${escapeHtml(child.realPath ?? child.path)}" title="переместить">→</button>
      ${canCreate ? `<button class="new-folder-btn" data-parent="${escapeHtml(child.path)}" title="новая папка">＋</button>` : ''}
    </div>`;
    if (expanded) html += renderFolderNode(child, bucketClass, depth + 1);
  });
  node.files.sort((a, b) => a.name.localeCompare(b.name)).forEach(f => {
    html += `<div class="node file folder-${bucketClass}" style="padding-left:${depth * 14 + 20}px" data-relpath="${escapeHtml(f.entry.relative_path)}">
      <span class="ic">${iconFor(f.name)}</span><span class="name">${escapeHtml(f.name)}</span>
      <button class="move-btn" data-move="${escapeHtml(f.entry.relative_path)}" title="переместить">→</button>
    </div>`;
  });
  return html;
}
```

И в уже существующей (написанной до этого плана) функции `buildMiscTree`
добавить `realPath` на папочные узлы:

```js
function buildMiscTree(entries) {
  const root = { folders: {}, files: [], path: 'misc' };
  for (const entry of entries) {
    const parts = entry.relative_path.split('/');
    let node = root, accPath = 'misc';
    for (let i = 0; i < parts.length - 1; i++) {
      accPath += '/' + parts[i];
      const realPath = parts.slice(0, i + 1).join('/');
      if (!node.folders[parts[i]]) node.folders[parts[i]] = { folders: {}, files: [], path: accPath, realPath };
      node = node.folders[parts[i]];
    }
    node.files.push({ name: parts[parts.length - 1], entry });
  }
  return root;
}
```

- [ ] **Step 4: Функция `moveEntry` и регистрация обработчиков в `renderTree`**

Рядом с `openEditor`/`saveEditor` (после строки 576) добавить:

```js
function moveEntryDefaultDestDir(relpath) {
  const idx = relpath.lastIndexOf('/');
  return idx === -1 ? '.' : relpath.slice(0, idx);
}

async function moveEntry(relpath) {
  const currentName = relpath.split('/').pop();
  const destDir = prompt('Переместить в папку (например result или result/kirik):', moveEntryDefaultDestDir(relpath));
  if (destDir === null) return;
  const newName = prompt('Имя (можно оставить как есть):', currentName);
  if (!newName) return;
  const resp = await apiFetch('/api/projects/move-entry', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: projectPath, source: relpath, dest_dir: destDir, new_name: newName }),
  });
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    alert('Не удалось переместить: ' + (body.error || resp.status));
    return;
  }
  await refreshTreeAndFiles();
}
```

В `renderTree()`, сразу после существующего блока
`document.querySelectorAll('.tree .node.file').forEach(...)` (изменённого в
Task 5), добавить:

```js
  document.querySelectorAll('.tree [data-move]').forEach(btn => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); moveEntry(btn.dataset.move); });
  });
  document.querySelectorAll('.tree [data-toggle-path]').forEach(row => {
    row.addEventListener('click', () => {
      const path = row.dataset.togglePath;
      if (expandedPaths.has(path)) expandedPaths.delete(path); else expandedPaths.add(path);
      saveExpandedPaths();
      renderTree(currentTree);
    });
  });
```

(Порядок регистрации внутри `renderTree` не важен относительно уже
существующего блока `.new-folder-btn` — тот уже вызывает
`e.stopPropagation()` первой строкой своего обработчика, поэтому клик по
кнопке `＋` не долетает до тоггла свёрнутости родительской папки; то же
верно для новой кнопки `.move-btn` благодаря явному `e.stopPropagation()`
здесь.)

- [ ] **Step 5: Ручная проверка (в этом репозитории нет JS-тестового фреймворка)**

Открыть проект с вложенными папками в `source`/`outer`/`result`/`misc`:
1. При открытии — все папки свёрнуты (▶), у каждой свёрнутой папки виден
   счётчик скрытых записей.
2. Клик по строке папки (не по кнопкам) — разворачивает/сворачивает,
   треугольник меняется на ▼/▶.
3. Перезагрузка страницы — ранее развёрнутая папка остаётся развёрнутой,
   остальные по-прежнему свёрнуты.
4. Кнопка «→» на файле — запрашивает папку назначения и имя, после
   подтверждения файл реально переместился (виден в дереве в новом месте).
5. Кнопка «→» на папке — аналогично, вся папка со содержимым переехала,
   **включая папку в разделе «🗂 остальное» (misc), а не только в
   source/outer/result** — именно этот случай был пропущен изначально
   (см. финальное ревью 2026-07-29, Finding 2: misc-папки строятся с
   синтетическим display-путём `misc/...`, который не существует на диске,
   и без отдельного `realPath` move для них 400-ился всегда).
6. Попытка переместить в уже занятое имя — видно сообщение об ошибке (409),
   дерево не меняется.

- [ ] **Step 6: Commit**

```bash
git add hermes-web/static/project-workspace.html
git commit -m "feat(hermes-web): сворачиваемое дерево (свёрнуто по умолчанию, персистентно) + кнопка 'переместить' на любом узле (Часть B + A2 frontend)"
```

---

## Финальный шаг плана

После всех 6 задач: **superpowers:requesting-code-review** (финальное ревью
всей ветки на самой мощной модели) → **superpowers:finishing-a-development-branch**.
Живая приёмка на VPS (как и в предыдущих срезах) обязательна перед тем, как
считать точку остановки закрытой — особенно ручные фронтенд-проверки Task 5/6,
которые не покрыты автотестами.
