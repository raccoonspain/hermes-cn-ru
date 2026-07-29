# Самовосстановление владельца файлов в workspace агента — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Автоматически чинить root-owned файлы/папки внутри проектов агента (`/home/hermes/workspace/...`) до того, как они заблокируют запись — без ручного `chmod`/approve в чате.

**Architecture:** Один root-owned shell-скрипт с собственной проверкой пути + одна sudoers-строка, разрешающая пользователю `hermes` вызвать ровно этот скрипт без пароля. Новый модуль `hermes_web/permissions.py` оборачивает вызов (`ensure_ownership_sync` / асинхронный `ensure_ownership`) и никогда не бросает исключение наружу. Вызывается из `quickchat.send_message` (перед каждым ходом чата) и из `workspace.save_file`/`make_dir`/`save_upload` (перед каждой файловой операцией из UI).

**Tech Stack:** Python 3 (aiohttp-бэкенд `hermes-web`), pytest + pytest-asyncio, bash, sudoers.

## Global Constraints

- Скрипт сам проверяет резолвленный (`readlink -f`) путь и отказывает работать за пределами `/home/hermes/workspace` — даже если sudoers-шаблон совпадёт шире, чем задумано.
- Sudoers-правило разрешает `hermes` вызвать **только** этот один скрипт, ничего больше (`NOPASSWD`, без общего `chown`/`sudo bash`).
- `sudo -n` — если правило не применилось, вызов должен сразу вернуть ошибку, а не повиснуть в ожидании пароля (которого у `hermes` нет, `passwd -l`).
- `ensure_ownership`/`ensure_ownership_sync` никогда не бросают исключение — это самолечение "по возможности", сбой не должен ронять чат или файловую операцию.
- `ensure_ownership` (async) обязана снять работу с event loop через `run_in_executor` — не блокировать другие одновременные запросы (тот же принцип, что уже применён к `project_index_core.index_update`).
- Не патчить вендорный код Hermes (`agent/file_safety.py` и т.п.) — только код `hermes-web` и серверная инфраструктура.
- Никогда не расширять привилегии `hermes` дальше одного этого скрипта (см. D-003).

---

### Task 1: `hermes_web/permissions.py` — модуль самопочинки владельца

**Files:**
- Create: `hermes-web/hermes_web/permissions.py`
- Test: `hermes-web/tests/test_permissions.py`

**Interfaces:**
- Produces: `ensure_ownership_sync(project_root: str) -> None` (синхронная, никогда не бросает).
- Produces: `async def ensure_ownership(project_root: str) -> None` (снимает `ensure_ownership_sync` с event loop через `run_in_executor`).
- Обе читают путь к скрипту из константы `FIX_SCRIPT_PATH = "/usr/local/bin/hermes-fix-workspace-perms.sh"` в этом же модуле.

- [ ] **Step 1: Написать падающие тесты**

```python
# hermes-web/tests/test_permissions.py
import asyncio
import logging
import subprocess
import threading

import pytest

from hermes_web import permissions


def test_ensure_ownership_sync_calls_sudo_script_with_project_root(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, timeout):
        captured["cmd"] = cmd
        captured["capture_output"] = capture_output
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(permissions.subprocess, "run", fake_run)

    permissions.ensure_ownership_sync("/home/hermes/workspace/dem/ALL/a")

    assert captured["cmd"] == [
        "sudo", "-n", permissions.FIX_SCRIPT_PATH, "/home/hermes/workspace/dem/ALL/a",
    ]
    assert captured["capture_output"] is True
    assert captured["timeout"] == 30


def test_ensure_ownership_sync_never_raises_on_nonzero_exit(monkeypatch, caplog):
    def fake_run(cmd, capture_output, timeout):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout=b"", stderr=b"refuse: outside root")

    monkeypatch.setattr(permissions.subprocess, "run", fake_run)

    with caplog.at_level(logging.WARNING):
        permissions.ensure_ownership_sync("/home/hermes/workspace/dem/ALL/a")  # не должно бросить

    assert "refuse: outside root" in caplog.text


def test_ensure_ownership_sync_never_raises_on_timeout(monkeypatch, caplog):
    def fake_run(cmd, capture_output, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(permissions.subprocess, "run", fake_run)

    with caplog.at_level(logging.WARNING):
        permissions.ensure_ownership_sync("/home/hermes/workspace/dem/ALL/a")  # не должно бросить

    assert "timed out" in caplog.text.lower() or "timeout" in caplog.text.lower()


@pytest.mark.asyncio
async def test_ensure_ownership_runs_off_event_loop(monkeypatch):
    calling_thread = threading.current_thread()
    seen = {}

    def fake_sync(project_root):
        seen["thread"] = threading.current_thread()
        seen["project_root"] = project_root

    monkeypatch.setattr(permissions, "ensure_ownership_sync", fake_sync)

    await permissions.ensure_ownership("/home/hermes/workspace/dem/ALL/a")

    assert seen["project_root"] == "/home/hermes/workspace/dem/ALL/a"
    assert seen["thread"] is not calling_thread
    assert seen["thread"] is not threading.main_thread()
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd hermes-web && python -m pytest tests/test_permissions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hermes_web.permissions'`

- [ ] **Step 3: Реализовать модуль**

```python
# hermes-web/hermes_web/permissions.py
"""Самопочинка владельца файлов внутри /home/hermes/workspace.

Терминал/execute_code-инструменты Hermes при terminal.backend: docker
иногда создают файлы/папки от root вместо ожидаемого uid хоста (тот же
класс бага, что и открытый upstream-баг hermes-agent#32049) — root-owned
запись потом блокирует ЛЮБУЮ последующую запись в это же место, потому
что chown чужого файла может выполнить только root, вне зависимости от
того, кто владеет папкой вокруг (см. docs/superpowers/specs/
2026-07-29-workspace-permissions-self-heal-design.md). hermes не имеет
sudo вообще (D-003) — здесь у него ровно одно узкое исключение: вызвать
этот один root-скрипт, который сам же отказывается работать за
пределами /home/hermes/workspace.

Это самолечение "по возможности": обе функции никогда не бросают
исключение — сбой самопочинки не должен ронять чат или файловую
операцию, которая её вызвала.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess

logger = logging.getLogger(__name__)

FIX_SCRIPT_PATH = "/usr/local/bin/hermes-fix-workspace-perms.sh"


def ensure_ownership_sync(project_root: str) -> None:
    try:
        result = subprocess.run(
            ["sudo", "-n", FIX_SCRIPT_PATH, project_root],
            capture_output=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ensure_ownership_sync timed out for %s", project_root)
        return
    if result.returncode != 0:
        logger.warning(
            "ensure_ownership_sync failed for %s: %s", project_root, result.stderr.decode(errors="replace"),
        )


async def ensure_ownership(project_root: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, ensure_ownership_sync, project_root)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd hermes-web && python -m pytest tests/test_permissions.py -v`
Expected: PASS — все 4 теста

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/permissions.py hermes-web/tests/test_permissions.py
git commit -m "feat(hermes-web): модуль самопочинки владельца workspace-файлов"
```

---

### Task 2: Вызов `ensure_ownership` перед каждым ходом чата

**Files:**
- Modify: `hermes-web/hermes_web/quickchat.py:181-196` (`send_message`)
- Test: `hermes-web/tests/test_quickchat.py`

**Interfaces:**
- Consumes: `permissions.ensure_ownership(project_root: str) -> None` (Task 1).
- Не меняет сигнатуру `send_message` — только добавляет вызов внутри неё, до `hermes_client.stream_chat`.

- [ ] **Step 1: Написать падающий тест**

Добавить в `hermes-web/tests/test_quickchat.py` (рядом с
`test_send_message_forwards_project_path_as_system_message`):

```python
@pytest.mark.asyncio
async def test_send_message_ensures_ownership_before_dispatch(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    host_project_path = str(tmp_path / "workspace" / "dem" / "ALL" / "2026-07-26_x")
    storage.create_chat_session(conn, "chat1", "dem", host_project_path, "web_x", created_at=1.0)

    calls = []

    async def fake_ensure_ownership(project_root):
        calls.append(project_root)

    monkeypatch.setattr(quickchat.permissions, "ensure_ownership", fake_ensure_ownership)

    async def fake_stream_chat(http_session, base_url, api_key, hermes_session_id, message, system_message=None):
        # На момент вызова стриминга самопочинка уже должна была отработать.
        assert calls == [host_project_path]
        yield "done", {}

    monkeypatch.setattr(quickchat.hermes_client, "stream_chat", fake_stream_chat)

    events = []
    async for name, payload in quickchat.send_message(conn, http_session=None, config=config, chat_session_id="chat1", text="привет"):
        events.append((name, payload))

    assert calls == [host_project_path]
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `cd hermes-web && python -m pytest tests/test_quickchat.py::test_send_message_ensures_ownership_before_dispatch -v`
Expected: FAIL — `AttributeError: module 'hermes_web.quickchat' has no attribute 'permissions'`

- [ ] **Step 3: Добавить вызов в `send_message`**

В `hermes-web/hermes_web/quickchat.py` изменить импорт (строка 24):

```python
from . import hermes_client, permissions, storage
```

И в `send_message` (было — строки 181-196):

```python
async def send_message(db_conn, http_session, config: Config, chat_session_id: str, text: str) -> AsyncIterator[tuple[str, dict]]:
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
        system_message=_system_message_for(_sandbox_project_path(config, row["project_path"])),
    ):
        yield name, payload

    storage.touch_chat_session(db_conn, chat_session_id, last_message_at=time.time())
```

(Именно `row["project_path"]" — хостовый путь, тот же, что уже пишет в БД `storage.create_chat_session`, а не sandbox-alias из `_sandbox_project_path` — `chown` должен применяться к реальному пути на диске.)

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd hermes-web && python -m pytest tests/test_quickchat.py -v`
Expected: PASS — все тесты, включая новый и уже существующие (`test_send_message_forwards_project_path_as_system_message` и др.)

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/quickchat.py hermes-web/tests/test_quickchat.py
git commit -m "feat(hermes-web): чинить владельца проекта перед каждым ходом чата"
```

---

### Task 3: Вызов `ensure_ownership_sync` перед файловыми операциями UI

**Files:**
- Modify: `hermes-web/hermes_web/workspace.py:198-222` (`save_file`), `:225-239` (`make_dir`), `:242-` (`save_upload`)
- Test: `hermes-web/tests/test_workspace.py`

**Interfaces:**
- Consumes: `permissions.ensure_ownership_sync(project_root: str) -> None` (Task 1).
- Сигнатуры `save_file`/`make_dir`/`save_upload` не меняются.

- [ ] **Step 1: Написать падающие тесты**

Добавить в `hermes-web/tests/test_workspace.py`:

```python
@pytest.mark.asyncio
async def test_save_file_ensures_ownership_before_write(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()

    calls = []
    monkeypatch.setattr(workspace.permissions, "ensure_ownership_sync", lambda root: calls.append(root))

    await workspace.save_file("dem", "dem/ALL/a", "source/note.txt", "текст", config)

    assert calls == [str(project_dir)]


def test_make_dir_ensures_ownership_before_write(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")

    calls = []
    monkeypatch.setattr(workspace.permissions, "ensure_ownership_sync", lambda root: calls.append(root))

    workspace.make_dir("dem", "dem/ALL/a", "source", "Иванов", config)

    assert calls == [str(project_dir)]


def test_save_upload_ensures_ownership_before_write(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")

    calls = []
    monkeypatch.setattr(workspace.permissions, "ensure_ownership_sync", lambda root: calls.append(root))

    workspace.save_upload("dem", "dem/ALL/a", "source", "scan.pdf", b"content", config)

    assert calls == [str(project_dir)]
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `cd hermes-web && python -m pytest tests/test_workspace.py -k ensures_ownership -v`
Expected: FAIL — `AttributeError: module 'hermes_web.workspace' has no attribute 'permissions'`

- [ ] **Step 3: Добавить вызовы**

В `hermes-web/hermes_web/workspace.py` добавить импорт (рядом со строкой 25):

```python
from . import permissions
```

В `save_file` (строка 203, сразу после `resolve_file_path`):

```python
    project_root, candidate = resolve_file_path(user, project_path, relative_path, config)
    permissions.ensure_ownership_sync(project_root)
    if relative_path not in ROOT_EDITABLE_FILES:
        _require_within_bucket(project_root, candidate)
```

В `make_dir` (строка 229, сразу после `resolve_file_path`):

```python
    project_root, parent_candidate = resolve_file_path(user, project_path, parent, config)
    permissions.ensure_ownership_sync(project_root)
    _require_within_bucket(project_root, parent_candidate)
```

В `save_upload` (строка 247, сразу после `resolve_file_path`):

```python
    project_root, target_dir_candidate = resolve_file_path(user, project_path, target_dir, config)
    permissions.ensure_ownership_sync(project_root)
    _require_within_bucket(project_root, target_dir_candidate)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `cd hermes-web && python -m pytest tests/test_workspace.py -v`
Expected: PASS — все тесты, старые и новые (149+ уже существующих + 3 новых)

- [ ] **Step 5: Commit**

```bash
git add hermes-web/hermes_web/workspace.py hermes-web/tests/test_workspace.py
git commit -m "feat(hermes-web): чинить владельца проекта перед файловыми операциями UI"
```

---

### Task 4: Серверные артефакты (скрипт + sudoers) и деплой на VPS

**Files:**
- Create: `ops/workspace-perms/hermes-fix-workspace-perms.sh`
- Create: `ops/workspace-perms/sudoers-hermes-fix-workspace-perms`

**Interfaces:**
- Путь скрипта на сервере (`/usr/local/bin/hermes-fix-workspace-perms.sh`) должен буквально совпадать с `permissions.FIX_SCRIPT_PATH` из Task 1.

- [ ] **Step 1: Создать скрипт**

```bash
#!/bin/bash
# ops/workspace-perms/hermes-fix-workspace-perms.sh
# Разворачивается на сервере как /usr/local/bin/hermes-fix-workspace-perms.sh,
# root:root, chmod 700. Единственная задача: chown -R hermes:hermes на
# путь, переданный первым аргументом — но только если он лежит внутри
# /home/hermes/workspace (см. docs/superpowers/specs/
# 2026-07-29-workspace-permissions-self-heal-design.md). Сам перепроверяет
# резолвленный путь — не полагается только на sudoers-шаблон.
set -euo pipefail
target="$(readlink -f "$1")"
root="/home/hermes/workspace"
if [[ "$target" != "$root" && "$target" != "$root"/* ]]; then
    echo "refuse: '$target' is outside $root" >&2
    exit 1
fi
chown -R hermes:hermes "$target"
```

- [ ] **Step 2: Проверить синтаксис скрипта локально**

Run: `bash -n ops/workspace-perms/hermes-fix-workspace-perms.sh`
Expected: без вывода, exit code 0

- [ ] **Step 3: Создать sudoers-файл**

```
# ops/workspace-perms/sudoers-hermes-fix-workspace-perms
# Разворачивается на сервере как /etc/sudoers.d/hermes-fix-workspace-perms.
# Единственная новая привилегия hermes (D-003: без sudo вообще до этого
# момента) — вызвать ровно этот скрипт без пароля. См. docs/superpowers/
# specs/2026-07-29-workspace-permissions-self-heal-design.md.
hermes ALL=(root) NOPASSWD: /usr/local/bin/hermes-fix-workspace-perms.sh *
```

- [ ] **Step 4: Закоммитить артефакты**

```bash
git add ops/workspace-perms/hermes-fix-workspace-perms.sh ops/workspace-perms/sudoers-hermes-fix-workspace-perms
git commit -m "feat(ops): скрипт+sudoers для самопочинки владельца workspace"
```

- [ ] **Step 5: Задеплоить на VPS (root)**

```bash
scp -i ~/.ssh/id_ed25519_hermes_vps ops/workspace-perms/hermes-fix-workspace-perms.sh root@212.115.55.116:/usr/local/bin/hermes-fix-workspace-perms.sh
ssh -i ~/.ssh/id_ed25519_hermes_vps root@212.115.55.116 "chown root:root /usr/local/bin/hermes-fix-workspace-perms.sh && chmod 700 /usr/local/bin/hermes-fix-workspace-perms.sh"

scp -i ~/.ssh/id_ed25519_hermes_vps ops/workspace-perms/sudoers-hermes-fix-workspace-perms root@212.115.55.116:/etc/sudoers.d/hermes-fix-workspace-perms
ssh -i ~/.ssh/id_ed25519_hermes_vps root@212.115.55.116 "chmod 440 /etc/sudoers.d/hermes-fix-workspace-perms && visudo -c"
```

Expected на `visudo -c`: `/etc/sudoers.d/hermes-fix-workspace-perms: parsed OK` (и без ошибок по остальным файлам).

- [ ] **Step 6: Живая проверка sudo-правила от имени `hermes`**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_vps hermes@212.115.55.116 "sudo -n /usr/local/bin/hermes-fix-workspace-perms.sh /home/hermes/workspace/dem && echo OK"
ssh -i ~/.ssh/id_ed25519_hermes_vps hermes@212.115.55.116 "sudo -n /usr/local/bin/hermes-fix-workspace-perms.sh /etc; echo \"exit=\$?\""
```

Expected: первая команда — `OK` (chown прошёл на легитимном пути); вторая — ненулевой `exit`, скрипт отказал (`refuse: '/etc' is outside /home/hermes/workspace`).

- [ ] **Step 7: Задеплоить обновлённый `hermes-web` и перезапустить сервис**

```bash
rsync -avz -e "ssh -i ~/.ssh/id_ed25519_hermes_vps" hermes-web/hermes_web/permissions.py hermes-web/hermes_web/quickchat.py hermes-web/hermes_web/workspace.py hermes@212.115.55.116:~/hermes-web/hermes_web/
ssh -i ~/.ssh/id_ed25519_hermes_vps hermes@212.115.55.116 "systemctl --user restart hermes-web.service && systemctl --user status hermes-web.service --no-pager"
```

Expected: `active (running)`.

- [ ] **Step 8: Живая приёмка на `qa_temp`**

Разово завести тестовый проект (или переиспользовать существующий тестовый аккаунт `qa_temp`, как в предыдущих срезах), намеренно испортить владельца тестовой папки под root:

```bash
ssh -i ~/.ssh/id_ed25519_hermes_vps root@212.115.55.116 "mkdir -p /home/hermes/workspace/qa_temp/ALL/perm-test/source/broken && chown -R root:root /home/hermes/workspace/qa_temp/ALL/perm-test/source/broken"
```

Открыть этот проект в `project-workspace.html`, отправить любое сообщение в чат (или через UI создать файл внутри `source/broken`) — убедиться, что папка автоматически стала `hermes:hermes` **до** ответа агента/до записи, без единого `chmod`/approve в чате:

```bash
ssh -i ~/.ssh/id_ed25519_hermes_vps root@212.115.55.116 "stat -c '%U:%G' /home/hermes/workspace/qa_temp/ALL/perm-test/source/broken"
```

Expected: `hermes:hermes`. После проверки — удалить тестовый проект `qa_temp` (как в предыдущих срезах).

- [ ] **Step 9: Обновить `docs/state.md`/`docs/changelog.md`/`docs/decisions.md`**

Записать в `changelog.md` факт находки и фикса (по образцу записи D-011),
добавить `D-012` в `decisions.md` (ссылка на этот спек/план), обновить
"Сейчас в работе" в `state.md`. Запустить `bash scripts/snapshot.sh
"самопочинка владельца workspace задеплоена"`.

---

## Self-Review

**1. Соответствие спеку:** скрипт с самопроверкой пути (Task 4), sudoers-правило (Task 4), модуль `permissions.py` (Task 1), точка вызова в `quickchat.send_message` (Task 2), точки вызова в `workspace.save_file`/`make_dir`/`save_upload` (Task 3), `sudo -n` (Task 1), деплой + живая приёмка (Task 4) — все разделы спека покрыты.

**2. Плейсхолдеры:** нет `TBD`/`TODO`, весь код — рабочий, все шаги содержат точный код или точную команду.

**3. Согласованность типов/имён:** `permissions.FIX_SCRIPT_PATH`, `permissions.ensure_ownership_sync`, `permissions.ensure_ownership` — одинаковые имена во всех трёх задачах, где они используются (Task 2 и 3 используют ровно то, что произведено в Task 1). `row["project_path"]` (хостовый путь) — единственный аргумент, передаваемый в `ensure_ownership`/`ensure_ownership_sync` везде, ни разу не перепутан со sandbox-путём (`_sandbox_project_path`).
