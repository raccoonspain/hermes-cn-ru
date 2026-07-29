# Видимость пустых папок result/ + явный выбор целевой папки для результата — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Пустые папки внутри `source/outer/result` (созданные через `＋папка`
в UI) видны в дереве файлов сразу и переживают перезагрузку страницы;
пользователь может явно выбрать целевую подпапку `result/` для текущего
хода чата, и модель получает усиленную, конкретную инструкцию класть
результат именно туда (с оговоркой — спросить пользователя, если считает
это место неподходящим).

**Architecture:** `list_tree` (`hermes_web/workspace.py`) начинает отдавать
директории каждого bucket'а отдельным полем `{bucket}_dirs` (включая
пустые) — это устраняет саму причину невидимости, а не симптом. Новый
селектор в композере чата (`static/project-workspace.html`) выбирает
подпапку `result/`, запоминает выбор в `localStorage` по проекту и
передаёт его в `POST /api/chat/{id}/send` → `quickchat.send_message` →
`_system_message_for`, которая на каждый ход добавляет абзац с конкретным
абсолютным путём.

**Tech Stack:** Python (aiohttp, без ORM/фреймворка — как и весь
`hermes_web`), pytest + pytest-asyncio, vanilla JS во фронтенде без
сборщика.

## Global Constraints

- Технически заблокировать запись модели в файловую систему нельзя —
  агент Hermes пишет напрямую в свою Docker-песочницу, `hermes_web` не
  встроен в этот путь. Любое усиление — только текст в системном
  сообщении на конкретный ход, не enforcement.
- `result_target`, приходящий с фронтенда, валидируется на бэкенде перед
  тем, как попасть в текст системного сообщения (без файлового доступа —
  чисто строковая проверка): должен быть `"result"` либо начинаться с
  `"result/"`, без сегментов `"."`/`".."`/пустых. Невалидное значение —
  тихо игнорируется, ничего не падает.
- Существующее поведение без `result_target` (старые клиенты, отсутствие
  поля в теле запроса) должно остаться байт-в-байт таким же, как сейчас —
  никаких новых обязательных полей в HTTP API.
- Фронтенд — vanilla JS, без сборщика и без JS-тестов в репозитории;
  проверка UI-изменений — вручную в браузере (dev-сервер +
  golden path + edge cases), как и для прошлых срезов.
- Костыль `manuallyCreatedFolders` (`project-workspace.html`) полностью
  убирается — он существовал только чтобы прятать реальный баг бэкенда;
  после Task 1 он не нужен и держать его рядом с настоящим источником
  данных значило бы держать два расходящихся источника правды.

---

### Task 1: `list_tree` отдаёт директории каждого bucket'а (включая пустые)

**Files:**
- Modify: `hermes-web/hermes_web/workspace.py:162-188` (`list_tree`)
- Test: `hermes-web/tests/test_workspace.py`

**Interfaces:**
- Produces: `list_tree(...)` теперь возвращает словарь с дополнительными
  ключами `f"{bucket}_dirs"` для каждого `bucket` в `BUCKETS` — отсортированный
  список relative-путей директорий (например `["result/kirik",
  "result/kirik/3-23-29"]`), включая директории без единого файла внутри.
  Существующие ключи (`tree[bucket]` — список файлов, `root_files`, `misc`,
  `misc_truncated`) не меняются.

- [ ] **Step 1: Написать падающий тест на пустую подпапку**

В `hermes-web/tests/test_workspace.py` добавить (после
`test_list_tree_lists_nested_folders`, использует уже существующие в файле
`_config`/`_write_project`):

```python
def test_list_tree_includes_empty_subfolder_created_via_make_dir(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    workspace.make_dir("dem", "dem/ALL/a", "result", "kirik", config)

    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert tree["result"] == []
    assert tree["result_dirs"] == ["result/kirik"]
    assert tree["source_dirs"] == []
    assert tree["outer_dirs"] == []


def test_list_tree_dirs_includes_intermediate_folder_without_own_files(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    nested = project_dir / "result" / "kirik" / "3-23-29"
    nested.mkdir(parents=True)
    (nested / "solution.md").write_text("x", encoding="utf-8")

    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert tree["result_dirs"] == ["result/kirik", "result/kirik/3-23-29"]
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `cd hermes-web && python -m pytest tests/test_workspace.py -k "list_tree_includes_empty_subfolder or list_tree_dirs_includes_intermediate" -v`
Expected: FAIL с `KeyError: 'result_dirs'`

- [ ] **Step 3: Реализовать сбор директорий в `list_tree`**

Заменить тело цикла по `BUCKETS` в `list_tree`
(`hermes-web/hermes_web/workspace.py`):

```python
    tree = {"root_files": root_files}
    for bucket in BUCKETS:
        bucket_dir = os.path.join(project_root, bucket)
        entries = []
        dirs = []
        if os.path.isdir(bucket_dir):
            for dirpath, _dirnames, filenames in os.walk(bucket_dir):
                if dirpath != bucket_dir:
                    dirs.append(os.path.relpath(dirpath, project_root))
                for filename in filenames:
                    full = os.path.join(dirpath, filename)
                    entries.append({
                        "relative_path": os.path.relpath(full, project_root),
                        "size": os.path.getsize(full),
                        "mtime": _iso_mtime(full),
                    })
        tree[bucket] = sorted(entries, key=lambda e: e["relative_path"])
        tree[f"{bucket}_dirs"] = sorted(dirs)
    misc_entries, misc_truncated = _list_misc(project_root)
    tree["misc"] = misc_entries
    tree["misc_truncated"] = misc_truncated
    return tree
```

(Изменения: добавлена локальная `dirs = []`, добавлена ветка
`if dirpath != bucket_dir: dirs.append(...)` внутри существующего
`os.walk`-цикла, добавлена строка `tree[f"{bucket}_dirs"] = sorted(dirs)`
после существующей `tree[bucket] = sorted(entries, ...)`. Остальное тело
функции не меняется.)

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `cd hermes-web && python -m pytest tests/test_workspace.py -v`
Expected: PASS, все тесты файла (старые + 2 новых)

- [ ] **Step 5: Commit**

```bash
cd hermes-web
git add hermes_web/workspace.py tests/test_workspace.py
git commit -m "feat(hermes-web): list_tree отдаёт директории bucket'ов, включая пустые"
```

---

### Task 2: Валидация `result_target` и усиленное системное сообщение

**Files:**
- Modify: `hermes-web/hermes_web/quickchat.py` (`_system_message_for`, `send_message`)
- Test: `hermes-web/tests/test_quickchat.py`

**Interfaces:**
- Consumes: ничего нового от Task 1 (независимая часть бэкенда).
- Produces:
  - `_is_valid_result_target(result_target: str) -> bool` — чистая
    строковая проверка, без файлового доступа.
  - `_system_message_for(project_path: str, result_target: str | None = None) -> str`
    — новый необязательный параметр, по умолчанию `None` (старое
    поведение не меняется).
  - `send_message(db_conn, http_session, config, chat_session_id, text, result_target: Optional[str] = None)`
    — новый необязательный именованный параметр в конце сигнатуры,
    существующие позиционные вызовы не ломаются.

- [ ] **Step 1: Написать падающие тесты**

В `hermes-web/tests/test_quickchat.py` добавить (после
`test_system_message_points_deliverables_to_result_bucket`, использует уже
существующие в файле `_config`, `quickchat.storage`, `pytest.mark.asyncio`):

```python
def test_is_valid_result_target_accepts_root_and_nested():
    assert quickchat._is_valid_result_target("result") is True
    assert quickchat._is_valid_result_target("result/kirik") is True
    assert quickchat._is_valid_result_target("result/kirik/3-23-29") is True


def test_is_valid_result_target_rejects_traversal_and_other_buckets():
    assert quickchat._is_valid_result_target("result/..") is False
    assert quickchat._is_valid_result_target("../etc") is False
    assert quickchat._is_valid_result_target("source/x") is False
    assert quickchat._is_valid_result_target("resultx") is False
    assert quickchat._is_valid_result_target("result/") is False
    assert quickchat._is_valid_result_target("") is False


def test_system_message_adds_result_target_instruction_when_valid():
    msg = quickchat._system_message_for("/workspace/dem/ALL/x", result_target="result/kirik")
    assert "/workspace/dem/ALL/x/result/kirik" in msg
    assert "спроси пользователя" in msg


def test_system_message_ignores_invalid_result_target():
    msg = quickchat._system_message_for("/workspace/dem/ALL/x", result_target="../etc")
    assert "спроси пользователя" not in msg
    assert "../etc" not in msg


def test_system_message_without_result_target_unchanged():
    msg = quickchat._system_message_for("/workspace/dem/ALL/x")
    assert "спроси пользователя" not in msg


@pytest.mark.asyncio
async def test_send_message_forwards_result_target_to_system_message(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    host_project_path = str(tmp_path / "workspace" / "dem" / "ALL" / "2026-07-26_x")
    storage.create_chat_session(conn, "chat1", "dem", host_project_path, "web_x", created_at=1.0)

    captured = {}

    async def fake_stream_chat(http_session, base_url, api_key, hermes_session_id, message, system_message=None):
        captured["system_message"] = system_message
        yield "done", {}

    monkeypatch.setattr(quickchat.hermes_client, "stream_chat", fake_stream_chat)

    async for _ in quickchat.send_message(
        conn, http_session=None, config=config, chat_session_id="chat1", text="привет", result_target="result/kirik",
    ):
        pass

    assert "/workspace/dem/ALL/2026-07-26_x/result/kirik" in captured["system_message"]
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `cd hermes-web && python -m pytest tests/test_quickchat.py -k "result_target" -v`
Expected: FAIL с `AttributeError: module 'hermes_web.quickchat' has no attribute '_is_valid_result_target'`
(и/или `TypeError: _system_message_for() got an unexpected keyword argument`)

- [ ] **Step 3: Реализовать валидацию и усиленный абзац**

Добавить в `hermes-web/hermes_web/quickchat.py` перед
`_system_message_for` (после `_new_hermes_session`):

```python
def _is_valid_result_target(result_target: str) -> bool:
    if result_target == "result":
        return True
    if not result_target.startswith("result/"):
        return False
    segments = result_target[len("result/"):].split("/")
    return all(segment and segment not in (".", "..") for segment in segments)
```

Заменить сигнатуру и тело `_system_message_for`:

```python
def _system_message_for(project_path: str, result_target: str | None = None) -> str:
    message = (
        f"Текущий проект: {project_path}. "
        "Готовые файлы (решения, отчёты, сгенерированные документы) клади в "
        "подпапку result/ внутри этого проекта — оттуда их видно и можно "
        "скачать в веб-интерфейсе; произвольные папки в корне проекта там не "
        "отображаются. Исходники — в source/, вспомогательные материалы "
        "(скачанное, промежуточное) — в outer/; внутри каждой из трёх можно "
        "заводить подпапки. "
        "Инструментам write_file/read_file передавай АБСОЛЮТНЫЙ путь, "
        f"начинающийся строго с {project_path} (например "
        f"{project_path}/result/solution.md). Путь без этого префикса "
        "резолвится не от корня текущего проекта, а от другого каталога "
        "сессии, и почти всегда попадает мимо проекта или получает отказ в "
        "записи. После записи файла — проверь ответ инструмента: если он "
        "сообщил об ошибке или отказе, файл не сохранён, не пиши "
        "пользователю, что всё готово."
    )
    if result_target and _is_valid_result_target(result_target):
        message += (
            " Пользователь указал целевую папку для результата этого хода: "
            f"{project_path}/{result_target}. Клади готовые файлы именно туда. "
            "Если считаешь, что это не подходящее место для результата этого "
            "хода — спроси пользователя перед сохранением, а не сохраняй молча "
            "в другое место."
        )
    return message
```

Изменить сигнатуру и вызов `_system_message_for` в `send_message`:

```python
async def send_message(
    db_conn, http_session, config: Config, chat_session_id: str, text: str, result_target: Optional[str] = None,
) -> AsyncIterator[tuple[str, dict]]:
    row = storage.get_chat_session(db_conn, chat_session_id)
    if row is None:
        raise QuickChatError(f"неизвестная сессия чата: {chat_session_id}")

    await permissions.ensure_ownership(row["project_path"])

    async for name, payload in hermes_client.stream_chat(
        http_session,
        config.hermes_base_url,
        config.hermes_api_key,
        row["hermes_session_id"],
        text,
        system_message=_system_message_for(_sandbox_project_path(config, row["project_path"]), result_target),
    ):
        yield name, payload

    storage.touch_chat_session(db_conn, chat_session_id, last_message_at=time.time())
```

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `cd hermes-web && python -m pytest tests/test_quickchat.py -v`
Expected: PASS, все тесты файла (старые + 6 новых)

- [ ] **Step 5: Commit**

```bash
cd hermes-web
git add hermes_web/quickchat.py tests/test_quickchat.py
git commit -m "feat(hermes-web): result_target усиливает системное сообщение конкретным путём"
```

---

### Task 3: `handle_send_message` принимает `result_target` из тела запроса

**Files:**
- Modify: `hermes-web/hermes_web/app.py` (`handle_send_message`)
- Test: `hermes-web/tests/test_app.py`

**Interfaces:**
- Consumes: `quickchat.send_message(..., result_target: Optional[str] = None)` из Task 2.
- Produces: `POST /api/chat/{chat_session_id}/send` принимает необязательное
  поле `result_target` в JSON-теле, наравне с уже существующим `text`.

- [ ] **Step 1: Написать падающий тест**

В `hermes-web/tests/test_app.py` добавить (после
`test_send_message_streams_sse_events`, использует уже существующие в
файле `aiohttp_client`, `app_and_conn`):

```python
@pytest.mark.asyncio
async def test_send_message_forwards_result_target(aiohttp_client, app_and_conn, monkeypatch):
    captured = {}

    async def fake_send_message(db_conn, http_session, config, chat_session_id, text, result_target=None):
        captured["result_target"] = result_target
        yield "done", {}

    monkeypatch.setattr("hermes_web.app.quickchat.send_message", fake_send_message)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/chat/chat1/send", json={"text": "привет", "result_target": "result/kirik"})
    assert resp.status == 200
    await resp.read()
    assert captured["result_target"] == "result/kirik"


@pytest.mark.asyncio
async def test_send_message_omits_result_target_when_absent(aiohttp_client, app_and_conn, monkeypatch):
    # Существующие клиенты (и большинство текущих тестов этого файла) не
    # шлют result_target вовсе — fake_send_message без этого параметра
    # должен продолжать работать без TypeError по неожиданному kwarg.
    async def fake_send_message(db_conn, http_session, config, chat_session_id, text):
        yield "done", {}

    monkeypatch.setattr("hermes_web.app.quickchat.send_message", fake_send_message)

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    resp = await client.post("/api/chat/chat1/send", json={"text": "привет"})
    assert resp.status == 200
```

- [ ] **Step 2: Запустить тесты, убедиться что падают**

Run: `cd hermes-web && python -m pytest tests/test_app.py -k "result_target" -v`
Expected: FAIL — первый тест: `captured["result_target"]` никогда не
устанавливается (`KeyError`), т.к. `handle_send_message` пока не читает и
не передаёт `result_target`.

- [ ] **Step 3: Реализовать проброс в `handle_send_message`**

В `hermes-web/hermes_web/app.py`, в `handle_send_message`, после строки
`if not text: return web.json_response(...)` добавить:

```python
    result_target = body.get("result_target")
```

И заменить вызов `quickchat.send_message(...)`:

```python
        send_kwargs = {"result_target": result_target} if result_target is not None else {}
        agen = quickchat.send_message(
            request.app["db"], request.app["http_session"], request.app["quickchat_config"], chat_session_id, text,
            **send_kwargs,
        ).__aiter__()
```

(Условный `send_kwargs` — намеренно: если `result_target` не пришёл,
`quickchat.send_message` вызывается ровно так же, как раньше, без нового
kwarg вообще — существующие тесты с `fake_send_message` без параметра
`result_target` продолжают работать без изменений.)

- [ ] **Step 4: Запустить тесты, убедиться что проходят**

Run: `cd hermes-web && python -m pytest tests/test_app.py -v`
Expected: PASS, все тесты файла (старые + 2 новых)

- [ ] **Step 5: Commit**

```bash
cd hermes-web
git add hermes_web/app.py tests/test_app.py
git commit -m "feat(hermes-web): /api/chat/{id}/send принимает result_target"
```

---

### Task 4: Фронтенд — селектор «папка для результата» и уборка костыля

**Files:**
- Modify: `hermes-web/static/project-workspace.html`

**Interfaces:**
- Consumes: `tree[f"{bucket}_dirs"]` из Task 1 (сервер), `result_target` из
  Task 2+3 (отправка сообщения).
- Produces: ничего для других задач — конечная точка цепочки.

Нет автоматических тестов для фронтенда в этом репозитории (vanilla JS,
без сборщика) — проверка вручную в браузере, шаги ниже.

- [ ] **Step 1: Убрать `manuallyCreatedFolders` и связанный комментарий**

В `hermes-web/static/project-workspace.html` удалить (около строки 183-188):

```js
// list_tree на бэкенде отдаёт только записи файлов из os.walk — папка без
// единого файла в ней вообще не попадает в ответ. Чтобы только что созданная
// пустая папка сразу была видна в дереве и доступна для выбора при загрузке,
// держим её путь здесь в рамках сессии страницы (переживёт до первого файла
// внутри неё либо до перезагрузки страницы — это ожидаемое ограничение).
let manuallyCreatedFolders = new Set();
```

- [ ] **Step 2: `buildFolderTree` принимает список директорий из ответа сервера**

Заменить функцию `buildFolderTree(entries, bucket)`:

```js
function buildFolderTree(entries, dirs, bucket) {
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
  // list_tree отдаёт {bucket}_dirs отдельным полем (включая пустые папки) —
  // подмешиваем их сюда, чтобы папка без единого файла тоже была видна.
  (dirs || []).forEach(fullPath => {
    const parts = fullPath.split('/').slice(1);
    let node = root, accPath = bucket;
    for (const part of parts) {
      accPath += '/' + part;
      if (!node.folders[part]) node.folders[part] = { folders: {}, files: [], path: accPath };
      node = node.folders[part];
    }
  });
  return root;
}
```

Обновить вызов в `renderTree`:

```js
  ['source', 'outer', 'result'].forEach(bucket => {
    html += `<div class="glabel">${labels[bucket]}<button class="new-folder-btn" data-parent="${bucket}" title="новая папка">＋папка</button></div>`;
    html += renderFolderNode(buildFolderTree(tree[bucket] || [], tree[bucket + '_dirs'] || [], bucket), bucket, 0);
  });
```

- [ ] **Step 3: Убрать запись в `manuallyCreatedFolders` из обработчика `new-folder-btn`**

В обработчике клика `.new-folder-btn` (внутри `renderTree`) удалить строку:

```js
      if (body.relative_path) manuallyCreatedFolders.add(body.relative_path);
```

Оставить последующий `await refreshTreeAndFiles();` как есть — после
Task 1 сервер сам вернёт новую папку в `{bucket}_dirs`.

- [ ] **Step 4: `renderFolderOptions` использует `{bucket}_dirs` вместо ручной сборки**

Заменить функцию `renderFolderOptions(tree)`:

```js
function renderFolderOptions(tree) {
  const select = document.getElementById('uploadTargetSelect');
  const options = [];
  ['source', 'outer', 'result'].forEach(bucket => {
    options.push(bucket);
    (tree[bucket + '_dirs'] || []).forEach(d => options.push(d));
  });
  const previous = select.value;
  select.innerHTML = options.map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('');
  if (options.includes(previous)) select.value = previous;
}
```

- [ ] **Step 5: Добавить строку «папка для результата» в HTML**

В `hermes-web/static/project-workspace.html`, сразу после существующего
блока (около строки 137-140):

```html
    <div class="upload-target-row">
      <span>папка для вложений:</span>
      <select id="uploadTargetSelect"></select>
    </div>
```

добавить:

```html
    <div class="upload-target-row">
      <span>папка для результата:</span>
      <select id="resultTargetSelect"></select>
    </div>
```

- [ ] **Step 6: Функция заполнения и восстановления выбора из `localStorage`**

Добавить рядом с `renderFolderOptions` (после неё):

```js
function resultTargetStorageKey() {
  return `hermes-web:result-target:${projectPath}`;
}

function renderResultTargetOptions(tree) {
  const select = document.getElementById('resultTargetSelect');
  const options = ['result', ...(tree.result_dirs || [])];
  const stored = localStorage.getItem(resultTargetStorageKey());
  const previous = select.value || stored || 'result';
  select.innerHTML = options.map(o => `<option value="${escapeHtml(o)}">${escapeHtml(o)}</option>`).join('');
  select.value = options.includes(previous) ? previous : 'result';
}
```

Вызвать её в `loadTreeAndRender()` сразу после существующего
`renderFolderOptions(currentTree);`:

```js
  renderFolderOptions(currentTree);
  renderResultTargetOptions(currentTree);
```

- [ ] **Step 7: Сохранять выбор пользователя в `localStorage` при изменении**

Добавить рядом с остальными `addEventListener` в конце файла (после
`document.getElementById('composeInput').addEventListener('paste', ...)`):

```js
document.getElementById('resultTargetSelect').addEventListener('change', () => {
  localStorage.setItem(resultTargetStorageKey(), document.getElementById('resultTargetSelect').value);
});
```

- [ ] **Step 8: Передавать `result_target` при отправке сообщения**

В `sendMessage()` заменить тело запроса:

```js
    const resp = await apiFetch(`/api/chat/${encodeURIComponent(chatSessionId)}/send`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: fullText }),
    });
```

на:

```js
    const resp = await apiFetch(`/api/chat/${encodeURIComponent(chatSessionId)}/send`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: fullText,
        result_target: document.getElementById('resultTargetSelect').value || 'result',
      }),
    });
```

- [ ] **Step 9: Запустить бэкенд-тесты (страховка, что фронтенд-правки не задели их)**

Run: `cd hermes-web && python -m pytest -v`
Expected: PASS, все тесты (163 + новые из Task 1-3)

- [ ] **Step 10: Ручная проверка в браузере**

Запустить дев-сервер (`cd hermes-web && python run.py` или как обычно
запускается локально), открыть `project-workspace.html` для существующего
проекта:
1. Создать через `＋папка` под `result` новую подпапку — убедиться, что
   она сразу видна в дереве.
2. Перезагрузить страницу — папка на месте (это и есть проверка фикса
   Task 1 живьём).
3. Убедиться, что новая папка появилась в выпадающем списке «папка для
   результата».
4. Выбрать эту подпапку в «папка для результата», отправить любое
   сообщение — открыть вкладку/лог сервера или временно
   залогировать `system_message` внутри `hermes_client.stream_chat` и
   убедиться, что в нём есть абсолютный путь именно к выбранной подпапке.
5. Перезагрузить страницу ещё раз — выбор в «папка для результата»
   должен остаться (проверка `localStorage`-персистентности).

- [ ] **Step 11: Commit**

```bash
cd hermes-web
git add static/project-workspace.html
git commit -m "feat(hermes-web): селектор «папка для результата», убран костыль manuallyCreatedFolders"
```

---

### Task 5: Деплой на VPS, живая проверка, документация

**Files:**
- No new files — деплой существующих изменённых файлов.
- Modify: `docs/state.md`, `docs/changelog.md`, `docs/decisions.md`
  (обновляются вручную по итогам Task 1-4, без заранее заданного текста —
  см. существующий формат этих файлов и `D-012` как образец).

- [ ] **Step 1: Прогнать полный тестовый набор перед деплоем**

Run: `cd hermes-web && python -m pytest -v`
Expected: PASS, все тесты, включая новые из Task 1-3.

- [ ] **Step 2: Задеплоить изменённые файлы на VPS**

```bash
rsync -avz -e "ssh -i ~/.ssh/id_ed25519_hermes_user" \
  hermes-web/hermes_web/workspace.py hermes-web/hermes_web/quickchat.py hermes-web/hermes_web/app.py \
  hermes@212.115.55.116:~/hermes-web/hermes_web/
rsync -avz -e "ssh -i ~/.ssh/id_ed25519_hermes_user" \
  hermes-web/static/project-workspace.html \
  hermes@212.115.55.116:~/hermes-web/static/
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 \
  "systemctl --user restart hermes-web.service && systemctl --user status hermes-web.service --no-pager"
```

Expected: `active (running)`, без трейсбеков в `journalctl --user -u hermes-web.service -n 50`.

- [ ] **Step 3: Живая проверка на реальном проекте**

Повторить шаги ручной проверки из Task 4/Step 10, но на реальном проекте
пользователя (например тот же «Кирик»), через публичный домен
`hermes.blackboxbegin.space` — создать подпапку в `result/`, перезагрузить
страницу, убедиться что видна и выбирается, отправить сообщение с выбранной
подпапкой, убедиться что модель в этом ходе кладёт файл именно туда (или
явно спрашивает, если считает место неподходящим).

- [ ] **Step 4: Обновить документацию проекта**

По итогам живой проверки:
- `docs/decisions.md` — добавить `D-013` по шаблону
  Контекст/Варианты/Решение/Почему/Последствия (как `D-012`): контекст —
  две находки живого прогона 2026-07-29 (невидимая пустая папка,
  модель мимо result/); решение — серверный список директорий +
  явный селектор с усиленной промпт-инструкцией; почему — техническое
  ограничение (нельзя перехватить запись модели) обсуждено и принято
  пользователем.
- `docs/changelog.md` — новая запись с датой живой проверки: что было
  сломано, что исправлено, число тестов до/после, факт деплоя и живой
  приёмки.
- `docs/state.md` — обновить дату «Последнее обновление» и добавить
  абзац в верхнюю сводку + подсекцию в «Сейчас в работе» по аналогии с
  существующей секцией про D-012, с реальными числами тестов и деталями
  проверки.

- [ ] **Step 5: Snapshot**

```bash
bash scripts/snapshot.sh "селектор папки результата + видимость пустых папок (D-013)"
```

---

## Self-Review

**1. Spec coverage:** Проблема 1 (пустые папки невидимы) → Task 1 (бэкенд)
+ Task 4/Step 1-4 (фронтенд использует новые данные, костыль убран).
Проблема 2 (модель мимо result/) → Task 2 (валидация + усиленный текст) +
Task 3 (проброс через HTTP) + Task 4/Step 5-8 (UI-селектор +
localStorage). Ограничение "не можем технически заблокировать" отражено
в Global Constraints и в самом тексте инструкции модели (просьба спросить
пользователя, а не гарантия). Деплой и документация — Task 5.

**2. Placeholder scan:** Весь код в шагах — реальные диффы к существующим
файлам, без "TBD"/"добавить обработку ошибок" — валидация уже описана
явно (`_is_valid_result_target`), обратная совместимость API описана явно
(условный `send_kwargs`).

**3. Type consistency:** `_is_valid_result_target` (Task 2) используется
и в `_system_message_for` (та же задача) — имя и сигнатура совпадают.
`result_target` как имя параметра/поля JSON — одинаково в
`quickchat.send_message`, `handle_send_message`, теле запроса фронтенда и
localStorage-ключе. `tree[f"{bucket}_dirs"]` (Task 1, Python) ↔
`tree[bucket + '_dirs']` (Task 4, JS) — одна и та же схема имени поля с
обеих сторон.
