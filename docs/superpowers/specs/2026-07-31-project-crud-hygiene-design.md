# Спек: CRUD-гигиена проектов — удаление, создание из списка, теги (Группа A бэклога живого тестирования)

**Дата:** 2026-07-31 · **Статус:** согласовано с пользователем (открытые
вопросы A1/A3 решены), ждёт спек-ревью

## Контекст

Продолжение бэклога живого тестирования
([2026-07-31-workspace-ux-backlog-from-live-testing.md](./2026-07-31-workspace-ux-backlog-from-live-testing.md)).
Группа B (создание папок бакетов) закрыта (B1 задеплоен и подтверждён
вживую). Следующий шаг по согласованному порядку B → A → C → D — Группа
A: три независимые, но родственные операции над проектами, которых
сегодня физически нет в коде (не спрятаны в UI — отсутствуют):

- **A1. Удаление проекта.** В `hermes-plugins/project_index/core.py` нет
  функции `delete_project`; в `hermes_web/app.py` нет эндпоинта. Два
  тестовых «мусорных» проекта пользователя в `ALL` реально нечем убрать.
- **A2. Создание проекта из `project-selector.html`.** Единственный
  сегодняшний путь завести проект — «Быстрый чат» (`create_quick_chat`),
  всегда в группу `ALL`, сразу поднимает Hermes-сессию. Отдельного «просто
  создать пустой проект в выбранной группе» пути нет.
- **A3. Редактирование тегов.** `tags`/`status` — YAML-фронтматтер
  `about.md` (`project_index_core.parse_about_md`), правится только как
  сырой текст файла — нет структурированного UI-поля.

**Согласованные решения по открытым вопросам** (пользователь, 2026-07-31):
- A1 — **мягкое удаление**: перенос в скрытую `.trash/` папку пользователя,
  а не безвозвратный `rmtree`. Восстановление — вручную по SSH при
  необходимости, отдельного UI/API для восстановления в этом срезе нет.
- A3 — **с автокомплитом** по уже известным пользователю тегам при
  добавлении нового.

Все три задачи используют один и тот же слой защиты пути, что уже
проверен в `move_project` (path traversal был реальной уязвимостью,
закрытой ревью 2026-07-26) — `resolve_project_path` (первый слой:
принадлежит пользователю) + требование `about.md` (второй слой: это
вообще проект, не голая группа/пользовательский корень).

## A1: Удаление проекта (мягкое, в `.trash/`)

### `hermes-plugins/project_index/core.py`

Новая функция, по образцу уже существующего `move_project` (тот же
двухслойный путь-контроль, та же валидация ДО любых изменений на диске):

```python
TRASH_DIR_NAME = ".trash"


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
    trash_path = os.path.join(trash_dir, f"{stamp}_{leaf}")

    shutil.move(old_path, trash_path)

    conn = storage.get_connection(db_path)
    try:
        storage.delete_project(conn, old_path)
    finally:
        conn.close()

    return {"old_path": old_path, "trashed_path": trash_path}
```

Требует `import uuid` в начале файла (сегодня не импортирован —
`shutil`/`datetime` уже есть). `storage.delete_project(conn, path)` уже
существует (`hermes-plugins/project_index/storage.py:100-102`, просто
никем не вызывается сегодня — сам DELETE FROM projects уже написан и
покрыт не был только оркестрирующей функцией) — просто удаляет строку
индекса, никакой доработки не требует.

Штамп `{дата}_{uuid8}_` перед именем гарантирует отсутствие коллизий
внутри `.trash/` при повторном удалении проектов с одинаковым именем —
без этого второе удаление проекта с тем же `leaf` затёрло бы первое.
Это тот же приём, что уже используется для слага `create_quick_chat`
(`f"{today}_chat-{uuid.uuid4().hex[:8]}"`), просто с сохранением
исходного имени в хвосте вместо генерации нового.

**Почему не переиспользовать `move_project` с фиктивной "группой" `.trash`
вместо отдельной функции:** `move_project` содержит
`leaving_all`/`entering_all`-логику добавления/снятия date-префикса —
абсолютно не к месту при перемещении в мусорную корзину (испортила бы
уникальность/читаемость имени), а обходить эту логику костылём —
сложнее и более хрупко, чем 15 строк отдельной функции.

### `hermes_web/projects.py`

Обёртка, зеркалящая уже существующую `move_project` дословно (тот же
повод — `shutil.move` + запись в БД вне event loop, тот же вызов
`storage.update_chat_session_project_path` — переиспользуем без
изменений, если у удаляемого проекта была chat-сессия, её `project_path`
переезжает вместе с папкой в `.trash/`, а не остаётся висеть на
несуществующем пути):

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

### `hermes_web/app.py`

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

Роут (тот же POST-с-телом стиль, что и `/move`/`/move-entry`, не нативный
HTTP DELETE — в этом кодовой базе уже устоявшийся паттерн):

```python
app.router.add_post("/api/projects/delete", handle_delete_project)
```

### `hermes_web/projects.py: list_groups` — исключить `.trash` из списка групп

`list_groups` (`projects.py:103-124`) сканирует `os.listdir(user_root)`
на все директории — без исключения `.trash` появился бы как обычная
(пустая по проектам, т.к. `storage.delete_project` убирает индекс)
видимая "группа" в сайдбаре. Точечная правка:

```python
disk_slugs = {
    name for name in os.listdir(user_root)
    if os.path.isdir(os.path.join(user_root, name)) and not name.startswith(".")
}
```

Общее правило «скрытые директории не группы» (не точечное исключение
только `.trash`) — на случай будущих служебных папок с точкой.

### Фронтенд (`static/project-selector.html`)

В `renderPanel` (`:434-457`), рядом с уже существующими
`openProjectBtn`/`movePanelBtn` — новая кнопка:

```html
<button class="btn-secondary btn-danger" id="deletePanelBtn">Удалить проект</button>
```

```js
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
  await loadProjects();
});
```

`confirm()` — тот же уровень модальности, что уже принят в проекте для
других необратимых действий (браузерный confirm, не кастомный оверлей —
см. прецедент `move_entry`/`save_upload` коллизий, где решение уже было
«чистая ошибка, не тихий молчаливый обход»; здесь по аналогии — явное
подтверждение, не тихое действие).

## A2: Создание проекта из списка, в выбранную группу

### `hermes_web/quickchat.py`

Новая функция рядом с `create_quick_chat` — делает то же самое на уровне
файловой системы и project_index, но **без** подъёма Hermes-сессии
(она создаётся лениво при первом открытии через уже существующий
`get_or_open_session` — тот же принцип «без сетевого вызова — без риска
осиротевшего проекта при сбое Hermes», уже проверенный ревью
2026-07-26 для похожего сценария):

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

    project_rel_path = os.path.join(user, group, leaf)
    project_abs_path = os.path.join(_workspace_root(config), user, group, leaf)

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

Требует `from . import projects` в начале `quickchat.py` (переиспользует
уже публичную `projects.slugify` — та же транслитерация, что уже
используется для слагов групп — не заводим второй slugify). Проверено:
`projects.py` не импортирует `quickchat` ни прямо, ни транзитивно —
циклического импорта нет.

Имя папки для группы `ALL` — дата-префиксный технический слаг (как у
«Быстрого чата»); для любой другой группы — человекочитаемый слаг из
названия (как у проектов, покинувших `ALL` через `move_project` —
`_strip_date_prefix`/`_add_date_prefix` уже кодируют именно это правило,
здесь то же самое, только «с рождения», без промежуточного переноса).
Коллизия имени — чистая ошибка (400), без тихого автосуффикса — та же
политика, что уже принята в `move_project`/`save_upload` (D-010, D-014).

`_backfill_project_scaffold` (переименован в B1) уже пишет
`AGENTS.md`/`history.md` + папки `source/outer/result` — переиспользуется
без изменений.

### `hermes_web/app.py`

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

Роут — `POST /api/projects`, тот же путь, что и уже существующий
`GET /api/projects` (`handle_list_projects`) — разные методы на одном
пути, стандартный REST-паттерн, уже есть прецедент в этом же файле
(`/api/projects/file` — и GET, и POST):

```python
app.router.add_post("/api/projects", handle_create_project)
```

### Фронтенд (`static/project-selector.html`)

Кнопка «+ Новый проект» в `.mainhead` (`:276-281`), рядом с уже
существующей `editGroupBtn`, видимая при том же условии (не «искать
везде», не в режиме RAG-поиска — `renderMain`, `:514`):

```html
<button class="btn-primary" id="addProjectBtn">+ новый проект</button>
```

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

И в `renderMain` рядом со строкой `editGroupBtn.style.display = ...`:

```js
document.getElementById('addProjectBtn').style.display = (everywhere || searching) ? 'none' : 'inline-block';
```

`prompt()` — простое однополевое имя, не полноценный модальный редактор
(как у создания группы, где ещё нужен выбор эмодзи) — минимальная UI-
поверхность для одного текстового поля, YAGNI. `state.group` как целевая
группа — «группа, выделенная курсором» из находки пользователя = уже
существующее состояние выбранной/отфильтрованной группы в сайдбаре, не
новое отслеживание hover. После создания — сразу редирект в рабочий
экран нового проекта (тот же паттерн, что уже у «Быстрого чата» и
«Открыть проект →»), не просто обновление списка.

## A3: Редактирование тегов и статуса

### `hermes-plugins/project_index/core.py`

Узкий, позиционный патч YAML-фронтматтера — **не** пересборка всего
`about.md` на фронтенде или сервере из отдельных полей (риск сломать
существующие секции при неполном round-trip). Тот же принцип, что уже
применён в `_rewrite_title` (патчит только секцию заголовка, остальное
не трогает) — здесь то же самое, но для YAML-блока:

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

`index_update` переиспускается целиком (не только для DB-строки, но и
для пересчёта эмбеддинга — `_embed_text` включает теги в текст для
эмбеддинга, значит смена тегов обязана переиндексировать RAG-поиск,
иначе поиск по смыслу разойдётся с реально отображаемыми тегами).
`get_project_detail` в конце — тот же формат ответа
(`title/description/points/now/tags/status/path/group`), что уже
отдаёт `GET /api/projects/detail`, поэтому фронтенду не нужен отдельный
парсер под новый эндпоинт — тот же `renderPanel(p, detail)` работает
без изменений.

### `hermes_web/projects.py`

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

### `hermes_web/app.py`

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

```python
app.router.add_post("/api/projects/metadata", handle_update_project_metadata)
```

### Фронтенд (`static/project-selector.html`)

Заменяем статичный блок тегов в `renderPanel` (`:447`) на редактируемый:
чипы с крестиком удаления, инпут с `<datalist>` для автокомплита (список
уникальных тегов из уже загруженного в память `projects` — тот же
источник, что уже питает `tagCloud`, никакого нового эндпоинта не
нужно), кнопка сохранения статуса (переключатель active/archived на
клик по `p-status`).

```html
<div class="p-block">
  <div class="lbl">Tags</div>
  <div class="p-tags-edit" id="tagsEdit"></div>
  <div class="tag-add-row">
    <input id="newTagInput" list="tagSuggestions" placeholder="добавить тег…">
    <datalist id="tagSuggestions"></datalist>
    <button id="addTagBtn">+</button>
  </div>
</div>
```

```js
let editingTags = [...p.tags];

function renderTagsEdit(){
  const wrap = document.getElementById('tagsEdit');
  wrap.innerHTML = editingTags.map(t =>
    `<span>#${escapeHtml(t)} <button class="tag-remove" data-tag="${escapeHtml(t)}">×</button></span>`
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

document.getElementById('addTagBtn').addEventListener('click', () => {
  const input = document.getElementById('newTagInput');
  const val = input.value.trim();
  if (!val || editingTags.includes(val)) return;
  editingTags.push(val);
  input.value = '';
  renderTagsEdit();
  saveTags();
});

async function saveTags(){
  const resp = await apiFetch('/api/projects/metadata', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: p.path, tags: editingTags }),
  });
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) { alert('Не удалось сохранить теги'); return; }
  const updated = await resp.json();
  p.tags = updated.tags;
  const idx = projects.findIndex(x => x.path === p.path);
  if (idx !== -1) projects[idx].tags = updated.tags;
}
```

Каждое добавление/удаление тега сохраняется сразу (не откладывается до
отдельной кнопки «Сохранить») — той же немодальной, немедленной
логике, что уже работает для перетаскивания файлов (`move_entry`) и
переноса проектов между группами. `p.tags`/`projects[idx].tags`
обновляются в памяти после сохранения — следующий `renderTagSuggestions()`
(при следующем открытии панели) увидит новый тег в автокомплите без
перезагрузки страницы.

Статус (`active`/`archived`) — по клику на `.p-status`-бейдж переключает
и сразу вызывает тот же `/api/projects/metadata` с `status` вместо
`tags`, симметрично.

## Деплой

**Отличие от B1: меняются файлы в ДВУХ разных пакетах, разворачиваются
в разные места.** `hermes-plugins/project_index/core.py` — Hermes-плагин,
на сервере живёт в `~/.hermes/plugins/project_index/` (используется и
`hermes-web` через `PROJECT_INDEX_PLUGIN_DIR`, и самим Hermes-агентом
как штатный плагин, см. D-001/D-025 setup) — после `rsync` этого файла
нужен рестарт **обоих** сервисов: `hermes-web.service` (подхватить новую
логику для API) и `hermes-gateway.service` (подхватить новую логику для
инструмента агента `project_move`/будущих вызовов, если Hermes
когда-либо читает этот же модуль напрямую — на практике агент не
вызывает `delete_project`/`update_project_metadata` через tool-calling
в этом срезе, но плагин переиспользуется как единый файл, рассинхрон
версий на сервере между сервисами — источник будущих багов, поэтому
рестартуем оба сразу, не откладываем).

`hermes_web/{app,projects,quickchat}.py`, `static/project-selector.html`
— обычный `rsync` + `systemctl --user restart hermes-web.service`.

**Живая проверка — по диску сервера (`ls -la`), не только по UI** (тот же
урок, что и в B1 — финальное ревью B1 показало, что UI может рисовать
состояние независимо от реального успеха бэкенд-операции; здесь
дополнительно необходимо: удаление — файл реально переехал в
`.trash/`, а не просто исчез из списка/API-ответа; создание — папка с
полным скаффолдом (`about.md`/`AGENTS.md`/`history.md`/`source/outer/result`)
реально появилась в указанной группе; теги — `about.md` на диске
содержит новый список тегов, а остальные секции (описание/опорные
точки/на чём остановились) не пострадали побайтово).
