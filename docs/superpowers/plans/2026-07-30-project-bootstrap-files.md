# Пакет стартовых файлов проекта (about.md/AGENTS.md/history.md) + подхват AGENTS.md — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Каждый новый проект `hermes-web` рождается сразу с полным пакетом
стартовых файлов (`about.md` + `AGENTS.md` + `history.md`), старые проекты
дополучают недостающие файлы лениво при следующем открытии, а
`AGENTS.md` реально подмешивается в системное сообщение модели на каждый
ход — закрывает находку из
`docs/superpowers/specs/2026-07-30-project-bootstrap-files-design.md`
(AGENTS.md лежал на диске, но не влиял на поведение модели).

**Architecture:** Всё изменение — внутри `hermes_web/quickchat.py`, без
новых модулей и HTTP-эндпоинтов. Два новых шаблона-константы
(`AGENTS_MD_TEMPLATE`, `HISTORY_MD_TEMPLATE`) рядом с уже существующим
`ABOUT_MD_PLACEHOLDER`; один новый хелпер `_backfill_root_files`,
вызываемый и из `create_quick_chat` (создание проекта), и из
`get_or_open_session` (открытие существующего) — одна и та же логика для
обоих случаев, не две копии. Отдельный чистый хелпер `_agents_md_block`
читает `AGENTS.md` **напрямую через `open()`**, без похода в
`hermes_web/workspace.py` — тот модуль устроен под HTTP-запросы с
пользовательским `relative_path` и делает лишнюю для этого случая работу
(проверку `about.md`, path-traversal защиту для пути, который здесь
всегда буквально `"AGENTS.md"`); здесь читаем доверенный `project_path`
из БД тем же способом, каким `create_quick_chat` уже пишет `about.md` —
плоским `open()`. `_system_message_for` получает третий необязательный
параметр `agents_md_block: str = ""` и просто дописывает его в конец —
все существующие юнит-тесты, вызывающие `_system_message_for` напрямую
(без нового параметра), продолжают проходить без изменений.

**Tech Stack:** Python 3.12, стандартная библиотека (`os`, `logging`),
pytest + pytest-asyncio (тесты, уже используются в проекте).

## Global Constraints

- Универсальная часть текста (`source/outer/result`, правило «проверяй
  ответ инструмента перед тем как сказать что всё готово», конвенция про
  `history.md`) переезжает в `AGENTS_MD_TEMPLATE` **как статический
  текст**. Путь проекта (`{project_path}`) и правило про обязательный
  абсолютный путь для `write_file`/`read_file` **остаются динамическими**
  в коде `_system_message_for` — не переносить их в шаблон, иначе они
  протухнут при `project_move` (шаблон не должен содержать буквальных
  путей).
- `_agents_md_block` **не** использует `hermes_web/workspace.py` — прямой
  `open()`, см. Architecture выше. Не импортировать `workspace` в
  `quickchat.py` в рамках этой фичи.
- Лимит текста `AGENTS.md`, подмешиваемого в системное сообщение:
  `AGENTS_MD_MAX_CHARS = 4000` символов. При превышении — обрезать и
  дописать пометку `[...обрезано, полный текст в AGENTS.md]`. Это лимит
  на **инъекцию в промпt**, не на сам файл — файл на диске не трогаем и
  не ограничиваем.
- Отсутствие `AGENTS.md` — не ошибка, тихо возвращаем пустую строку
  (старые проекты до бэкфилла, либо гонка между чтением и бэкфиллом).
  Любая другая ошибка чтения (`OSError`, кроме `FileNotFoundError`) —
  `logger.warning`, тоже возвращаем `""`, ход чата не должен падать
  из-за этой второстепенной фичи.
- **Не реализуем** принудительную ротацию `history.md` — это мягкая
  конвенция в тексте `AGENTS_MD_TEMPLATE`, которую соблюдает модель, не
  код backend'а (см. спеку, раздел «Что не делаем»).
- **Не бэкфиллим `about.md`** — он и так гарантированно существует у
  любого проекта, который вообще можно открыть (`resolve_file_path`
  требует его наличия).
- **Не трогаем `hermes_web/app.py`, HTTP-слой, фронтенд** — вся фича
  внутри `quickchat.py`, `AGENTS.md`/`history.md` уже редактируются через
  существующий UI (`ROOT_EDITABLE_FILES` в `workspace.py` их уже
  перечисляет).
- Тесты гонять из `hermes-web/`:
  `PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins python3 -m pytest tests/ -q`
  — все зависимости (`aiohttp`, `argon2-cffi`, `pytest`, `pytest-asyncio`)
  уже установлены в системный `python3` на этой машине, отдельный venv не
  нужен. **Базовая линия перед этим срезом: 201 тест проходит.**

---

### Task 1: Шаблоны `AGENTS.md`/`history.md` + создание пакета в `create_quick_chat`

**Files:**
- Modify: `hermes-web/hermes_web/quickchat.py:64` (после `ABOUT_MD_PLACEHOLDER`, до `_project_index_kwargs`)
- Modify: `hermes-web/hermes_web/quickchat.py:116-153` (`create_quick_chat`)
- Test: `hermes-web/tests/test_quickchat.py`

**Interfaces:**
- Produces: `AGENTS_MD_TEMPLATE: str`, `HISTORY_MD_TEMPLATE: str`,
  `_backfill_root_files(project_root: str) -> None` — создаёт
  `AGENTS.md`/`history.md` из шаблонов, только если файла ещё нет; ничего
  не возвращает. Используется в Task 1 (создание) и Task 2 (бэкфилл).

- [ ] **Step 1: Написать падающий тест на создание пакета файлов**

Добавить в конец `test_create_quick_chat_runs_index_update_without_blocking_event_loop`
(после неё, перед `test_send_message_forwards_project_path_as_system_message`):

```python
@pytest.mark.asyncio
async def test_create_quick_chat_creates_agents_and_history_md(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    result = await quickchat.create_quick_chat(conn, http_session=None, config=config, user="dem")

    agents_path = os.path.join(result["project_path"], "AGENTS.md")
    history_path = os.path.join(result["project_path"], "history.md")
    assert os.path.isfile(agents_path)
    assert os.path.isfile(history_path)

    agents_text = open(agents_path, encoding="utf-8").read()
    assert "result/" in agents_text
    assert "history.md" in agents_text

    history_text = open(history_path, encoding="utf-8").read()
    assert "append-only" in history_text
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd hermes-web && PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins python3 -m pytest tests/test_quickchat.py -k test_create_quick_chat_creates_agents_and_history_md -v`
Expected: FAIL — `AGENTS.md`/`history.md` не существуют (`create_quick_chat` их пока не создаёт).

- [ ] **Step 3: Добавить шаблоны и хелпер, вызвать из `create_quick_chat`**

Сразу после блока `ABOUT_MD_PLACEHOLDER` (`quickchat.py:50-64`) добавить:

```python
AGENTS_MD_TEMPLATE = """# Конвенции проекта

Готовые файлы (решения, отчёты, сгенерированные документы) клади в
подпапку result/ внутри этого проекта — оттуда их видно и можно скачать
в веб-интерфейсе; произвольные файлы в корне проекта там не отображаются.
Исходники — в source/, вспомогательные материалы (скачанное,
промежуточное) — в outer/. Внутри каждой из трёх папок можно заводить
подпапки.

После записи файла — проверь ответ инструмента: если он сообщил об
ошибке или отказе, файл не сохранён, не пиши пользователю, что всё
готово.

Веди history.md в корне проекта — после каждого содержательного хода
коротко фиксируй, что сделано и что дальше, новую запись добавляй строго
снизу (append-only), не переписывая и не удаляя предыдущие. Держи размер
разумным — ориентировочно не больше ~200 записей; если файл сильно
разрастается, обобщи или сократи самые старые записи, не теряя ключевых
решений.

Это базовые конвенции проекта, общие для всех проектов на этой
платформе. Можешь дополнять этот файл своими, специфичными для этого
конкретного проекта, если пользователь просит что-то запомнить именно
для него.
"""

HISTORY_MD_TEMPLATE = """# История хода проекта

<!-- append-only: новые записи добавляй строго снизу, старые не трогай -->
"""


def _backfill_root_files(project_root: str) -> None:
    for name, template in (("AGENTS.md", AGENTS_MD_TEMPLATE), ("history.md", HISTORY_MD_TEMPLATE)):
        path = os.path.join(project_root, name)
        if not os.path.isfile(path):
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(template)
```

В `create_quick_chat`, сразу после записи `about.md` (`quickchat.py:131-132`):

```python
    with open(os.path.join(project_abs_path, "about.md"), "w", encoding="utf-8") as fh:
        fh.write(ABOUT_MD_PLACEHOLDER.format(title=f"Новый разговор {now_label}"))
    _backfill_root_files(project_abs_path)
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `cd hermes-web && PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins python3 -m pytest tests/test_quickchat.py -v`
Expected: PASS, все тесты файла (включая старые) зелёные.

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/quickchat.py hermes-web/tests/test_quickchat.py
git commit -m "feat(hermes-web): создавать AGENTS.md/history.md вместе с about.md для нового проекта"
```

---

### Task 2: Ленивый бэкфилл `AGENTS.md`/`history.md` для старых проектов

**Files:**
- Modify: `hermes-web/hermes_web/quickchat.py:156-173` (`get_or_open_session`)
- Test: `hermes-web/tests/test_quickchat.py`

**Interfaces:**
- Consumes: `_backfill_root_files(project_root: str) -> None` (Task 1).

- [ ] **Step 1: Написать падающие тесты**

Добавить после `test_get_or_open_session_reuses_existing_session`:

```python
@pytest.mark.asyncio
async def test_get_or_open_session_backfills_missing_agents_and_history_md(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )
    # AGENTS.md/history.md намеренно отсутствуют — проект "созданный до этой фичи".

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    assert os.path.isfile(project_dir / "AGENTS.md")
    assert os.path.isfile(project_dir / "history.md")
    assert "append-only" in (project_dir / "history.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_get_or_open_session_does_not_overwrite_existing_agents_md(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )
    (project_dir / "AGENTS.md").write_text("# Мои личные правила проекта\n", encoding="utf-8")

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    assert (project_dir / "AGENTS.md").read_text(encoding="utf-8") == "# Мои личные правила проекта\n"
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `cd hermes-web && PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins python3 -m pytest tests/test_quickchat.py -k "backfills_missing or does_not_overwrite_existing_agents_md" -v`
Expected: FAIL — `get_or_open_session` пока не вызывает `_backfill_root_files`, файлы не появляются.

- [ ] **Step 3: Вызвать `_backfill_root_files` в `get_or_open_session`**

```python
async def get_or_open_session(db_conn, http_session, config: Config, user: str, project_path: str) -> dict:
    resolved = project_index_core.resolve_project_path(user, project_path, _workspace_root(config))
    # get_project_detail кидает ProjectIndexError, если about.md не найден —
    # значит это не проект, открывать нечего.
    project_index_core.get_project_detail(user, project_path, workspace_root=_workspace_root(config))
    _backfill_root_files(resolved)

    existing = storage.get_chat_session_for_project(db_conn, user, resolved)
    ...
```

(Строка `_backfill_root_files(resolved)` — единственное добавление, всё
остальное тело функции без изменений.)

- [ ] **Step 4: Запустить и убедиться, что проходят**

Run: `cd hermes-web && PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins python3 -m pytest tests/test_quickchat.py -v`
Expected: PASS, все тесты файла зелёные.

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/quickchat.py hermes-web/tests/test_quickchat.py
git commit -m "feat(hermes-web): лениво досоздавать AGENTS.md/history.md для проектов без них"
```

---

### Task 3: `_agents_md_block` — чтение AGENTS.md с обрезкой и обработкой ошибок

**Files:**
- Modify: `hermes-web/hermes_web/quickchat.py` (новая функция рядом с `_system_message_for`, текущая строка 176)
- Test: `hermes-web/tests/test_quickchat.py`

**Interfaces:**
- Produces: `_agents_md_block(project_path: str) -> str` — `""`, если
  файла нет или ошибка чтения; иначе `"\n\nКонвенции проекта
  (AGENTS.md):\n{текст}"`, обрезанный до `AGENTS_MD_MAX_CHARS` символов
  с пометкой при превышении.

- [ ] **Step 1: Написать падающие тесты**

Добавить перед `test_system_message_requires_absolute_sandbox_path`:

```python
def test_agents_md_block_returns_empty_when_file_missing(tmp_path):
    assert quickchat._agents_md_block(str(tmp_path / "nope")) == ""


def test_agents_md_block_returns_content_when_present(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "AGENTS.md").write_text("# Мои правила\nПишем тесты.", encoding="utf-8")

    block = quickchat._agents_md_block(str(project_dir))

    assert "Конвенции проекта (AGENTS.md):" in block
    assert "Мои правила" in block


def test_agents_md_block_truncates_when_too_long(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "AGENTS.md").write_text("x" * (quickchat.AGENTS_MD_MAX_CHARS + 1000), encoding="utf-8")

    block = quickchat._agents_md_block(str(project_dir))

    assert "[...обрезано, полный текст в AGENTS.md]" in block
    assert len(block) < quickchat.AGENTS_MD_MAX_CHARS + 1000


def test_agents_md_block_logs_and_returns_empty_on_read_error(tmp_path, caplog):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "AGENTS.md").mkdir()  # директория вместо файла → open() кидает OSError

    with caplog.at_level("WARNING", logger="hermes_web.quickchat"):
        block = quickchat._agents_md_block(str(project_dir))

    assert block == ""
    assert "AGENTS.md" in caplog.text
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `cd hermes-web && PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins python3 -m pytest tests/test_quickchat.py -k test_agents_md_block -v`
Expected: FAIL — `AttributeError: module 'hermes_web.quickchat' has no attribute '_agents_md_block'`.

- [ ] **Step 3: Реализовать `_agents_md_block`**

Перед `_system_message_for` (текущая строка 176) добавить:

```python
AGENTS_MD_MAX_CHARS = 4000


def _agents_md_block(project_path: str) -> str:
    path = os.path.join(project_path, "AGENTS.md")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except FileNotFoundError:
        return ""
    except OSError:
        logger.warning("не удалось прочитать AGENTS.md: %s", path, exc_info=True)
        return ""
    if len(text) > AGENTS_MD_MAX_CHARS:
        text = text[:AGENTS_MD_MAX_CHARS] + "\n[...обрезано, полный текст в AGENTS.md]"
    return f"\n\nКонвенции проекта (AGENTS.md):\n{text}"
```

- [ ] **Step 4: Запустить и убедиться, что проходят**

Run: `cd hermes-web && PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins python3 -m pytest tests/test_quickchat.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/quickchat.py hermes-web/tests/test_quickchat.py
git commit -m "feat(hermes-web): читать AGENTS.md с обрезкой по лимиту и без падений на ошибках чтения"
```

---

### Task 4: `_system_message_for` подмешивает `agents_md_block`

**Files:**
- Modify: `hermes-web/hermes_web/quickchat.py:176-202` (`_system_message_for`)
- Test: `hermes-web/tests/test_quickchat.py`

**Interfaces:**
- Produces: `_system_message_for(project_path: str, result_target: Optional[str] = None, agents_md_block: str = "") -> str`
  — третий параметр опционален, дефолт `""` не меняет вывод для всех
  существующих вызовов без него.

- [ ] **Step 1: Написать падающие тесты**

Добавить после `test_system_message_without_result_target_unchanged`:

```python
def test_system_message_appends_agents_md_block_when_provided():
    msg = quickchat._system_message_for("/workspace/dem/ALL/x", agents_md_block="\n\nКонвенции проекта (AGENTS.md):\nМои правила")
    assert "Конвенции проекта (AGENTS.md):" in msg
    assert "Мои правила" in msg


def test_system_message_agents_md_block_defaults_to_empty():
    msg = quickchat._system_message_for("/workspace/dem/ALL/x")
    assert "Конвенции проекта (AGENTS.md):" not in msg


def test_system_message_agents_md_block_comes_after_result_target_hint():
    msg = quickchat._system_message_for(
        "/workspace/dem/ALL/x", result_target="result/kirik",
        agents_md_block="\n\nКонвенции проекта (AGENTS.md):\nМои правила",
    )
    assert msg.index("спроси пользователя") < msg.index("Конвенции проекта (AGENTS.md):")
```

- [ ] **Step 2: Запустить и убедиться, что падают**

Run: `cd hermes-web && PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins python3 -m pytest tests/test_quickchat.py -k "agents_md_block_when_provided or agents_md_block_defaults or agents_md_block_comes_after" -v`
Expected: FAIL — `_system_message_for()` пока не принимает `agents_md_block`.

- [ ] **Step 3: Добавить параметр и дописывание блока**

```python
def _system_message_for(project_path: str, result_target: Optional[str] = None, agents_md_block: str = "") -> str:
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
    if agents_md_block:
        message += agents_md_block
    return message
```

(Меняется только сигнатура и добавляется финальный `if agents_md_block`
блок — тело до этого без изменений.)

- [ ] **Step 4: Запустить и убедиться, что проходят**

Run: `cd hermes-web && PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins python3 -m pytest tests/test_quickchat.py -v`
Expected: PASS, включая все старые тесты `_system_message_for` (вызываются без нового параметра — дефолт `""` ничего не меняет).

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/quickchat.py hermes-web/tests/test_quickchat.py
git commit -m "feat(hermes-web): _system_message_for принимает опциональный agents_md_block"
```

---

### Task 5: Подключить `_agents_md_block` в `send_message`

**Files:**
- Modify: `hermes-web/hermes_web/quickchat.py:205-230` (`send_message`)
- Test: `hermes-web/tests/test_quickchat.py`

**Interfaces:**
- Consumes: `_agents_md_block(project_path: str) -> str` (Task 3),
  `_system_message_for(project_path, result_target=None, agents_md_block="")` (Task 4).

- [ ] **Step 1: Написать падающий тест**

Добавить после `test_send_message_forwards_result_target_to_system_message`:

```python
@pytest.mark.asyncio
async def test_send_message_includes_agents_md_content_when_present(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    host_project_path = tmp_path / "workspace" / "dem" / "ALL" / "2026-07-26_x"
    host_project_path.mkdir(parents=True)
    (host_project_path / "AGENTS.md").write_text("# Мои личные правила\nВсегда пиши по-русски.", encoding="utf-8")
    storage.create_chat_session(conn, "chat1", "dem", str(host_project_path), "web_x", created_at=1.0)

    async def fake_ensure_ownership(project_root):
        pass

    monkeypatch.setattr(quickchat.permissions, "ensure_ownership", fake_ensure_ownership)

    captured = {}

    async def fake_stream_chat(http_session, base_url, api_key, hermes_session_id, message, system_message=None):
        captured["system_message"] = system_message
        yield "done", {}

    monkeypatch.setattr(quickchat.hermes_client, "stream_chat", fake_stream_chat)

    async for _ in quickchat.send_message(conn, http_session=None, config=config, chat_session_id="chat1", text="привет"):
        pass

    assert "Мои личные правила" in captured["system_message"]
    assert "Всегда пиши по-русски." in captured["system_message"]
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `cd hermes-web && PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins python3 -m pytest tests/test_quickchat.py -k test_send_message_includes_agents_md_content_when_present -v`
Expected: FAIL — `send_message` пока не читает `AGENTS.md`, `captured["system_message"]` не содержит текста файла.

- [ ] **Step 3: Передать `agents_md_block` в `_system_message_for` внутри `send_message`**

```python
async def send_message(
    db_conn, http_session, config: Config, chat_session_id: str, text: str, result_target: Optional[str] = None,
) -> AsyncIterator[tuple[str, dict]]:
    row = storage.get_chat_session(db_conn, chat_session_id)
    if row is None:
        raise QuickChatError(f"неизвестная сессия чата: {chat_session_id}")

    await permissions.ensure_ownership(row["project_path"])

    reinforced = bool(result_target and _is_valid_result_target(result_target))
    logger.info(
        "chat_session_id=%s result_target=%r reinforced=%s",
        chat_session_id, result_target, reinforced,
    )

    async for name, payload in hermes_client.stream_chat(
        http_session,
        config.hermes_base_url,
        config.hermes_api_key,
        row["hermes_session_id"],
        text,
        system_message=_system_message_for(
            _sandbox_project_path(config, row["project_path"]),
            result_target,
            agents_md_block=_agents_md_block(row["project_path"]),
        ),
    ):
        yield name, payload

    storage.touch_chat_session(db_conn, chat_session_id, last_message_at=time.time())
```

(Единственное изменение — новый именованный аргумент
`agents_md_block=_agents_md_block(row["project_path"])` в вызове
`_system_message_for`; обратите внимание — путь берётся **хостовый**
`row["project_path"]`, а не sandbox-путь, потому что `hermes-web`
читает файл напрямую с диска сервера, а не через файловые инструменты
Hermes.)

- [ ] **Step 4: Запустить полный набор тестов**

Run: `cd hermes-web && PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins python3 -m pytest tests/ -q`
Expected: PASS, **212 теста** (201 базовых + 11 новых из Task 1–5:
1 в Task 1, 2 в Task 2, 4 в Task 3, 3 в Task 4, 1 в Task 5 — без
регрессий: тесты `send_message` без реального каталога на диске (не
создающие `host_project_path` физически) продолжают проходить — `open()`
на несуществующем пути кидает `FileNotFoundError`, который
`_agents_md_block` уже ловит и превращает в `""`).

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/quickchat.py hermes-web/tests/test_quickchat.py
git commit -m "feat(hermes-web): AGENTS.md проекта подмешивается в системное сообщение каждого хода"
```

---

## После реализации (не часть этого плана)

Деплой — тем же порядком, что и в предыдущих срезах (см. `docs/state.md`,
D-013/D-014): `rsync` изменённых `hermes_web/*.py` на сервер,
`systemctl --user restart hermes-web.service`, проверка `journalctl` на
чистый рестарт, живая проверка — открыть новый и старый (существовавший
до фичи) проект, подтвердить появление `AGENTS.md`/`history.md` и то, что
правки `AGENTS.md` через редактор UI реально меняют системное сообщение
следующего хода. Это делается после финального ревью всей ветки
(`superpowers:finishing-a-development-branch`), не как отдельная задача
плана.
