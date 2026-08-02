# Удаление файлов из проекта + уникальные имена вставленных скриншотов — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать пользователю удалять файлы/папки из рабочей области проекта и убрать ложные коллизии при вставке нескольких скриншотов из буфера обмена.

**Architecture:** Backend — новая функция `workspace.delete_entry()` (по образцу уже существующей `move_entry`) + HTTP-хендлер `POST /api/projects/delete-entry`. Frontend — кнопка «🗑» рядом с существующей «→» в дереве проекта, плюс переименование вставленных скриншотов на клиенте перед загрузкой (сервер не меняется).

**Tech Stack:** Python (aiohttp) + pytest на бэкенде, ванильный JS (без сборщика) во фронтенде — та же связка, что во всём `hermes-web`.

## Global Constraints

- Удаление — насовсем (`os.remove`/`shutil.rmtree`), без корзины и без возможности восстановить; подтверждение — только через `confirm()` в UI.
- Разрешено удалять: что угодно внутри `source`/`outer`/`result` (бакетов), и что угодно в «остальном» (misc — корень проекта вне бакетов), кроме скрытых (`.`-префикс) путей на любом уровне вложенности — то же правило, что уже применяет `_list_misc`.
- Запрещено удалять: сам корень проекта, `about.md`/`AGENTS.md`/`history.md` (`ROOT_EDITABLE_FILES`), сами папки-бакеты `source`/`outer`/`result` целиком.
- Если удаляемый элемент — символическая ссылка, удаляется сама ссылка, а не файл/папка, на которую она указывает.
- Обычная загрузка файлов (кнопка-скрепка) не меняется: коллизия имён по-прежнему явная ошибка, не молчаливый auto-suffix.
- Схема имени для вставленного скриншота: `screenshot_ЧЧ-ММ-СС[-N].<ext>` — суффикс `-N` (начиная с 1) только когда в одном `paste`-событии больше одного изображения; расширение из MIME-типа файла, фолбэк `png`.
- Спек: `docs/superpowers/specs/2026-08-02-workspace-delete-and-paste-naming-design.md`.

---

### Task 1: `workspace.delete_entry()` + юнит-тесты

**Files:**
- Modify: `hermes-web/hermes_web/workspace.py`
- Test: `hermes-web/tests/test_workspace.py`

**Interfaces:**
- Consumes: `resolve_file_path(user, project_path, relative_path, config) -> (project_root, candidate)`, `ROOT_EDITABLE_FILES`, `BUCKETS`, `WorkspaceError`, `permissions.ensure_ownership_sync(project_root)` — все уже определены в `workspace.py`.
- Produces: `delete_entry(user: str, project_path: str, relative_path: str, config) -> dict` с ключом `relative_path` (путь удалённого элемента относительно корня проекта, POSIX-стиль через `/`, как у `move_entry`). Task 2 вызывает эту функцию напрямую.

- [ ] **Step 1: Написать падающие тесты в `hermes-web/tests/test_workspace.py`**

Добавить в конец файла (после последнего теста `test_move_entry_rejects_dest_dir_that_is_a_file`):

```python
def test_delete_entry_removes_file_in_bucket(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    result = workspace.delete_entry("dem", "dem/ALL/a", "source/note.txt", config)

    assert result["relative_path"] == "source/note.txt"
    assert not (project_dir / "source" / "note.txt").exists()


def test_delete_entry_removes_folder_with_contents(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    nested = project_dir / "outer" / "topic"
    nested.mkdir(parents=True)
    (nested / "a.txt").write_text("a", encoding="utf-8")

    result = workspace.delete_entry("dem", "dem/ALL/a", "outer/topic", config)

    assert result["relative_path"] == "outer/topic"
    assert not (project_dir / "outer" / "topic").exists()


def test_delete_entry_removes_misc_file_outside_buckets(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "loose.html").write_text("<html></html>", encoding="utf-8")

    result = workspace.delete_entry("dem", "dem/ALL/a", "loose.html", config)

    assert result["relative_path"] == "loose.html"
    assert not (project_dir / "loose.html").exists()


def test_delete_entry_rejects_hidden_misc_path(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    hidden_dir = project_dir / ".git"
    hidden_dir.mkdir()
    (hidden_dir / "config").write_text("x", encoding="utf-8")

    with pytest.raises(workspace.WorkspaceError):
        workspace.delete_entry("dem", "dem/ALL/a", ".git/config", config)
    assert (hidden_dir / "config").exists()


def test_delete_entry_rejects_missing_entry(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.delete_entry("dem", "dem/ALL/a", "source/nope.txt", config)


def test_delete_entry_rejects_traversal(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.delete_entry("dem", "dem/ALL/a", "../../etc/passwd", config)


def test_delete_entry_rejects_bucket_dir_itself(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    with pytest.raises(workspace.WorkspaceError):
        workspace.delete_entry("dem", "dem/ALL/a", "source", config)
    assert (project_dir / "source").exists()


def test_delete_entry_rejects_about_md(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.delete_entry("dem", "dem/ALL/a", "about.md", config)
    assert (project_dir / "about.md").exists()


def test_delete_entry_rejects_project_root(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.delete_entry("dem", "dem/ALL/a", ".", config)
    assert project_dir.exists()


def test_delete_entry_ensures_ownership_before_write(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    calls = []
    monkeypatch.setattr(workspace.permissions, "ensure_ownership_sync", lambda root: calls.append(root))

    workspace.delete_entry("dem", "dem/ALL/a", "source/note.txt", config)

    assert calls == [str(project_dir)]


def test_delete_entry_removes_symlink_not_its_target(tmp_path):
    """Удаляемый элемент может оказаться симлинком (например, агент мог его
    создать внутри своей песочницы) — resolve_file_path отдаёт realpath
    ЦЕЛИ, а не самой ссылки. Наивная реализация удалила бы файл, на который
    ссылка указывает, вместо самой ссылки — потеря чужих данных."""
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "outer").mkdir()
    target = project_dir / "outer" / "real.txt"
    target.write_text("настоящий файл", encoding="utf-8")
    link = project_dir / "source" / "link.txt"
    os.symlink(target, link)

    result = workspace.delete_entry("dem", "dem/ALL/a", "source/link.txt", config)

    assert result["relative_path"] == "source/link.txt"
    assert not os.path.lexists(link)
    assert target.read_text(encoding="utf-8") == "настоящий файл"
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd hermes-web && python -m pytest tests/test_workspace.py -k delete_entry -v`
Expected: FAIL — `AttributeError: module 'hermes_web.workspace' has no attribute 'delete_entry'` (или похожее) на каждом тесте.

- [ ] **Step 3: Добавить `import shutil` в `hermes-web/hermes_web/workspace.py`**

Найти:

```python
import asyncio
import datetime
import functools
import os
import re
import sys
```

Заменить на:

```python
import asyncio
import datetime
import functools
import os
import re
import shutil
import sys
```

- [ ] **Step 4: Вынести проверку "внутри бакета" в переиспользуемый булев хелпер**

Найти:

```python
def _require_within_bucket(project_root: str, candidate: str) -> None:
    for bucket in BUCKETS:
        bucket_dir = os.path.join(project_root, bucket)
        if candidate == bucket_dir or candidate.startswith(bucket_dir + os.sep):
            return
    raise WorkspaceError("путь должен быть внутри source/outer/result")
```

Заменить на:

```python
def _within_bucket(project_root: str, candidate: str) -> bool:
    for bucket in BUCKETS:
        bucket_dir = os.path.join(project_root, bucket)
        if candidate == bucket_dir or candidate.startswith(bucket_dir + os.sep):
            return True
    return False


def _require_within_bucket(project_root: str, candidate: str) -> None:
    if not _within_bucket(project_root, candidate):
        raise WorkspaceError("путь должен быть внутри source/outer/result")
```

- [ ] **Step 5: Реализовать `delete_entry` в конце `hermes-web/hermes_web/workspace.py`**

Добавить после `move_entry` (в самом конце файла):

```python


def delete_entry(user: str, project_path: str, relative_path: str, config) -> dict:
    project_root, candidate = resolve_file_path(user, project_path, relative_path, config)
    literal_path = os.path.join(project_root, relative_path)

    if not os.path.lexists(literal_path):
        raise WorkspaceError(f"'{relative_path}' не найден")
    if candidate == project_root:
        raise WorkspaceError(f"'{relative_path}' нельзя удалить")
    for root_file in ROOT_EDITABLE_FILES:
        if candidate == os.path.join(project_root, root_file):
            raise WorkspaceError(f"'{relative_path}' нельзя удалить")
    for bucket in BUCKETS:
        if candidate == os.path.join(project_root, bucket):
            raise WorkspaceError(f"'{relative_path}' нельзя удалить — это сам bucket '{bucket}'")

    if not _within_bucket(project_root, candidate):
        rel_parts = os.path.relpath(candidate, project_root).split(os.sep)
        if any(part.startswith(".") for part in rel_parts):
            raise WorkspaceError(f"'{relative_path}' нельзя удалить")

    permissions.ensure_ownership_sync(project_root)

    if os.path.islink(literal_path):
        os.remove(literal_path)
        return {"relative_path": os.path.relpath(literal_path, project_root)}
    if os.path.isdir(candidate):
        shutil.rmtree(candidate)
    else:
        os.remove(candidate)
    return {"relative_path": os.path.relpath(candidate, project_root)}
```

- [ ] **Step 6: Запустить тесты и убедиться, что они проходят**

Run: `cd hermes-web && python -m pytest tests/test_workspace.py -v`
Expected: PASS — все тесты файла, включая новые `test_delete_entry_*` (весь файл, не только `-k delete_entry`, чтобы поймать регресс в `_within_bucket`/`_require_within_bucket` после Step 4).

- [ ] **Step 7: Commit**

```bash
git add hermes-web/hermes_web/workspace.py hermes-web/tests/test_workspace.py
git commit -m "feat(workspace): добавить delete_entry для удаления файлов/папок проекта"
```

---

### Task 2: HTTP-хендлер `POST /api/projects/delete-entry` + интеграционные тесты

**Files:**
- Modify: `hermes-web/hermes_web/app.py`
- Test: `hermes-web/tests/test_app.py`

**Interfaces:**
- Consumes: `workspace.delete_entry(user, project_path, relative_path, config) -> {"relative_path": str}` из Task 1; `_require_user(request)`, `workspace.WorkspaceError`, `projects.project_index_core.ProjectIndexError` — уже используются соседними хендлерами в `app.py`.
- Produces: маршрут `POST /api/projects/delete-entry`, тело `{"path": str, "relative_path": str}` → `200 {"relative_path": str}` / `400 {"error": str}` (WorkspaceError) / `404 {"error": str}` (ProjectIndexError, чужой/несуществующий проект) / `401` (не аутентифицирован). Task 3 (фронтенд) вызывает этот маршрут.

- [ ] **Step 1: Написать падающие тесты в `hermes-web/tests/test_app.py`**

Добавить после `test_project_move_entry_requires_auth` (перед `test_project_upload_saves_file_with_date_prefix`):

```python
@pytest.mark.asyncio
async def test_project_delete_entry_removes_file(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/delete-entry", json={
        "path": "dem/ALL/a", "relative_path": "source/note.txt",
    })
    assert resp.status == 200
    body = await resp.json()
    assert body["relative_path"] == "source/note.txt"
    assert not (project_dir / "source" / "note.txt").exists()


@pytest.mark.asyncio
async def test_project_delete_entry_removes_folder(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    nested = project_dir / "outer" / "topic"
    nested.mkdir(parents=True)
    (nested / "a.txt").write_text("a", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/delete-entry", json={
        "path": "dem/ALL/a", "relative_path": "outer/topic",
    })
    assert resp.status == 200
    assert not (project_dir / "outer" / "topic").exists()


@pytest.mark.asyncio
async def test_project_delete_entry_missing_returns_400(aiohttp_client, app_and_conn, tmp_path):
    _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/delete-entry", json={
        "path": "dem/ALL/a", "relative_path": "source/nope.txt",
    })
    assert resp.status == 400


@pytest.mark.asyncio
async def test_project_delete_entry_protected_file_returns_400(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/projects/delete-entry", json={
        "path": "dem/ALL/a", "relative_path": "about.md",
    })
    assert resp.status == 400
    assert (project_dir / "about.md").exists()


@pytest.mark.asyncio
async def test_project_delete_entry_cross_user_returns_404(aiohttp_client, app_and_conn, tmp_path):
    project_dir = _seed_project(tmp_path, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "rost", "password": "secret456"})
    resp = await client.post("/api/projects/delete-entry", json={
        "path": "dem/ALL/a", "relative_path": "source/note.txt",
    })
    assert resp.status == 404
    assert (project_dir / "source" / "note.txt").exists()


@pytest.mark.asyncio
async def test_project_delete_entry_requires_auth(aiohttp_client, app_and_conn):
    client = await aiohttp_client(app_and_conn)
    resp = await client.post("/api/projects/delete-entry", json={
        "path": "dem/ALL/a", "relative_path": "source/note.txt",
    })
    assert resp.status == 401
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `cd hermes-web && python -m pytest tests/test_app.py -k delete_entry -v`
Expected: FAIL — 404 "Not Found" на каждом запросе (маршрут ещё не зарегистрирован) вместо ожидаемых статусов.

- [ ] **Step 3: Добавить хендлер в `hermes-web/hermes_web/app.py`**

Найти:

```python
async def handle_project_upload(request: web.Request) -> web.Response:
```

Вставить перед этой строкой:

```python
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
```

- [ ] **Step 4: Зарегистрировать маршрут**

Найти:

```python
    app.router.add_post("/api/projects/move-entry", handle_project_move_entry)
    app.router.add_post("/api/projects/upload", handle_project_upload)
```

Заменить на:

```python
    app.router.add_post("/api/projects/move-entry", handle_project_move_entry)
    app.router.add_post("/api/projects/delete-entry", handle_project_delete_entry)
    app.router.add_post("/api/projects/upload", handle_project_upload)
```

- [ ] **Step 5: Запустить тесты и убедиться, что они проходят**

Run: `cd hermes-web && python -m pytest tests/test_app.py -v`
Expected: PASS — весь файл (не только `-k delete_entry`), чтобы поймать регресс в соседних маршрутах.

- [ ] **Step 6: Commit**

```bash
git add hermes-web/hermes_web/app.py hermes-web/tests/test_app.py
git commit -m "feat(app): маршрут POST /api/projects/delete-entry"
```

---

### Task 3: Кнопка удаления в дереве проекта

**Files:**
- Modify: `hermes-web/static/project-workspace.html`

**Interfaces:**
- Consumes: `POST /api/projects/delete-entry` из Task 2 (тело `{path, relative_path}` → `200 {relative_path}` / `400 {error}` / `401`); существующие в файле `apiFetch`, `escapeHtml`, `projectPath`, `refreshTreeAndFiles`, `currentEditorFile`, `editorDirty`, `closeEditorPane`, `renderFolderNode`, `renderTree`.
- Produces: функция `deleteEntry(relpath: string, isFolder: boolean)`, кнопка `.delete-btn[data-delete]` рядом с существующей `.move-btn[data-move]` для каждого файла/папки в `source`/`outer`/`result`/misc.

- [ ] **Step 1: Добавить CSS для кнопки удаления**

Найти:

```css
  .move-btn{background:none;border:1px solid var(--panel-line);color:var(--text-dim);border-radius:5px;font-size:10px;padding:1px 5px;cursor:pointer}
  .move-btn:hover{color:var(--text);border-color:var(--violet)}
```

Заменить на:

```css
  .move-btn{background:none;border:1px solid var(--panel-line);color:var(--text-dim);border-radius:5px;font-size:10px;padding:1px 5px;cursor:pointer}
  .move-btn:hover{color:var(--text);border-color:var(--violet)}
  .delete-btn{background:none;border:1px solid var(--panel-line);color:var(--text-dim);border-radius:5px;font-size:10px;padding:1px 5px;cursor:pointer}
  .delete-btn:hover{color:var(--red);border-color:var(--red)}
```

Найти:

```css
    --violet:#ad9fe6; --teal:#7fc4b2; --dim-star:#727bab;
```

Заменить на:

```css
    --violet:#ad9fe6; --teal:#7fc4b2; --dim-star:#727bab; --red:#e88980;
```

- [ ] **Step 2: Добавить кнопку удаления в `renderFolderNode`**

Найти:

```js
    html += `<div class="node folder-${bucketClass}" style="padding-left:${depth * 14}px" data-toggle-path="${escapeHtml(child.path)}">
      <span class="tri">${expanded ? '▼' : '▶'}</span><span class="ic">📁</span><span class="name">${escapeHtml(name)}</span>${hiddenCount ? ` <span class="fcount">(${hiddenCount})</span>` : ''}
      <button class="move-btn" data-move="${escapeHtml(child.realPath ?? child.path)}" title="переместить">→</button>
      ${canCreate ? `<button class="new-folder-btn" data-parent="${escapeHtml(child.path)}" title="новая папка">＋</button>` : ''}
    </div>`;
```

Заменить на:

```js
    html += `<div class="node folder-${bucketClass}" style="padding-left:${depth * 14}px" data-toggle-path="${escapeHtml(child.path)}">
      <span class="tri">${expanded ? '▼' : '▶'}</span><span class="ic">📁</span><span class="name">${escapeHtml(name)}</span>${hiddenCount ? ` <span class="fcount">(${hiddenCount})</span>` : ''}
      <button class="move-btn" data-move="${escapeHtml(child.realPath ?? child.path)}" title="переместить">→</button>
      <button class="delete-btn" data-delete="${escapeHtml(child.realPath ?? child.path)}" data-delete-kind="folder" title="удалить">🗑</button>
      ${canCreate ? `<button class="new-folder-btn" data-parent="${escapeHtml(child.path)}" title="новая папка">＋</button>` : ''}
    </div>`;
```

Найти:

```js
    html += `<div class="node file folder-${bucketClass}" style="padding-left:${depth * 14 + 20}px" data-relpath="${escapeHtml(f.entry.relative_path)}">
      <span class="ic">${iconFor(f.name)}</span><span class="name">${escapeHtml(f.name)}</span>
      <button class="move-btn" data-move="${escapeHtml(f.entry.relative_path)}" title="переместить">→</button>
    </div>`;
```

Заменить на:

```js
    html += `<div class="node file folder-${bucketClass}" style="padding-left:${depth * 14 + 20}px" data-relpath="${escapeHtml(f.entry.relative_path)}">
      <span class="ic">${iconFor(f.name)}</span><span class="name">${escapeHtml(f.name)}</span>
      <button class="move-btn" data-move="${escapeHtml(f.entry.relative_path)}" title="переместить">→</button>
      <button class="delete-btn" data-delete="${escapeHtml(f.entry.relative_path)}" data-delete-kind="file" title="удалить">🗑</button>
    </div>`;
```

- [ ] **Step 3: Добавить функцию `deleteEntry` и подключить обработчик кликов**

Найти:

```js
async function moveEntry(relpath) {
```

Вставить перед этой строкой:

```js
async function deleteEntry(relpath, isFolder) {
  const name = relpath.split('/').pop();
  const msg = isFolder
    ? `Удалить папку «${name}» со всем содержимым безвозвратно?`
    : `Удалить файл «${name}» безвозвратно?`;
  if (!confirm(msg)) return;
  const resp = await apiFetch('/api/projects/delete-entry', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: projectPath, relative_path: relpath }),
  });
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    alert('Не удалось удалить: ' + (body.error || resp.status));
    return;
  }
  if (currentEditorFile === relpath) {
    closeEditorPane();
    currentEditorFile = null;
    editorDirty = false;
  }
  await refreshTreeAndFiles();
}

async function moveEntry(relpath) {
```

Найти:

```js
  document.querySelectorAll('.tree [data-move]').forEach(btn => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); moveEntry(btn.dataset.move); });
  });
```

Заменить на:

```js
  document.querySelectorAll('.tree [data-move]').forEach(btn => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); moveEntry(btn.dataset.move); });
  });
  document.querySelectorAll('.tree [data-delete]').forEach(btn => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); deleteEntry(btn.dataset.delete, btn.dataset.deleteKind === 'folder'); });
  });
```

- [ ] **Step 4: Проверить синтаксис извлечённого `<script>` через node**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('hermes-web/static/project-workspace.html', 'utf8');
const match = html.match(/<script>([\s\S]*?)<\/script>/);
fs.writeFileSync('/tmp/project-workspace-inline.js', match[1]);
"
node --check /tmp/project-workspace-inline.js
```

Expected: без вывода (успех, код выхода 0).

- [ ] **Step 5: Проверить, что все ссылки на новые идентификаторы согласованы**

```bash
grep -n "delete-btn\|deleteEntry\|data-delete" hermes-web/static/project-workspace.html
```

Expected: видны все точки правки — 2 CSS-правила (`.delete-btn`/`.delete-btn:hover`), обе точки рендера кнопки в дереве (папка + файл), объявление `async function deleteEntry(...)` и подключение обработчика через `document.querySelectorAll('.tree [data-delete]')`.

- [ ] **Step 6: Commit**

```bash
git add hermes-web/static/project-workspace.html
git commit -m "feat(workspace-ui): кнопка удаления файлов/папок в дереве проекта"
```

---

### Task 4: Уникальные имена вставленных скриншотов

**Files:**
- Modify: `hermes-web/static/project-workspace.html`

**Interfaces:**
- Consumes: существующий `uploadPending(files, targetDir)` (не меняется — принимает массив `File`).
- Produces: функции `screenshotExtension(mimeType)` и `renameScreenshot(file, index, total)`, применяются в обработчике `paste` перед вызовом `uploadPending`.

- [ ] **Step 1: Заменить обработчик `paste`**

Найти:

```js
document.getElementById('composeInput').addEventListener('paste', async (e) => {
  const items = e.clipboardData ? e.clipboardData.items : [];
  const files = [];
  for (const it of items) if (it.type.startsWith('image/')) files.push(it.getAsFile());
  if (files.length) await uploadPending(files, document.getElementById('uploadTargetSelect').value || 'source');
});
```

Заменить на:

```js
function screenshotExtension(mimeType) {
  const map = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif' };
  return map[mimeType] || 'png';
}

function renameScreenshot(file, index, total) {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const time = `${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`;
  const suffix = total > 1 ? `-${index + 1}` : '';
  const name = `screenshot_${time}${suffix}.${screenshotExtension(file.type)}`;
  return new File([file], name, { type: file.type });
}

document.getElementById('composeInput').addEventListener('paste', async (e) => {
  const items = e.clipboardData ? e.clipboardData.items : [];
  const files = [];
  for (const it of items) if (it.type.startsWith('image/')) files.push(it.getAsFile());
  const renamed = files.map((file, index) => renameScreenshot(file, index, files.length));
  if (renamed.length) await uploadPending(renamed, document.getElementById('uploadTargetSelect').value || 'source');
});
```

- [ ] **Step 2: Проверить синтаксис извлечённого `<script>` через node**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('hermes-web/static/project-workspace.html', 'utf8');
const match = html.match(/<script>([\s\S]*?)<\/script>/);
fs.writeFileSync('/tmp/project-workspace-inline.js', match[1]);
"
node --check /tmp/project-workspace-inline.js
```

Expected: без вывода (успех, код выхода 0).

- [ ] **Step 3: Проверить логику руками через node (без браузера)**

Эта проверка держит собственную копию функций (не вычитывает их из HTML), чтобы не зависеть от точного форматирования исходника — сверяется с логикой, добавленной в Step 1:

```bash
node -e "
function screenshotExtension(mimeType) {
  const map = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif' };
  return map[mimeType] || 'png';
}
function renameScreenshot(file, index, total) {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const time = pad(now.getHours()) + '-' + pad(now.getMinutes()) + '-' + pad(now.getSeconds());
  const suffix = total > 1 ? ('-' + (index + 1)) : '';
  const name = 'screenshot_' + time + suffix + '.' + screenshotExtension(file.type);
  return { name };
}
console.log(renameScreenshot({ type: 'image/png' }, 0, 1).name);
console.log(renameScreenshot({ type: 'image/png' }, 0, 2).name);
console.log(renameScreenshot({ type: 'image/jpeg' }, 1, 2).name);
"
```

Expected: три строки вида `screenshot_ЧЧ-ММ-СС.png`, `screenshot_ЧЧ-ММ-СС-1.png`, `screenshot_ЧЧ-ММ-СС-2.jpg` (текущее время, без суффикса при `total=1`, с суффиксом `-1`/`-2` при `total=2`). Затем визуально сверить `renameScreenshot`/`screenshotExtension` в `hermes-web/static/project-workspace.html` (добавленные в Step 1) с этой копией — логика должна совпадать дословно.

- [ ] **Step 4: Commit**

```bash
git add hermes-web/static/project-workspace.html
git commit -m "fix(workspace-ui): уникальные имена вставленных скриншотов (дата+время+номер)"
```

---

## Self-Review (для исполнителя, после завершения всех задач)

Перед финальным ревью всей ветки свериться со спеком
(`docs/superpowers/specs/2026-08-02-workspace-delete-and-paste-naming-design.md`):

- Feature 1 полностью покрыта Task 1-3 (бэкенд, API, UI).
- Feature 2 полностью покрыта Task 4.
- Symlink guard (Feature 1, отдельный пункт спека) реализован и покрыт тестом `test_delete_entry_removes_symlink_not_its_target`.
- Обычная загрузка файлов (кнопка-скрепка) не тронута — `_add_date_prefix`/`save_upload` не менялись.
