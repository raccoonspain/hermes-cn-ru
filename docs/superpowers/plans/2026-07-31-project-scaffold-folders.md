# Заводить папки source/outer/result вместе со стартовыми файлами проекта — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** При создании нового проекта (или первом открытии проекта, созданного
до этой фичи) `hermes_web/quickchat.py` создаёт не только
`about.md`/`AGENTS.md`/`history.md`, но и папки бакетов `source/`,
`outer/`, `result/` — чтобы дерево `project-workspace.html` показывало
полную структуру сразу, без первого сообщения агенту или ручного клика
«создать папку».

**Architecture:** Расширяем уже существующий хелпер
`_backfill_root_files` (переименовываем в `_backfill_project_scaffold`,
т.к. он больше не только про файлы) — после записи трёх файлов создаём
три директории через `os.makedirs(path, exist_ok=True)`, по списку
`workspace.BUCKETS` (единственный источник правды, уже существующий в
`hermes_web/workspace.py`). Обе существующие точки вызова
(`create_quick_chat`, `get_or_open_session`) переименовываются вместе с
функцией — новых точек вызова не добавляется.

**Tech Stack:** Python 3.12, aiohttp, pytest + pytest-asyncio (те же, что
и весь `hermes-web`).

## Global Constraints

- Единственный изменённый файл на бэкенде — `hermes_web/quickchat.py`
  (плюс тесты в `hermes_web/tests/test_quickchat.py`). Никаких новых
  HTTP-эндпоинтов, миграций БД, фронтенд-изменений — деплой остаётся
  однострочным `rsync` (см. спек, раздел «Деплой»).
- Список бакетов — **только** `workspace.BUCKETS`, второй хардкод-список
  `("source", "outer", "result")` в `quickchat.py` не заводить (см. спек,
  «Проблема» — тот же класс дублирования, что уже чинили в D-015).
- Ошибка создания одной папки логируется через `logger.warning` и не
  прерывает выполнение — та же политика отказоустойчивости, что уже есть
  у файловой части `_backfill_root_files` (try/except OSError).
- `os.makedirs(path, exist_ok=True)` — идемпотентность папок не требует
  отдельной проверки `isdir`, в отличие от файлов (где `isfile`-проверка
  нужна, чтобы не перезаписать пользовательское содержимое).

---

## Файлы

- **Modify:** `hermes-web/hermes_web/quickchat.py` — импорт `workspace`,
  переименование `_backfill_root_files` → `_backfill_project_scaffold` с
  добавлением цикла по бакетам, обновление двух точек вызова.
- **Test:** `hermes-web/tests/test_quickchat.py` — новые/обновлённые
  тесты на создание папок при `create_quick_chat` и
  `get_or_open_session`, идемпотентность, отказоустойчивость.

## Как запускать тесты

```bash
cd /home/deploy/hermes-cn-ru/hermes-web
PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins \
  /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3 \
  -m pytest tests/test_quickchat.py -v
```

Если этот venv недоступен (сессия сброшена, путь исчез) — пересоздать по
образцу плана `docs/superpowers/plans/2026-07-26-web-backend-auth-chat.md`
(aiohttp/argon2-cffi/pytest/pytest-asyncio, см. `docs/state.md`, раздел
«Главные подводные камни»). Перед первым запуском в этой сессии
проверить командой выше, что venv жив и текущие 39 тестов
`test_quickchat.py` зелёные (sanity check, не отдельный шаг плана — если
падает что-то из существующих тестов до наших изменений, это сигнал
сломанного окружения, не начинать реализацию, пока не разобрано).

---

### Task 1: Переименовать `_backfill_root_files` в `_backfill_project_scaffold` и научить создавать папки бакетов

**Files:**
- Modify: `hermes-web/hermes_web/quickchat.py:24` (импорт), `:98-106`
  (сама функция), `:175` и `:204` (точки вызова)
- Test: `hermes-web/tests/test_quickchat.py`

**Interfaces:**
- Consumes: `workspace.BUCKETS` — `tuple[str, ...]`, уже существует в
  `hermes_web/workspace.py:29` как `("source", "outer", "result")`.
- Produces: `quickchat._backfill_project_scaffold(project_root: str) -> None`
  — та же сигнатура и то же место в модуле, что раньше занимала
  `_backfill_root_files`; вызывающий код (`create_quick_chat`,
  `get_or_open_session`) обновляется в этой же задаче.

- [ ] **Step 1: Прочитать текущее состояние файла, чтобы не разъехаться с реальными номерами строк**

```bash
cd /home/deploy/hermes-cn-ru/hermes-web
sed -n '1,40p;90,210p' hermes_web/quickchat.py
```

Строки в этом плане (`:24`, `:98-106`, `:175`, `:204`) соответствуют
состоянию репозитория на момент написания плана (2026-07-31, после
деплоя D-015). Если они успели сдвинуться — искать по содержимому
(`_backfill_root_files`, `from . import hermes_client`), не вслепую по
номеру.

- [ ] **Step 2: Написать падающие тесты на создание папок в `create_quick_chat`**

Добавить в `hermes-web/tests/test_quickchat.py`, рядом с
`test_create_quick_chat_creates_agents_and_history_md` (после неё, перед
`test_send_message_forwards_project_path_as_system_message`):

```python
@pytest.mark.asyncio
async def test_create_quick_chat_creates_bucket_folders(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    result = await quickchat.create_quick_chat(conn, http_session=None, config=config, user="dem")

    for bucket in ("source", "outer", "result"):
        assert os.path.isdir(os.path.join(result["project_path"], bucket))
```

- [ ] **Step 3: Запустить тест, убедиться что падает**

```bash
PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins \
  /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3 \
  -m pytest tests/test_quickchat.py::test_create_quick_chat_creates_bucket_folders -v
```

Ожидается: FAIL — `AssertionError` (папки `source`/`outer`/`result` не
существуют, т.к. `create_quick_chat` их ещё не создаёт).

- [ ] **Step 4: Написать падающий тест на бэкфилл папок у старого проекта (`get_or_open_session`)**

Добавить рядом с `test_get_or_open_session_backfills_missing_agents_and_history_md`:

```python
@pytest.mark.asyncio
async def test_get_or_open_session_backfills_missing_bucket_folders(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )
    # source/outer/result намеренно отсутствуют — проект "созданный до этой фичи".

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    for bucket in ("source", "outer", "result"):
        assert os.path.isdir(project_dir / bucket)
```

- [ ] **Step 5: Запустить оба новых теста, убедиться что падают**

```bash
PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins \
  /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3 \
  -m pytest tests/test_quickchat.py::test_create_quick_chat_creates_bucket_folders tests/test_quickchat.py::test_get_or_open_session_backfills_missing_bucket_folders -v
```

Ожидается: оба FAIL.

- [ ] **Step 6: Импортировать `workspace` в `quickchat.py`**

Найти строку:

```python
from . import hermes_client, permissions, storage
```

Заменить на:

```python
from . import hermes_client, permissions, storage, workspace
```

- [ ] **Step 7: Переименовать функцию и добавить создание папок бакетов**

Найти:

```python
def _backfill_root_files(project_root: str) -> None:
    for name, template in (("AGENTS.md", AGENTS_MD_TEMPLATE), ("history.md", HISTORY_MD_TEMPLATE)):
        path = os.path.join(project_root, name)
        if not os.path.isfile(path):
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(template)
            except OSError:
                logger.warning("не удалось создать %s в %s", name, project_root, exc_info=True)
```

Заменить на:

```python
def _backfill_project_scaffold(project_root: str) -> None:
    for name, template in (("AGENTS.md", AGENTS_MD_TEMPLATE), ("history.md", HISTORY_MD_TEMPLATE)):
        path = os.path.join(project_root, name)
        if not os.path.isfile(path):
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(template)
            except OSError:
                logger.warning("не удалось создать %s в %s", name, project_root, exc_info=True)
    for bucket in workspace.BUCKETS:
        path = os.path.join(project_root, bucket)
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            logger.warning("не удалось создать папку %s в %s", bucket, project_root, exc_info=True)
```

- [ ] **Step 8: Обновить обе точки вызова**

В `create_quick_chat` найти:

```python
    _backfill_root_files(project_abs_path)
```

Заменить на:

```python
    _backfill_project_scaffold(project_abs_path)
```

В `get_or_open_session` найти:

```python
    _backfill_root_files(resolved)
```

Заменить на:

```python
    _backfill_project_scaffold(resolved)
```

- [ ] **Step 9: Запустить оба новых теста, убедиться что проходят**

```bash
PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins \
  /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3 \
  -m pytest tests/test_quickchat.py::test_create_quick_chat_creates_bucket_folders tests/test_quickchat.py::test_get_or_open_session_backfills_missing_bucket_folders -v
```

Ожидается: оба PASS.

- [ ] **Step 10: Запустить весь `test_quickchat.py`, убедиться что ничего не сломалось**

```bash
PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins \
  /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3 \
  -m pytest tests/test_quickchat.py -v
```

Ожидается: 41 passed (39 существующих + 2 новых из этой задачи).

- [ ] **Step 11: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/hermes_web/quickchat.py hermes-web/tests/test_quickchat.py
git commit -m "feat(hermes-web): создавать папки source/outer/result вместе со стартовыми файлами проекта"
```

---

### Task 2: Идемпотентность и отказоустойчивость создания папок

**Files:**
- Modify: нет (код уже написан в Task 1) — только тесты
- Test: `hermes-web/tests/test_quickchat.py`

**Interfaces:**
- Consumes: `quickchat._backfill_project_scaffold(project_root: str) -> None`
  (из Task 1).
- Produces: ничего нового для последующих задач — это последняя задача
  плана.

- [ ] **Step 1: Написать падающий тест на идемпотентность (повторный вызов не трогает содержимое бакета)**

Добавить в `hermes-web/tests/test_quickchat.py`, сразу после
`test_get_or_open_session_backfills_missing_bucket_folders`:

```python
@pytest.mark.asyncio
async def test_get_or_open_session_does_not_touch_existing_bucket_contents(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )
    (project_dir / "source").mkdir()
    (project_dir / "source" / "notes.txt").write_text("не трогать", encoding="utf-8")

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    assert (project_dir / "source" / "notes.txt").read_text(encoding="utf-8") == "не трогать"
    assert os.path.isdir(project_dir / "outer")
    assert os.path.isdir(project_dir / "result")
```

Это на самом деле уже должно пройти сразу после Task 1 (`exist_ok=True`
не трогает существующее содержимое директории) — тест здесь для защиты
от регрессии, а не потому что ожидается провал. Всё равно прогнать сразу
после написания, чтобы убедиться, что тест вообще что-то проверяет (а не
падает по опечатке в фикстуре).

- [ ] **Step 2: Запустить, убедиться что проходит**

```bash
PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins \
  /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3 \
  -m pytest tests/test_quickchat.py::test_get_or_open_session_does_not_touch_existing_bucket_contents -v
```

Ожидается: PASS сразу (см. Step 1 — это тест-регрессия, не TDD-red).
Если он FAIL — значит реализация Task 1 отличается от плана, остановиться
и разобраться, прежде чем продолжать.

- [ ] **Step 3: Написать падающий тест на отказоустойчивость (один бакет занят файлом)**

```python
@pytest.mark.asyncio
async def test_get_or_open_session_logs_and_continues_when_bucket_path_is_a_file(tmp_path, monkeypatch, caplog):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(
        "---\ntags: []\nstatus: active\n---\n\n# Название проекта\nТест\n\n# Краткое описание\nОписание\n", encoding="utf-8",
    )
    # "source" занят файлом, а не папкой — os.makedirs(..., exist_ok=True)
    # в этом случае бросает FileExistsError (подкласс OSError).
    (project_dir / "source").write_text("не папка", encoding="utf-8")

    async def fake_create_session(http_session, base_url, api_key, session_id):
        return {"session": {"id": session_id}}

    monkeypatch.setattr(quickchat.hermes_client, "create_session", fake_create_session)

    with caplog.at_level("WARNING", logger="hermes_web.quickchat"):
        await quickchat.get_or_open_session(conn, http_session=None, config=config, user="dem", project_path="dem/ALL/a")

    assert "source" in caplog.text
    # Остальные два бакета создались несмотря на ошибку первого.
    assert os.path.isdir(project_dir / "outer")
    assert os.path.isdir(project_dir / "result")
    # Файл "source" остался нетронутым, а не превратился в директорию силой.
    assert (project_dir / "source").is_file()
```

- [ ] **Step 4: Запустить, проверить поведение**

```bash
PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins \
  /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3 \
  -m pytest tests/test_quickchat.py::test_get_or_open_session_logs_and_continues_when_bucket_path_is_a_file -v
```

Ожидается: PASS, если Task 1 реализована по плану (try/except вокруг
каждого `os.makedirs` в цикле — ошибка на одном бакете не прерывает
остальные). Если FAIL с необработанным `FileExistsError` — значит
try/except в Task 1 обёрнут не вокруг каждой итерации цикла, а вокруг
всего цикла целиком; поправить `_backfill_project_scaffold` так, чтобы
`try/except` был внутри `for bucket in workspace.BUCKETS:`, на каждую
итерацию отдельно (как и написано в Task 1, Step 7 — сверить дословно).

- [ ] **Step 5: Запустить весь `test_quickchat.py` целиком**

```bash
PROJECT_INDEX_PLUGIN_DIR=/home/deploy/hermes-cn-ru/hermes-plugins \
  /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3 \
  -m pytest tests/test_quickchat.py -v
```

Ожидается: 43 passed (41 из Task 1 + 2 новых из этой задачи).

- [ ] **Step 6: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-web/tests/test_quickchat.py
git commit -m "test(hermes-web): идемпотентность и отказоустойчивость создания папок бакетов"
```

---

## После реализации (не отдельная задача — ручные шаги)

1. **Финальное ревью всей ветки** — по конвенции проекта
   (subagent-driven-development), отдельный проход самой мощной моделью
   поверх обеих задач целиком, до деплоя.
2. **Деплой на VPS** — `rsync hermes_web/quickchat.py` (единственный
   изменённый файл) + `systemctl --user restart hermes-web.service`,
   проверка `journalctl` на чистый рестарт без трейсбеков (см. спек,
   раздел «Деплой»).
3. **Живая приёмка** — одноразовый `qa_temp` (создание/удаление как в
   D-015, см. `docs/changelog.md` за 2026-07-31): создать проект через
   «Быстрый чат», убедиться что `source/outer/result` видны в дереве
   `project-workspace.html` сразу, без первого сообщения агенту; открыть
   существующий (`dem`/`rost`) проект, созданный до этой фичи — папки
   должны появиться при открытии.
4. **`docs/state.md`/`docs/changelog.md`/`git snapshot.sh`** — как после
   каждого шага проекта (см. `CLAUDE.md`).
