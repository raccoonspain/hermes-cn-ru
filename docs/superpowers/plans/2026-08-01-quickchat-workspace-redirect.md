# Быстрый чат → project-workspace.html Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Плитка «Быстрый чат» на `home.html` должна открывать только что
созданный проект в полноценном `project-workspace.html` (дерево файлов,
чат, работа с вложениями), а не в устаревшем минимальном `chat.html`
(голый тред без файлового дерева) — и убрать `chat.html` из кодовой базы
как мёртвый код.

**Architecture:** Чисто фронтенд-правка одной строки редиректа плюс
удаление файла. `POST /api/quick-chat` уже возвращает `project_path`
готового к работе проекта (с `about.md`, папками `source/outer/result`).
`project-workspace.html` уже умеет открыть любой проект по одному `path`
в query-строке — сам вызывает `POST /api/projects/open`, которая через
`get_or_open_session` находит уже существующую чат-сессию для этого пути
(созданную `create_quick_chat` на предыдущем шаге) и переиспользует её, не
плодя вторую сессию. Никаких изменений бэкенда не требуется — только
редирект и чистка мёртвого кода на фронтенде + два комментария, которые
на него ссылались.

**Tech Stack:** Vanilla JS/HTML (без сборщика), aiohttp-бэкенд (не
меняется). Фронтенд без тестового фреймворка — верификация синтаксиса
через `node --check` / `node -e "new Function(...)"`, как заведено в
проекте.

## Global Constraints

- Никакого нового бэкенд-кода и новых API-эндпоинтов — `/api/quick-chat`
  и `/api/projects/open` уже делают всё нужное, план их не трогает.
- `chat.html` удаляется целиком; всё, что на него ссылалось (комментарии
  в `app.js` и `hermes_web/app.py`), обновляется, чтобы не врать про
  несуществующий файл.
- Бэкенд-тестовый набор должен остаться зелёным как есть (77 тестов
  `hermes-plugins`, 248 тестов `hermes-web` на момент написания плана) —
  эта правка не меняет ни одной строки бэкенд-логики, только докстринг-
  комментарий в `app.py`, так что новых тестов не требуется и падать
  ничего не должно.

---

### Task 1: Переключить редирект «Быстрого чата» и удалить `chat.html`

**Files:**
- Modify: `hermes-web/static/home.html:112-124` (обработчик клика по
  `quickChatTile`)
- Modify: `hermes-web/static/app.js:1` (комментарий про общие хелперы)
- Modify: `hermes-web/hermes_web/app.py:1-5` (докстринг модуля)
- Delete: `hermes-web/static/chat.html`

**Interfaces:**
- Consumes: `POST /api/quick-chat` (уже существует, не меняется) —
  возвращает `{chat_session_id: string, project_path: string}`.
  `project-workspace.html` (уже существует, не меняется) — принимает
  `?path=<project_path>` в query-строке, сам вызывает
  `POST /api/projects/open` и дальше работает самостоятельно.
- Produces: ничего нового — задача только меняет строку редиректа и
  убирает мёртвый файл.

- [ ] **Step 1: Заменить обработчик клика в `home.html`**

Текущий код (`hermes-web/static/home.html:112-124`):

```js
document.getElementById('quickChatTile').addEventListener('click', async (e) => {
  e.preventDefault();
  try {
    const resp = await apiFetch('/api/quick-chat', { method: 'POST' });
    if (resp.status === 401) { location.href = 'login.html'; return; }
    if (!resp.ok) { alert('Не удалось начать чат — попробуйте ещё раз'); return; }
    const body = await resp.json();
    const params = new URLSearchParams({ id: body.chat_session_id, path: body.project_path || '' });
    location.href = `chat.html?${params.toString()}`;
  } catch (err) {
    alert('Hermes временно недоступен, попробуйте ещё раз');
  }
});
```

Замени на:

```js
document.getElementById('quickChatTile').addEventListener('click', async (e) => {
  e.preventDefault();
  try {
    const resp = await apiFetch('/api/quick-chat', { method: 'POST' });
    if (resp.status === 401) { location.href = 'login.html'; return; }
    if (!resp.ok) { alert('Не удалось начать чат — попробуйте ещё раз'); return; }
    const body = await resp.json();
    location.href = `project-workspace.html?path=${encodeURIComponent(body.project_path)}`;
  } catch (err) {
    alert('Hermes временно недоступен, попробуйте ещё раз');
  }
});
```

`project_path` всегда непустой при `resp.ok` (это гарантирует
`create_quick_chat` — см. `hermes_web/quickchat.py:203-239`, там нет пути
без записанного `project_path`), поэтому `|| ''`-фолбэк из старого кода
и промежуточный `params`-объект больше не нужны.

- [ ] **Step 2: Проверить синтаксис `home.html` после правки**

Run:

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('hermes-web/static/home.html', 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
for (const s of scripts) new Function(s);
console.log('OK: ' + scripts.length + ' inline script(s) parsed');
"
```

Expected: `OK: 1 inline script(s) parsed` (без исключений).

- [ ] **Step 3: Удалить `chat.html`**

```bash
rm hermes-web/static/chat.html
```

- [ ] **Step 4: Обновить комментарий в `app.js`**

Текущая первая строка (`hermes-web/static/app.js:1`):

```js
// Общие хелперы для login.html/home.html/chat.html — без сборщика, обычный <script src="app.js">.
```

Замени на:

```js
// Общие хелперы для login.html/home.html/project-selector.html/project-workspace.html — без сборщика, обычный <script src="app.js">.
```

- [ ] **Step 5: Обновить докстринг модуля в `hermes_web/app.py`**

Текущие строки (`hermes-web/hermes_web/app.py:1-5`):

```python
"""aiohttp web application: login/logout, /api/me, quick-chat, chat send/history,
плюс раздача статики. Неавторизованные HTML-страницы (login.html/home.html/
chat.html) отдаются как обычные статические файлы — секретов в них нет,
авторизация проверяется на уровне API (/api/me и т.д.), а фронтенд сам
редиректит на /login.html при 401 (см. static-JS в Task 7)."""
```

Замени на:

```python
"""aiohttp web application: login/logout, /api/me, quick-chat, chat send/history,
плюс раздача статики. Неавторизованные HTML-страницы (login.html/home.html/
project-workspace.html) отдаются как обычные статические файлы — секретов
в них нет, авторизация проверяется на уровне API (/api/me и т.д.), а
фронтенд сам редиректит на /login.html при 401 (см. static-JS в Task 7)."""
```

- [ ] **Step 6: Убедиться, что нигде больше не осталось ссылок на `chat.html`**

Run:

```bash
grep -rn "chat.html" hermes-web/ --include="*.py" --include="*.html" --include="*.js"
```

Expected: пустой вывод (ничего не найдено).

- [ ] **Step 7: Прогнать бэкенд-тесты — убедиться, что ничего не сломано**

Run (из `hermes-web/`, с активным venv, `PYTHONPATH` указывает на
`hermes-plugins`):

```bash
python -m pytest tests/ -v
```

Expected: `248 passed` (тот же счёт, что и до правки — эта задача не
меняет бэкенд-логику).

- [ ] **Step 8: Commit**

```bash
git add hermes-web/static/home.html hermes-web/static/app.js hermes-web/hermes_web/app.py
git rm hermes-web/static/chat.html
git commit -m "feat(hermes-web): переключить «Быстрый чат» на project-workspace.html, убрать chat.html"
```
