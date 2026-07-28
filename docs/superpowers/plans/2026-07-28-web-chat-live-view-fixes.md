# Живой вид чата на рабочем экране проекта — 4 фикса Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть 4 бага живого чата на `project-workspace.html`, найденных
вторым живым прогоном заказчика 2026-07-28: пустые пузыри в ленте,
одинаковое время у всех сообщений, чат не обновляется сам на многошаговых
ходах, итоговый файл агента не виден вне `source/outer/result`.

**Architecture:** Каждый баг — независимая, точечная правка (не связаны
друг с другом кодом, только общим источником диагностики). Задачи 1-3 —
чистый JS-фронтенд без сборщика (`project-workspace.html`), задача 4 —
Python-бэкенд (`hermes_web/workspace.py`) + рендер нового раздела дерева
на фронтенде. Задача 5 — сквозная ручная проверка всех четырёх фиксов на
реальном сервере одним QA-проходом (так эффективнее одного `qa_temp`-
захода, чем 4 отдельных).

**Tech Stack:** Python 3 / aiohttp (бэкенд), vanilla JS без сборщика
(фронтенд), pytest/pytest-asyncio (тесты бэкенда).

## Global Constraints

- Источник истины по каждому багу — спек
  `docs/superpowers/specs/2026-07-28-web-chat-live-view-fixes-design.md`
  (причина, доказательства, точный фикс на каждый пункт). Этот план не
  переоткрывает диагностику, только переводит спек в шаги.
- В проекте нет JS-тестового фреймворка (решение зафиксировано в
  предыдущих срезах) — для задач 1-3 (чистый JS) TDD в узком смысле не
  применяется, вместо RED/GREEN-цикла — прямая правка + обязательная
  ручная проверка в конце (задача 5). Для задачи 4 (Python) — обычный
  RED → GREEN цикл, как во всех предыдущих срезах.
- Тестовый venv: `PROJECT_INDEX_PLUGIN_DIR=../hermes-plugins`, интерпретатор
  `/tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3`
  (если сессия, в которой исполняется этот план, отличается — venv нужно
  создать заново по образцу плана `2026-07-26-web-backend-auth-chat.md`,
  зависимости: aiohttp, argon2-cffi, pytest, pytest-asyncio). Команды
  запуска тестов в задачах ниже даны из каталога `hermes-web/`.
- `chat.html` сознательно не трогаем в этом срезе (см. спек, раздел «Вне
  рамок этого документа» и Проблему 3) — там та же многослотовая модель,
  но продукт для короткого разового диалога, а не для просмотра шагов.
- Не пытаться заставить модель класть файлы строго в `result/` новым
  промпт-инженирингом — этот путь уже пройден (system-сообщение уже
  просит об этом) и недостаточен сам по себе; задача 4 чинит это на
  уровне продукта (показываем то, что реально есть на диске).
- Контракт SSE Hermes API подтверждён чтением реального обработчика на
  VPS (см. `docs/superpowers/specs/2026-07-27-web-project-workspace-design.md`,
  раздел «Проверено в текущем коде»): `event: <name>` включает
  `run.started`/`message.started`/`assistant.delta`/`assistant.completed`/
  `tool.started`/`tool.progress`/`tool.completed`/`tool.failed`/
  `run.completed`/`done`/`error`. `handle_send_message` в `app.py`
  пересылает все именованные события в браузер как есть — в бэкенде для
  этого плана менять нечего, кроме задачи 4 (`list_tree`).

---

## Task 1: Не рендерить пустые пузыри ассистента (Проблема 1)

**Files:**
- Modify: `hermes-web/static/project-workspace.html:281-297` (`renderMessages`)

**Interfaces:**
- Не меняет сигнатуру `renderMessages()` (без аргументов, читает глобальный
  `messages`), не меняет индексацию `messages`/`id="msg-${idx}"` —
  `jumpToMessage(idx)` уже безопасно ничего не делает, если DOM-узла нет
  (`if (!target) return;`, строка 274).

- [ ] **Step 1: Пропускать рендер пустых assistant-сообщений без вложений**

В `renderMessages()` (`hermes-web/static/project-workspace.html`) заменить
тело `.map()`:

```javascript
// БЫЛО:
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
      ...
    </div>`;
  }).join('');
```

```javascript
// СТАЛО:
  el.innerHTML = messages.map((m, idx) => {
    if (m.role !== 'user' && m.role !== 'assistant') return '';
    const { text, attachments } = splitAttachments(m.content);
    // Hermes хранит каждый шаг tool-calling цикла отдельным assistant-
    // сообщением — часть из них легитимно пустые (модель молча вызвала
    // инструмент, ничего не написав). Рендерить такие как пустую тёмную
    // капсулу нечего — пропускаем узел целиком, не трогая индексацию.
    if (m.role === 'assistant' && !text.trim() && attachments.length === 0) return '';
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
```

- [ ] **Step 2: Проверить вручную (нет JS-тестового фреймворка в этом проекте)**

Run: `cd hermes-web/static && python3 -m http.server 8080`, открыть
`project-workspace.html?path=<любой существующий проект>` в браузере с
авторизацией, отправить сообщение вида «вызови terminal без комментария,
просто выполни echo hi» (или использовать реальную историю сессии
`web_7dc4e63efa3942429b8e1d1e06b0171a`, если тестовый сервер настроен на
ту же БД, что и прод — если нет, отложить прямую проверку живых данных
до задачи 5).

Expected: пустые тёмные капсулы не появляются в ленте; сообщения с
текстом или вложениями рендерятся как раньше; полная живая проверка на
реальном сервере — в задаче 5.

- [ ] **Step 3: Commit**

```bash
git add hermes-web/static/project-workspace.html
git commit -m "fix(hermes-web): не рендерить пустые assistant-сообщения в чате"
```

---

## Task 2: Секунды vs миллисекунды в `formatTime()` (Проблема 2)

**Files:**
- Modify: `hermes-web/static/project-workspace.html:262-265` (`formatTime`)

**Interfaces:**
- Сигнатура не меняется: `formatTime(ts)` вызывается из `renderMessages()`
  (строки 290/295) и `renderFilesTab()` (строка 363) — оба места передают
  либо число (Unix-секунды из истории Hermes или mtime-строку ISO из
  `workspace.py`), либо ISO-строку (клиентский `timestamp` при
  оптимистичной вставке в `sendMessage()`, строки 585/587). Обе формы
  должны продолжать работать после фикса.

- [ ] **Step 1: Различать число (секунды) и строку (ISO) на входе**

```javascript
// БЫЛО:
function formatTime(ts) {
  const d = new Date(ts);
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}
```

```javascript
// СТАЛО:
function formatTime(ts) {
  // Hermes отдаёт timestamp сообщений как Unix-секунды (число) — JS Date
  // ожидает миллисекунды, отсюда домножение. Клиентские метки (при
  // оптимистичной вставке в sendMessage) и mtime файлов из workspace.py —
  // уже ISO-строки, которые new Date() понимает как есть.
  const d = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
  return isNaN(d.getTime()) ? '' : d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}
```

- [ ] **Step 2: Проверить вручную**

Run: тот же локальный сервер, что в Task 1 Step 2. Открыть проект с
реальной историей из нескольких сообщений, отправленных в разное время
(или перезагрузить страницу после отправки пары сообщений с паузой).

Expected: время у разных сообщений истории различается и соответствует
реальному моменту отправки — не «одно и то же» на все сообщения. Полная
проверка на живых данных — в задаче 5.

- [ ] **Step 3: Commit**

```bash
git add hermes-web/static/project-workspace.html
git commit -m "fix(hermes-web): formatTime переводит Unix-секунды Hermes в миллисекунды"
```

---

## Task 3: Многослотовый живой рендер хода (Проблема 3)

**Files:**
- Modify: `hermes-web/static/project-workspace.html:568-645`
  (`sendMessage`, `recoverAfterStreamDrop`)

**Interfaces:**
- Consumes: SSE-события `message.started`/`assistant.delta`/
  `assistant.completed`/`error`/`done` (проксируются `handle_send_message`
  в `app.py` без изменений, см. Global Constraints), `GET
  /api/chat/{id}/messages` → `{"data": [{"role", "content", "timestamp"}]}`
  (без изменений).
- Produces: `sendMessage()` больше не принимает решения о количестве
  ответных сообщений заранее — открывает новые слоты по мере поступления
  `message.started`. `recoverAfterStreamDrop()` меняет сигнатуру: было
  `recoverAfterStreamDrop(assistantIdx)`, становится
  `recoverAfterStreamDrop()` без аргументов (перечитывает всю историю
  безусловно — см. обоснование в спеке, вариант «полная перечитка»
  выбран как более простой и надёжный, чем позиционное отслеживание
  переменного числа сообщений за ход).

- [ ] **Step 1: `sendMessage()` — открывать новый слот на каждый `message.started`, кроме первого**

```javascript
// БЫЛО (hermes-web/static/project-workspace.html):
  messages.push({ role: 'user', content: fullText, timestamp: new Date().toISOString() });
  const assistantIdx = messages.length;
  messages.push({ role: 'assistant', content: '', timestamp: new Date().toISOString() });
  renderMessages();
  clearActivity();

  try {
    const resp = await apiFetch(`/api/chat/${encodeURIComponent(chatSessionId)}/send`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: fullText }),
    });
    if (resp.status === 401) { location.href = 'login.html'; return; }
    if (!resp.ok) {
      messages[assistantIdx].content = 'Hermes временно недоступен, попробуйте ещё раз';
      renderMessages();
      return;
    }
    let streamEndedCleanly = false;
    try {
      await readSSE(resp, (name, payload) => {
        if (name === 'assistant.delta') { messages[assistantIdx].content += payload.delta || ''; renderMessages(); }
        else if (name === 'assistant.completed' && payload.content) { messages[assistantIdx].content = payload.content; renderMessages(); }
        else if (name === 'error') { messages[assistantIdx].content = `Ошибка: ${payload.message || 'неизвестная'}`; renderMessages(); }
        else if (name === 'done') { streamEndedCleanly = true; }
        else { appendActivity(name, payload); }
      });
    } catch (err) {
      streamEndedCleanly = false;
    }
    if (!streamEndedCleanly) await recoverAfterStreamDrop(assistantIdx);
    await refreshTreeAndFiles();
  } finally {
    sendBtn.disabled = false;
  }
}
```

```javascript
// СТАЛО:
  messages.push({ role: 'user', content: fullText, timestamp: new Date().toISOString() });
  let assistantIdx = messages.length;
  messages.push({ role: 'assistant', content: '', timestamp: new Date().toISOString() });
  renderMessages();
  clearActivity();

  try {
    const resp = await apiFetch(`/api/chat/${encodeURIComponent(chatSessionId)}/send`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: fullText }),
    });
    if (resp.status === 401) { location.href = 'login.html'; return; }
    if (!resp.ok) {
      messages[assistantIdx].content = 'Hermes временно недоступен, попробуйте ещё раз';
      renderMessages();
      return;
    }
    let streamEndedCleanly = false;
    let sawFirstMessage = false;
    try {
      await readSSE(resp, (name, payload) => {
        if (name === 'message.started') {
          // Один ход Hermes реально состоит из произвольного числа
          // отдельных assistant-сообщений (один на каждый шаг
          // tool-calling цикла), каждое начинается своим message.started.
          // Первое message.started относится к слоту, уже выделенному
          // выше; на каждое следующее — открываем новый слот, а не
          // дозаписываем в старый (иначе более поздний шаг перезаписывает
          // более ранний и пузырь на экране выглядит «зависшим»).
          if (sawFirstMessage) {
            assistantIdx = messages.length;
            messages.push({ role: 'assistant', content: '', timestamp: new Date().toISOString() });
            renderMessages();
          }
          sawFirstMessage = true;
        }
        else if (name === 'assistant.delta') { messages[assistantIdx].content += payload.delta || ''; renderMessages(); }
        else if (name === 'assistant.completed' && payload.content) { messages[assistantIdx].content = payload.content; renderMessages(); }
        else if (name === 'error') { messages[assistantIdx].content = `Ошибка: ${payload.message || 'неизвестная'}`; renderMessages(); }
        else if (name === 'done') { streamEndedCleanly = true; }
        else { appendActivity(name, payload); }
      });
    } catch (err) {
      streamEndedCleanly = false;
    }
    // Соединение иногда рвётся раньше, чем агент реально закончил ход (долгая
    // тихая пауза — wormsoft.ru/докер). Бэкенд продолжает работать и допишет
    // ответ в историю чата — целиком перечитываем историю вместо того, чтобы
    // гадать, сколько ещё сообщений придёт в этом ходе (см. Проблему 3 в
    // спеке — позиционное отслеживание несовместимо с переменным числом
    // сообщений за один ход).
    if (!streamEndedCleanly) await recoverAfterStreamDrop();
    await refreshTreeAndFiles();
  } finally {
    sendBtn.disabled = false;
  }
}
```

- [ ] **Step 2: `recoverAfterStreamDrop()` — перечитывать всю историю, без позиции**

```javascript
// БЫЛО:
async function recoverAfterStreamDrop(assistantIdx) {
  if (!messages[assistantIdx].content) messages[assistantIdx].content = 'Соединение прервалось, жду ответ агента…';
  renderMessages();
  const expectedCount = assistantIdx + 1;
  for (let attempt = 0; attempt < 60; attempt++) {
    await new Promise(r => setTimeout(r, 5000));
    const histResp = await apiFetch(`/api/chat/${encodeURIComponent(chatSessionId)}/messages`);
    if (!histResp.ok) continue;
    const histBody = await histResp.json();
    const fresh = histBody.data.filter(m => m.role === 'user' || m.role === 'assistant');
    if (fresh.length >= expectedCount && fresh[assistantIdx]?.role === 'assistant' && fresh[assistantIdx]?.content) {
      messages = fresh;
      renderMessages();
      return;
    }
  }
  if (messages[assistantIdx].content === 'Соединение прервалось, жду ответ агента…') {
    messages[assistantIdx].content = 'Не удалось дождаться ответа — обновите страницу позже, агент мог ещё не закончить.';
    renderMessages();
  }
}
```

```javascript
// СТАЛО:
async function recoverAfterStreamDrop() {
  const lastIdx = messages.length - 1;
  if (!messages[lastIdx].content) messages[lastIdx].content = 'Соединение прервалось, жду ответ агента…';
  renderMessages();
  // Сообщений за один ход может быть непредсказуемо много (см. Проблему 3 —
  // до 47 в реальном случае), опрашиваем историю, пока её длина не
  // перестанет расти между двумя опросами подряд — это надёжный сигнал,
  // что ход действительно завершился, без гадания о точном числе шагов.
  let previousLength = -1;
  for (let attempt = 0; attempt < 60; attempt++) {
    await new Promise(r => setTimeout(r, 5000));
    const histResp = await apiFetch(`/api/chat/${encodeURIComponent(chatSessionId)}/messages`);
    if (!histResp.ok) continue;
    const histBody = await histResp.json();
    const fresh = histBody.data.filter(m => m.role === 'user' || m.role === 'assistant');
    if (fresh.length > messages.length) {
      messages = fresh;
      renderMessages();
      previousLength = -1;
      continue;
    }
    if (fresh.length === messages.length && fresh.length === previousLength) {
      messages = fresh;
      renderMessages();
      return;
    }
    previousLength = fresh.length;
    messages = fresh;
  }
  const stillPlaceholder = messages[lastIdx] && messages[lastIdx].content === 'Соединение прервалось, жду ответ агента…';
  if (stillPlaceholder) {
    messages[lastIdx].content = 'Не удалось дождаться ответа — обновите страницу позже, агент мог ещё не закончить.';
    renderMessages();
  }
}
```

- [ ] **Step 3: Проверить вручную**

Run: тот же локальный сервер. Отправить сообщение, провоцирующее
несколько последовательных шагов агента (например «сначала вызови
terminal с echo one, потом другим отдельным вызовом echo two, потом
напиши мне итог»).

Expected: живой вид показывает каждый шаг отдельным пузырём по мере
поступления, без перезагрузки страницы; после `event: done` количество
пузырей совпадает с тем, что показывает перезагрузка страницы. Полная
проверка на реальном многошаговом ходе — в задаче 5.

- [ ] **Step 4: Commit**

```bash
git add hermes-web/static/project-workspace.html
git commit -m "fix(hermes-web): живой чат открывает новый пузырь на каждое message.started"
```

---

## Task 4: `list_tree()` показывает файлы вне `source/outer/result` (Проблема 4)

**Files:**
- Modify: `hermes-web/hermes_web/workspace.py:107-130` (`list_tree`)
- Test: `hermes-web/tests/test_workspace.py`
- Modify: `hermes-web/static/project-workspace.html` (рендер нового
  раздела дерева и вкладки «Файлы»)

**Interfaces:**
- Produces: `list_tree()` возвращает словарь с новым ключом `"misc"` —
  список записей `{"relative_path", "size", "mtime"}` в том же формате,
  что `tree["source"]`/`tree["outer"]`/`tree["result"]`, но
  `relative_path` не имеет фиксированного префикса-бакета (это может быть
  `"3-kirik-3-23-29/tasks.md"` или файл прямо в корне вроде
  `"notes.txt"`). `handle_project_tree` в `app.py` не требует изменений —
  он отдаёт результат `list_tree()` как есть (`web.json_response(tree)`).
- Consumes на фронтенде: `renderTree()`, `buildFolderTree()`,
  `renderFolderNode()`, `renderFilesTab()`, `computeFileMessageIndex()`
  (все — `project-workspace.html`).

- [ ] **Step 1: Написать падающий тест на новый ключ `misc`**

Добавить в `hermes-web/tests/test_workspace.py` (после существующих
`test_list_tree_*`, использует уже определённые в файле `_config`/
`_write_project`):

```python
def test_list_tree_surfaces_files_outside_buckets(tmp_path):
    """Проблема 4 (спек 2026-07-28): агент иногда кладёт готовые файлы в
    произвольную папку прямо в корне проекта, а не в result/ — такие файлы
    должны быть видны в дереве и доступны для скачивания, а не пропадать
    молча."""
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    stray_dir = project_dir / "3-kirik-3-23-29"
    stray_dir.mkdir()
    (stray_dir / "tasks.md").write_text("решение", encoding="utf-8")
    (project_dir / "loose.txt").write_text("прямо в корне", encoding="utf-8")

    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert sorted(f["relative_path"] for f in tree["misc"]) == [
        "3-kirik-3-23-29/tasks.md",
        "loose.txt",
    ]


def test_list_tree_misc_excludes_buckets_and_root_editable_files(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "x.txt").write_text("x", encoding="utf-8")

    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert tree["misc"] == []
```

- [ ] **Step 2: Запустить тесты, убедиться что оба падают**

Run (из `hermes-web/`):
```bash
PROJECT_INDEX_PLUGIN_DIR=../hermes-plugins \
  /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3 \
  -m pytest tests/test_workspace.py -k "test_list_tree_surfaces_files_outside_buckets or test_list_tree_misc_excludes_buckets_and_root_editable_files" -v
```
Expected: FAIL с `KeyError: 'misc'` на обоих тестах.

- [ ] **Step 3: Реализовать `misc` в `list_tree()`**

```python
# hermes-web/hermes_web/workspace.py
# БЫЛО:
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

```python
# СТАЛО:
def _list_misc(project_root: str) -> list:
    """Модель не гарантированно кладёт готовые файлы в result/ (см.
    Проблему 4 в спеке 2026-07-28) — вместо того чтобы бороться с этим
    только промптом, показываем всё, что реально лежит в корне проекта
    и не относится к source/outer/result/служебным файлам, одним
    дополнительным разделом. Точечные скрытые файлы (начинающиеся с '.')
    пропускаем — это не то, что кладёт туда агент или пользователь."""
    skip_names = set(BUCKETS) | set(ROOT_EDITABLE_FILES)
    entries = []
    for entry_name in os.listdir(project_root):
        if entry_name in skip_names or entry_name.startswith('.'):
            continue
        full = os.path.join(project_root, entry_name)
        if os.path.isfile(full):
            entries.append({
                "relative_path": entry_name,
                "size": os.path.getsize(full),
                "mtime": _iso_mtime(full),
            })
        elif os.path.isdir(full):
            for dirpath, _dirnames, filenames in os.walk(full):
                for filename in filenames:
                    fpath = os.path.join(dirpath, filename)
                    entries.append({
                        "relative_path": os.path.relpath(fpath, project_root),
                        "size": os.path.getsize(fpath),
                        "mtime": _iso_mtime(fpath),
                    })
    return sorted(entries, key=lambda e: e["relative_path"])


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
    tree["misc"] = _list_misc(project_root)
    return tree
```

- [ ] **Step 4: Запустить тесты, убедиться что весь пакет проходит**

Run (из `hermes-web/`):
```bash
PROJECT_INDEX_PLUGIN_DIR=../hermes-plugins \
  /tmp/claude-1000/-home-deploy-hermes-cn-ru/333f04b6-c842-486b-85fa-2a0095a11d44/scratchpad/hermes-web-venv/bin/python3 \
  -m pytest tests/ -q
```
Expected: PASS (весь пакет — 213 существующих + 2 новых = 215, ни один
старый тест не сломан).

- [ ] **Step 5: Отрисовать раздел «misc» на фронтенде**

`hermes-web/static/project-workspace.html` — добавить CSS-переменную
цвета (в `:root`, рядом с `--c-source`/`--c-outer`/`--c-result`):

```css
/* БЫЛО: */
    --c-source:#ad9fe6; --c-outer:#7fc4b2; --c-result:#f0bb5c;
```
```css
/* СТАЛО: */
    --c-source:#ad9fe6; --c-outer:#7fc4b2; --c-result:#f0bb5c; --c-misc:#8b93bf;
```

И правило для иконки папки (рядом с `.node.folder-result`):
```css
/* добавить после .node.folder-result{...} */
  .node.folder-misc .ic{color:var(--c-misc)}
```

`renderFolderNode()` — не рисовать кнопку «＋» для `misc` (backend
всё равно отклонит `mkdir` вне `source/outer/result` через
`_require_within_bucket`, показывать нерабочую кнопку — плохой UX):

```javascript
// БЫЛО:
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
```

```javascript
// СТАЛО:
function renderFolderNode(node, bucketClass, depth) {
  let html = '';
  const canCreate = bucketClass !== 'misc';
  Object.keys(node.folders).sort().forEach(name => {
    const child = node.folders[name];
    html += `<div class="node folder-${bucketClass}" style="padding-left:${depth * 14}px">
      <span class="ic">📁</span><span class="name">${escapeHtml(name)}</span>
      ${canCreate ? `<button class="new-folder-btn" data-parent="${escapeHtml(child.path)}" title="новая папка">＋</button>` : ''}
    </div>`;
    html += renderFolderNode(child, bucketClass, depth + 1);
  });
```

`buildFolderTree()` — текущая версия предполагает единый префикс-бакет
на все записи (`parts.slice(1)`), что для `misc` неверно (у записей
`misc` разные топ-уровневые папки, а не общий `"misc"`). Добавить
отдельную функцию для misc, не трогая существующую `buildFolderTree`
(она остаётся как есть для `source`/`outer`/`result`):

```javascript
// добавить после buildFolderTree(entries, bucket) { ... }
function buildMiscTree(entries) {
  const root = { folders: {}, files: [], path: 'misc' };
  for (const entry of entries) {
    const parts = entry.relative_path.split('/');
    let node = root, accPath = 'misc';
    for (let i = 0; i < parts.length - 1; i++) {
      accPath += '/' + parts[i];
      if (!node.folders[parts[i]]) node.folders[parts[i]] = { folders: {}, files: [], path: accPath };
      node = node.folders[parts[i]];
    }
    node.files.push({ name: parts[parts.length - 1], entry });
  }
  return root;
}
```

`renderTree()` — добавить секцию `misc` после цикла по `source/outer/result`:

```javascript
// БЫЛО (конец renderTree, после forEach по bucket):
  ['source', 'outer', 'result'].forEach(bucket => {
    html += `<div class="glabel">${labels[bucket]}<button class="new-folder-btn" data-parent="${bucket}" title="новая папка">＋папка</button></div>`;
    html += renderFolderNode(buildFolderTree(tree[bucket] || [], bucket), bucket, 0);
  });

  document.getElementById('tree').innerHTML = html;
```

```javascript
// СТАЛО:
  ['source', 'outer', 'result'].forEach(bucket => {
    html += `<div class="glabel">${labels[bucket]}<button class="new-folder-btn" data-parent="${bucket}" title="новая папка">＋папка</button></div>`;
    html += renderFolderNode(buildFolderTree(tree[bucket] || [], bucket), bucket, 0);
  });

  if ((tree.misc || []).length) {
    // Файлы, которые модель положила мимо source/outer/result (см.
    // Проблему 4, спек 2026-07-28) — показываем как есть, без попытки
    // угадать, куда их "следовало" положить.
    html += `<div class="glabel">🗂 остальное — вне source/outer/result</div>`;
    html += renderFolderNode(buildMiscTree(tree.misc), 'misc', 0);
  }

  document.getElementById('tree').innerHTML = html;
```

`renderFilesTab()` — включить `misc` в общий список строк вкладки
«Файлы» и в легенду:

```javascript
// БЫЛО:
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
```

```javascript
// СТАЛО:
function renderFilesTab(tree, fileIndex) {
  const rows = [];
  (tree.root_files || []).forEach(f => rows.push({ relative_path: f.name, bucket: 'root', size: f.size, mtime: f.mtime }));
  ['source', 'outer', 'result', 'misc'].forEach(bucket => (tree[bucket] || []).forEach(f => rows.push({ ...f, bucket })));
  rows.sort((a, b) => (a.mtime < b.mtime ? 1 : -1));

  const legend = `<div class="legend">
    <span><span class="sw" style="background:var(--c-source)"></span>source</span>
    <span><span class="sw" style="background:var(--c-outer)"></span>outer</span>
    <span><span class="sw" style="background:var(--c-result)"></span>result</span>
    <span><span class="sw" style="background:var(--c-misc)"></span>вне бакетов</span>
  </div>`;
```

`computeFileMessageIndex()` — включить `misc` в бакеты, для которых
ищем ближайшее следующее сообщение ассистента (та же логика, что уже
есть для `outer`/`result` — misc-файлы тоже создаёт агент, не
пользователь):

```javascript
// БЫЛО:
  const nearest = {};
  ['outer', 'result'].forEach(bucket => {
```

```javascript
// СТАЛО:
  const nearest = {};
  ['outer', 'result', 'misc'].forEach(bucket => {
```

- [ ] **Step 6: Проверить вручную**

Run: тот же локальный сервер (или прямо задача 5 на реальном). Создать
файл в проекте вне `source/outer/result` (например через `terminal`
агента: `mkdir -p /workspace/<project>/misc-test && echo hi >
/workspace/<project>/misc-test/note.txt`, либо руками в файловой системе
для локальной проверки).

Expected: раздел «🗂 остальное» появляется в дереве слева, файл виден и
скачивается по клику; во вкладке «Файлы» строка попадает в общий список с
меткой «вне бакетов»; кнопки «＋» на папках этого раздела нет.

- [ ] **Step 7: Commit**

```bash
git add hermes-web/hermes_web/workspace.py hermes-web/tests/test_workspace.py hermes-web/static/project-workspace.html
git commit -m "feat(hermes-web): list_tree показывает файлы вне source/outer/result"
```

---

## Task 5: Живая приёмочная проверка всех 4 фиксов на реальном сервере

**Files:** нет изменений кода — только проверка задеплоенного результата.

**Interfaces:**
- Consumes: развёрнутую на VPS ветку (после слияния и деплоя, см.
  `superpowers:finishing-a-development-branch` — этот таск предполагает,
  что деплой уже произошёл per обычный порядок этого проекта: смотри
  `docs/state.md` про предыдущие срезы).

- [ ] **Step 1: Завести одноразовый `qa_temp`-аккаунт**

Тем же способом, что и в предыдущих срезах (см. `docs/state.md`,
приёмочные тесты срезов 3.1/3.2) — создать временного пользователя,
провести проверку, удалить сразу после.

- [ ] **Step 2: Проверить Проблему 1 (пустые пузыри)**

Попросить агента вызвать инструмент без комментария (например
«выполни в терминале `echo test`, ничего не объясняя»).

Expected: в ленте нет пустой тёмной капсулы между репликами.

- [ ] **Step 3: Проверить Проблему 2 (время)**

Отправить 2-3 сообщения с паузами, перезагрузить страницу.

Expected: время у сообщений в истории различается и соответствует
реальному моменту отправки.

- [ ] **Step 4: Проверить Проблему 3 (многошаговый ход без перезагрузки)**

Попросить агента выполнить несколько независимых шагов подряд одним
запросом (по образцу реального инцидента — «переведи каждую задачу из
скана по одной, отдельным сообщением на каждую»).

Expected: живой вид показывает каждый шаг отдельным пузырём по мере
поступления, без ручной перезагрузки страницы; итоговое число пузырей
после `event: done` совпадает с тем, что покажет перезагрузка.

- [ ] **Step 5: Проверить Проблему 4 (файл вне бакетов)**

Попросить агента создать файл в произвольной папке в корне проекта, не
в `result/` (например «сохрани файл в папке `misc-test/` в корне
проекта, не в result»).

Expected: файл появляется в разделе «🗂 остальное» дерева и во вкладке
«Файлы», скачивается по клику.

- [ ] **Step 6: Удалить `qa_temp`, обновить `docs/state.md`/`docs/changelog.md`**

Отметить все 4 фикса как выкаченные и проверенные живьём, с датой и
кратким описанием способа проверки (по образцу предыдущих записей
`changelog.md`). Снимок в git: `bash scripts/snapshot.sh "4 фикса живого
чата рабочего экрана проекта — выкачены и проверены живьём"`.

---

## Self-Review (для исполняющего план)

- Покрытие спека: Проблема 1 → Task 1, Проблема 2 → Task 2, Проблема 3 →
  Task 3, Проблема 4 → Task 4. Раздел «Тестирование» спека → Task 4
  Step 1-4 (Python TDD) + Task 5 (ручная приёмка всех 4).
- `chat.html` умышленно не входит ни в одну задачу (см. Global
  Constraints и спек).
- Пятая задача — не код, а обязательный приёмочный проход; без неё
  JS-фиксы (задачи 1-3) не имеют собственного автоматического теста и
  формально не подтверждены на реальных данных Hermes (только руками
  разработчика локально на шагах 1-3 каждой задачи).
