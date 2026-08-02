# Раскладка рабочего экрана: раздвижная панель редактора вместо модалки — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить модальный редактор `.md`/`.txt` файлов раздвижной панелью
между деревом и чатом; дерево и боковая панель получают ручной resize и
сворачивание — всё по единому спеку Группы D бэклога живого тестирования.

**Architecture:** Один файл, `hermes-web/static/project-workspace.html`
(vanilla HTML/CSS/JS, без сборщика — как весь фронтенд проекта). Раскладка
меняется с CSS Grid на Flexbox-строку `.body-row` с переменным числом
видимых колонок. Два новых JS-хелпера (`makeResizable`, `collapsePane`)
покрывают resize/collapse для трёх панелей (дерево, редактор, боковая).
Бэкенд не меняется — оба используемых эндпоинта (`GET`/`POST
/api/projects/file`) уже существуют.

**Tech Stack:** Vanilla JS/HTML/CSS, `localStorage` для персистентности
раскладки. Никаких новых зависимостей.

## Global Constraints

- Без сборщика и новых npm-зависимостей — тот же vanilla JS, что и весь
  фронтенд проекта (спек, раздел «Архитектура»).
- Границы ширины колонок: дерево 140–360px, редактор 220–560px, боковая
  панель 180–420px (спек, раздел «Сохранение состояния раскладки»).
- Ключи `localStorage` — глобальные (без префикса пути проекта):
  `hermes.workspace.treeWidth`, `hermes.workspace.sideWidth`,
  `hermes.workspace.editorWidth`, `hermes.workspace.treeCollapsed`,
  `hermes.workspace.sideCollapsed`. Состояние «открыт/закрыт» редактора не
  персистится — редактор всегда закрыт при заходе в проект.
- Номера строк, подсветка синтаксиса, вкладки нескольких файлов,
  адаптивная/мобильная раскладка — вне объёма (спек, раздел «Что не
  делаем»).
- В репозитории нет JS-тестового фреймворка для фронтенда (та же ситуация,
  что у предыдущих срезов B/A/C) — верификация по ходу: `node --check` на
  извлечённый inline-скрипт; финальная приёмка — ручная, на живом сервере.

---

## Файловая карта

Единственный файл, который меняется во всех задачах:
`hermes-web/static/project-workspace.html`.

- **CSS** (`<style>`, строки ~7–125 в текущей версии) — переезд с Grid на
  Flexbox, новые классы `.body-row`, `.tree-pane`, `.editor-pane`,
  `.drag-handle`, `.layout-toggle-btn`, `.topbar-spacer`.
- **HTML** (`<body>`, строки ~127–176) — `.tree`/`.overlay+.editor`/`.side`
  оборачиваются в `.body-row`; новая `.editor-pane` заменяет `.overlay`;
  дерево получает id `treePane`-обёртку и `#treeHandle`; боковая панель
  получает `#sideHandle`; топбар получает две кнопки сворачивания.
- **JS** (`<script>`, строки ~179 и далее) — новые функции
  `makeResizable`, `collapsePane`, `initLayout`, `showEditorPane`,
  `closeEditorPane`, `attemptCloseEditor`; переписанные `openEditor`,
  `saveEditor`; новые переменные `currentEditorFile`, `editorDirty`.

Backend не меняется — оба эндпоинта (`GET`/`POST /api/projects/file`) уже
реализованы и покрывают всё, что нужно этому срезу.

---

### Task 1: Разметка — Flexbox-скелет раскладки, модалка → инлайн-панель (без resize/collapse/dirty-tracking)

**Files:**
- Modify: `hermes-web/static/project-workspace.html`

**Interfaces:**
- Consumes: существующие `apiFetch`, `projectPath`, `refreshTreeAndFiles`
  — без изменений сигнатур.
- Produces: `showEditorPane()`, `closeEditorPane()` — обе без аргументов,
  используются в Task 2 (обновляется `showEditorPane`) и Task 3
  (заворачивается в `attemptCloseEditor`). Новые id в разметке:
  `#treePane`, `#treeHandle`, `#editorPane`, `#editorHandle`,
  `#editorCloseXBtn`, `#cancelEditorBtn`, `#sideHandle`, `#toggleTreeBtn`,
  `#toggleSideBtn` — потребляются в Task 2.

Один связанный срез: CSS и HTML меняются вместе, потому что раскладка не
имеет смысла без соответствующей разметки, а JS-обвязка редактора должна
сразу указывать на новые элементы (иначе получим синтаксически валидный,
но фактически сломанный промежуточный файл).

- [ ] **Step 1: CSS — заменить grid-раскладку `body`/`.topbar` на flexbox**

В `<style>` найти блок (строки 16–31):

```css
  body{
    background:var(--sky); color:var(--text);
    font-family:Georgia,"Iowan Old Style",serif;
    height:100vh; display:grid;
    grid-template-columns:260px 1fr 360px;
    grid-template-rows:56px 1fr;
    grid-template-areas:"top top top" "tree chat side";
  }
  .topbar{
    grid-area:top; border-bottom:1px solid var(--panel-line);
    display:flex; align-items:center; gap:14px; padding:0 20px;
    font-family:ui-monospace,Consolas,monospace; font-size:12.5px; color:var(--text-dim);
  }
  .topbar a{color:var(--text-dim); text-decoration:none}
  .topbar a:hover{color:var(--gold)}
  .topbar .title{color:var(--text); font-family:Georgia,serif; font-size:14.5px; font-style:italic; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:600px}
```

Заменить на:

```css
  body{
    background:var(--sky); color:var(--text);
    font-family:Georgia,"Iowan Old Style",serif;
    height:100vh; display:flex; flex-direction:column;
  }
  .topbar{
    border-bottom:1px solid var(--panel-line); flex-shrink:0; height:56px;
    display:flex; align-items:center; gap:14px; padding:0 20px;
    font-family:ui-monospace,Consolas,monospace; font-size:12.5px; color:var(--text-dim);
  }
  .topbar a{color:var(--text-dim); text-decoration:none}
  .topbar a:hover{color:var(--gold)}
  .topbar .title{color:var(--text); font-family:Georgia,serif; font-size:14.5px; font-style:italic; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:600px}
  .topbar-spacer{flex:1}
  .layout-toggle-btn{background:none;border:1px solid var(--panel-line);color:var(--text-dim);border-radius:6px;font-family:inherit;font-size:11.5px;padding:4px 9px;cursor:pointer}
  .layout-toggle-btn:hover{color:var(--text);border-color:var(--gold)}

  .body-row{flex:1; display:flex; min-height:0}
  .drag-handle{position:absolute; top:0; bottom:0; width:6px; cursor:col-resize; z-index:5}
  .drag-handle:hover, .drag-handle.dragging{background:var(--gold)}
```

- [ ] **Step 2: CSS — `.tree` → `.tree-pane` + `.tree`**

Найти:

```css
  .tree{grid-area:tree; border-right:1px solid var(--panel-line); padding:18px 14px; overflow-y:auto}
```

Заменить на:

```css
  .tree-pane{position:relative; width:260px; flex-shrink:0; display:flex; flex-direction:column; border-right:1px solid var(--panel-line)}
  .tree-pane .drag-handle{right:-3px}
  .tree{flex:1; padding:18px 14px; overflow-y:auto}
```

(Остальные `.tree .glabel`/`.node`/... правила ниже по файлу не трогаем —
они по-прежнему адресуют `.tree`, а `#tree` остаётся тем же элементом,
просто теперь вложенным в `.tree-pane`.)

- [ ] **Step 3: CSS — `.chat` теряет `grid-area`, получает `min-width:0`**

Найти:

```css
  .chat{grid-area:chat; display:flex; flex-direction:column; min-height:0}
```

Заменить на:

```css
  .chat{flex:1; min-width:0; display:flex; flex-direction:column; min-height:0}
```

(`min-width:0` обязателен — без него flex-элемент с длинным текстом внутри
не сжимается меньше содержимого, и `.chat` будет распирать `.body-row`
вместо того, чтобы уступать место открытой `.editor-pane`.)

- [ ] **Step 4: CSS — `.side` теряет `grid-area`, получает якорь для хендла**

Найти:

```css
  .side{grid-area:side; border-left:1px solid var(--panel-line); display:flex; flex-direction:column; min-height:0}
```

Заменить на:

```css
  .side{position:relative; width:360px; flex-shrink:0; border-left:1px solid var(--panel-line); display:flex; flex-direction:column; min-height:0}
  .side .drag-handle{left:-3px}
```

- [ ] **Step 5: CSS — `.overlay`/`.editor` (модалка) → `.editor-pane` (инлайн-панель)**

Найти блок:

```css
  .overlay{position:fixed;inset:0;background:rgba(6,8,16,.7);display:none;align-items:center;justify-content:center;z-index:10}
  .overlay.on{display:flex}
  .editor{width:640px;max-width:90vw;background:var(--panel);border:1px solid var(--panel-line);border-radius:12px;overflow:hidden}
  .editor-head{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid var(--panel-line);font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--text-dim)}
  .editor textarea{width:100%;height:340px;background:var(--sky-deep);color:var(--text);border:none;outline:none;padding:16px;font-family:ui-monospace,Consolas,monospace;font-size:12.5px;line-height:1.6;resize:none}
  .editor-foot{display:flex;justify-content:flex-end;gap:8px;padding:12px 16px;border-top:1px solid var(--panel-line)}
  .editor-foot button{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;padding:8px 14px;border-radius:8px;cursor:pointer}
```

Заменить на:

```css
  .editor-pane{position:relative; width:320px; flex-shrink:0; display:none; flex-direction:column; border-right:1px solid var(--panel-line); background:var(--panel)}
  .editor-pane .drag-handle{right:-3px}
  .editor-head{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;border-bottom:1px solid var(--panel-line);font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--text-dim)}
  .editor-head .x-btn{background:none;border:1px solid var(--panel-line);color:var(--text-dim);width:22px;height:22px;border-radius:6px;cursor:pointer;font-size:12px;line-height:1}
  .editor-head .x-btn:hover{color:var(--text);border-color:var(--gold)}
  .editor-pane textarea{flex:1;background:var(--sky-deep);color:var(--text);border:none;outline:none;padding:16px;font-family:ui-monospace,Consolas,monospace;font-size:12.5px;line-height:1.6;resize:none}
  .editor-foot{display:flex;justify-content:flex-end;gap:8px;padding:12px 16px;border-top:1px solid var(--panel-line)}
  .editor-foot button{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;padding:8px 14px;border-radius:8px;cursor:pointer}
```

- [ ] **Step 6: HTML — тело страницы: `.body-row`, `.tree-pane`, `.editor-pane`, `#side`**

Найти блок (от `<div class="topbar">` до закрывающего `.overlay`):

```html
<div class="topbar">
  <a href="home.html" title="на главную">🏠</a>
  <a href="project-selector.html">← к проектам</a>
  <span class="title" id="projectTitle">Загрузка…</span>
</div>

<div class="tree" id="tree"></div>

<div class="chat">
  <div class="messages" id="messages"></div>
  <div class="composer">
    <div class="compose-attachments" id="composeAttachments"></div>
    <div class="upload-target-row">
      <span>папка для вложений:</span>
      <select id="uploadTargetSelect"></select>
    </div>
    <div class="upload-target-row">
      <span>папка для результата:</span>
      <select id="resultTargetSelect"></select>
    </div>
    <div class="compose-box">
      <button class="icon-btn" id="attachBtn" title="прикрепить файлы">📎</button>
      <textarea id="composeInput" rows="1" placeholder="Написать Hermes… (Ctrl+V — вставить изображение из буфера)"></textarea>
      <button class="send-btn" id="sendBtn" title="отправить">➤</button>
    </div>
    <input type="file" id="fileInput" multiple style="display:none">
  </div>
</div>

<div class="side">
  <div class="side-tabs">
    <button class="on" data-tab="activity">Активность агента</button>
    <button data-tab="files">Файлы</button>
  </div>
  <div class="side-pane on" id="pane-activity"></div>
  <div class="side-pane" id="pane-files"></div>
</div>

<div class="overlay" id="overlay">
  <div class="editor">
    <div class="editor-head"><span id="editorName"></span><span>txt/md редактор</span></div>
    <textarea id="editorText"></textarea>
    <div class="editor-foot">
      <button class="icon-btn" id="closeEditorBtn">Закрыть</button>
      <button class="send-btn" id="saveEditorBtn" style="width:auto;padding:0 16px">Сохранить</button>
    </div>
  </div>
</div>
```

Заменить на:

```html
<div class="topbar">
  <a href="home.html" title="на главную">🏠</a>
  <a href="project-selector.html">← к проектам</a>
  <span class="title" id="projectTitle">Загрузка…</span>
  <span class="topbar-spacer"></span>
  <button class="layout-toggle-btn" id="toggleTreeBtn" title="свернуть/развернуть дерево файлов">🌲 дерево</button>
  <button class="layout-toggle-btn" id="toggleSideBtn" title="свернуть/развернуть боковую панель">🗂 панель</button>
</div>

<div class="body-row">
  <div class="tree-pane" id="treePane">
    <div class="tree" id="tree"></div>
    <div class="drag-handle" id="treeHandle"></div>
  </div>

  <div class="editor-pane" id="editorPane">
    <div class="editor-head">
      <span id="editorName"></span>
      <button class="x-btn" id="editorCloseXBtn" title="закрыть">✕</button>
    </div>
    <textarea id="editorText"></textarea>
    <div class="editor-foot">
      <button class="icon-btn" id="cancelEditorBtn">Отменить</button>
      <button class="send-btn" id="saveEditorBtn" style="width:auto;padding:0 16px">Сохранить</button>
    </div>
    <div class="drag-handle" id="editorHandle"></div>
  </div>

  <div class="chat">
    <div class="messages" id="messages"></div>
    <div class="composer">
      <div class="compose-attachments" id="composeAttachments"></div>
      <div class="upload-target-row">
        <span>папка для вложений:</span>
        <select id="uploadTargetSelect"></select>
      </div>
      <div class="upload-target-row">
        <span>папка для результата:</span>
        <select id="resultTargetSelect"></select>
      </div>
      <div class="compose-box">
        <button class="icon-btn" id="attachBtn" title="прикрепить файлы">📎</button>
        <textarea id="composeInput" rows="1" placeholder="Написать Hermes… (Ctrl+V — вставить изображение из буфера)"></textarea>
        <button class="send-btn" id="sendBtn" title="отправить">➤</button>
      </div>
      <input type="file" id="fileInput" multiple style="display:none">
    </div>
  </div>

  <div class="side" id="side">
    <div class="drag-handle" id="sideHandle"></div>
    <div class="side-tabs">
      <button class="on" data-tab="activity">Активность агента</button>
      <button data-tab="files">Файлы</button>
    </div>
    <div class="side-pane on" id="pane-activity"></div>
    <div class="side-pane" id="pane-files"></div>
  </div>
</div>
```

- [ ] **Step 7: JS — `openEditor`/`saveEditor` указывают на `#editorPane` вместо `#overlay`**

Найти:

```js
async function openEditor(relpath) {
  const resp = await apiFetch('/api/projects/file?' + new URLSearchParams({ path: projectPath, file: relpath }));
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) { alert('Не удалось открыть файл'); return; }
  document.getElementById('editorName').textContent = relpath;
  document.getElementById('editorText').value = await resp.text();
  document.getElementById('overlay').classList.add('on');
  document.getElementById('saveEditorBtn').onclick = () => saveEditor(relpath);
}

async function saveEditor(relpath) {
  const content = document.getElementById('editorText').value;
  const resp = await apiFetch('/api/projects/file', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: projectPath, file: relpath, content }),
  });
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    alert('Не удалось сохранить: ' + (body.error || resp.status));
    return;
  }
  document.getElementById('overlay').classList.remove('on');
  await refreshTreeAndFiles();
}
```

Заменить на:

```js
function showEditorPane() {
  document.getElementById('editorPane').style.display = 'flex';
}

function closeEditorPane() {
  document.getElementById('editorPane').style.display = 'none';
}

async function openEditor(relpath) {
  const resp = await apiFetch('/api/projects/file?' + new URLSearchParams({ path: projectPath, file: relpath }));
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) { alert('Не удалось открыть файл'); return; }
  document.getElementById('editorName').textContent = relpath;
  document.getElementById('editorText').value = await resp.text();
  showEditorPane();
  document.getElementById('saveEditorBtn').onclick = () => saveEditor(relpath);
}

async function saveEditor(relpath) {
  const content = document.getElementById('editorText').value;
  const resp = await apiFetch('/api/projects/file', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: projectPath, file: relpath, content }),
  });
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    alert('Не удалось сохранить: ' + (body.error || resp.status));
    return;
  }
  await refreshTreeAndFiles();
}
```

Обратите внимание: строка `document.getElementById('overlay').classList.remove('on');`
из `saveEditor` **не переносится** — панель теперь остаётся открытой после
сохранения (явное требование спека, раздел «Взаимодействие»).

- [ ] **Step 8: JS — перевесить обработчик закрытия на новые кнопки**

Найти:

```js
document.getElementById('closeEditorBtn').addEventListener('click', () => document.getElementById('overlay').classList.remove('on'));
```

Заменить на:

```js
document.getElementById('editorCloseXBtn').addEventListener('click', closeEditorPane);
document.getElementById('cancelEditorBtn').addEventListener('click', closeEditorPane);
```

- [ ] **Step 9: Проверить синтаксис**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('hermes-web/static/project-workspace.html', 'utf8');
const match = html.match(/<script>([\s\S]*?)<\/script>/);
fs.writeFileSync('/tmp/project-workspace-inline.js', match[1]);
"
node --check /tmp/project-workspace-inline.js
```

Expected: без вывода (успех). Дополнительно:

```bash
grep -n "overlay\|closeEditorBtn\|grid-area" hermes-web/static/project-workspace.html
```

Expected: пусто (все три термина полностью выведены из файла).

- [ ] **Step 10: Commit**

```bash
git add hermes-web/static/project-workspace.html
git commit -m "feat(hermes-web): раскладка рабочего экрана — Flexbox-скелет, модалка редактора заменена инлайн-панелью (без resize/collapse, Группа D шаг 1)"
```

---

### Task 2: Resize + collapse — `makeResizable`/`collapsePane`, drag-хендлы, кнопки сворачивания в топбаре

**Files:**
- Modify: `hermes-web/static/project-workspace.html`

**Interfaces:**
- Consumes: `#treePane`, `#treeHandle`, `#editorPane`, `#editorHandle`,
  `#side`, `#sideHandle`, `#toggleTreeBtn`, `#toggleSideBtn` (Task 1),
  `showEditorPane()` (Task 1, эта задача её модифицирует).
- Produces: `makeResizable(handleEl, paneEl, {min, max, storageKey,
  invert})`, `collapsePane(btnEl, paneEl, {storageKey})`, `initLayout()` —
  ничем из этого дальнейшие задачи не пользуются напрямую (терминальная
  для этой части), но `showEditorPane()` в изменённом виде используется
  в Task 3.

- [ ] **Step 1: Добавить `makeResizable`, `collapsePane`, `initLayout`**

Найти конец блока переключения вкладок боковой панели:

```js
document.querySelectorAll('.side-tabs button').forEach(b => {
  b.addEventListener('click', () => {
    document.querySelectorAll('.side-tabs button').forEach(x => x.classList.remove('on'));
    document.querySelectorAll('.side-pane').forEach(x => x.classList.remove('on'));
    b.classList.add('on');
    document.getElementById('pane-' + b.dataset.tab).classList.add('on');
  });
});
```

Сразу после него добавить:

```js
function makeResizable(handleEl, paneEl, { min, max, storageKey, invert }) {
  let dragging = false, startX = 0, startWidth = 0;
  function onMove(e) {
    if (!dragging) return;
    const delta = (e.clientX - startX) * (invert ? -1 : 1);
    paneEl.style.width = Math.min(max, Math.max(min, startWidth + delta)) + 'px';
  }
  function onUp() {
    if (!dragging) return;
    dragging = false;
    handleEl.classList.remove('dragging');
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    localStorage.setItem(storageKey, parseInt(paneEl.style.width, 10));
  }
  handleEl.addEventListener('mousedown', (e) => {
    dragging = true;
    startX = e.clientX;
    startWidth = paneEl.getBoundingClientRect().width;
    handleEl.classList.add('dragging');
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    e.preventDefault();
  });
}

function collapsePane(btnEl, paneEl, { storageKey }) {
  function setCollapsed(collapsed) {
    paneEl.style.display = collapsed ? 'none' : '';
    localStorage.setItem(storageKey, collapsed ? '1' : '0');
  }
  setCollapsed(localStorage.getItem(storageKey) === '1');
  btnEl.addEventListener('click', () => setCollapsed(paneEl.style.display !== 'none'));
}

function initLayout() {
  const treePane = document.getElementById('treePane');
  const side = document.getElementById('side');
  const editorPane = document.getElementById('editorPane');

  const treeWidth = localStorage.getItem('hermes.workspace.treeWidth');
  if (treeWidth) treePane.style.width = treeWidth + 'px';
  const sideWidth = localStorage.getItem('hermes.workspace.sideWidth');
  if (sideWidth) side.style.width = sideWidth + 'px';

  makeResizable(document.getElementById('treeHandle'), treePane, { min: 140, max: 360, storageKey: 'hermes.workspace.treeWidth' });
  makeResizable(document.getElementById('sideHandle'), side, { min: 180, max: 420, storageKey: 'hermes.workspace.sideWidth', invert: true });
  makeResizable(document.getElementById('editorHandle'), editorPane, { min: 220, max: 560, storageKey: 'hermes.workspace.editorWidth' });

  collapsePane(document.getElementById('toggleTreeBtn'), treePane, { storageKey: 'hermes.workspace.treeCollapsed' });
  collapsePane(document.getElementById('toggleSideBtn'), side, { storageKey: 'hermes.workspace.sideCollapsed' });
}

initLayout();
```

`invert: true` у боковой панели — её хендл сидит на **левой** границе
(между чатом и панелью), поэтому перетаскивание влево (уменьшение
`clientX`) должно увеличивать ширину `.side`, а не уменьшать: формула
берёт `-delta`. У дерева и редактора хендл на правой границе — обычное
направление, `invert` не передаётся (falsy по умолчанию).

- [ ] **Step 2: `showEditorPane` восстанавливает сохранённую ширину**

Найти (добавлено в Task 1, Step 7):

```js
function showEditorPane() {
  document.getElementById('editorPane').style.display = 'flex';
}
```

Заменить на:

```js
function showEditorPane() {
  const pane = document.getElementById('editorPane');
  const savedWidth = localStorage.getItem('hermes.workspace.editorWidth');
  pane.style.width = (savedWidth ? Number(savedWidth) : 320) + 'px';
  pane.style.display = 'flex';
}
```

- [ ] **Step 3: Проверить синтаксис**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('hermes-web/static/project-workspace.html', 'utf8');
const match = html.match(/<script>([\s\S]*?)<\/script>/);
fs.writeFileSync('/tmp/project-workspace-inline.js', match[1]);
"
node --check /tmp/project-workspace-inline.js
```

Expected: без вывода (успех).

- [ ] **Step 4: Commit**

```bash
git add hermes-web/static/project-workspace.html
git commit -m "feat(hermes-web): ручной resize (дерево/редактор/боковая) + сворачивание дерева и боковой панели, персистентно в localStorage (Группа D шаг 2)"
```

---

### Task 3: Защита несохранённых правок — dirty-tracking, confirm() на переключение файла и закрытие панели

**Files:**
- Modify: `hermes-web/static/project-workspace.html`

**Interfaces:**
- Consumes: `showEditorPane()`/`closeEditorPane()` (Task 1/2, эта задача
  оборачивает `closeEditorPane` в `attemptCloseEditor` и не меняет саму
  `closeEditorPane`), `apiFetch`, `refreshTreeAndFiles`.
- Produces: `attemptCloseEditor()`, `currentEditorFile` (string|null),
  `editorDirty` (bool) — ничем из этого дальнейшие задачи не пользуются
  (терминальная фронтенд-задача среза).

- [ ] **Step 1: Новые переменные состояния редактора**

Найти:

```js
let currentTree = null;
let pendingAttachments = [];
```

Заменить на:

```js
let currentTree = null;
let pendingAttachments = [];
let currentEditorFile = null;
let editorDirty = false;
const EDITOR_DISCARD_CONFIRM = 'Есть несохранённые изменения — открыть другой файл и потерять их?';
```

- [ ] **Step 2: `openEditor`/`saveEditor` — переключение файла и no-op на повторный клик**

Найти (текущая версия из Task 1):

```js
async function openEditor(relpath) {
  const resp = await apiFetch('/api/projects/file?' + new URLSearchParams({ path: projectPath, file: relpath }));
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) { alert('Не удалось открыть файл'); return; }
  document.getElementById('editorName').textContent = relpath;
  document.getElementById('editorText').value = await resp.text();
  showEditorPane();
  document.getElementById('saveEditorBtn').onclick = () => saveEditor(relpath);
}

async function saveEditor(relpath) {
  const content = document.getElementById('editorText').value;
  const resp = await apiFetch('/api/projects/file', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: projectPath, file: relpath, content }),
  });
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    alert('Не удалось сохранить: ' + (body.error || resp.status));
    return;
  }
  await refreshTreeAndFiles();
}
```

Заменить на:

```js
function attemptCloseEditor() {
  if (editorDirty && !confirm(EDITOR_DISCARD_CONFIRM)) return;
  closeEditorPane();
  currentEditorFile = null;
  editorDirty = false;
}

async function openEditor(relpath) {
  if (currentEditorFile === relpath) return;
  if (editorDirty && !confirm(EDITOR_DISCARD_CONFIRM)) return;
  const resp = await apiFetch('/api/projects/file?' + new URLSearchParams({ path: projectPath, file: relpath }));
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) { alert('Не удалось открыть файл'); return; }
  document.getElementById('editorName').textContent = relpath;
  document.getElementById('editorText').value = await resp.text();
  currentEditorFile = relpath;
  editorDirty = false;
  showEditorPane();
  document.getElementById('saveEditorBtn').onclick = () => saveEditor(relpath);
}

async function saveEditor(relpath) {
  const content = document.getElementById('editorText').value;
  const resp = await apiFetch('/api/projects/file', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: projectPath, file: relpath, content }),
  });
  if (resp.status === 401) { location.href = 'login.html'; return; }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    alert('Не удалось сохранить: ' + (body.error || resp.status));
    return;
  }
  editorDirty = false;
  await refreshTreeAndFiles();
}
```

`currentEditorFile === relpath` ловит и «клик по уже открытому файлу»
(no-op, без confirm — п. спека «Взаимодействие»), и защищает от лишнего
запроса при повторном клике сразу после открытия.

- [ ] **Step 3: Отслеживать правки в textarea + перевесить кнопки закрытия на `attemptCloseEditor`**

Найти (добавлено в Task 1, Step 8):

```js
document.getElementById('editorCloseXBtn').addEventListener('click', closeEditorPane);
document.getElementById('cancelEditorBtn').addEventListener('click', closeEditorPane);
```

Заменить на:

```js
document.getElementById('editorText').addEventListener('input', () => { editorDirty = true; });
document.getElementById('editorCloseXBtn').addEventListener('click', attemptCloseEditor);
document.getElementById('cancelEditorBtn').addEventListener('click', attemptCloseEditor);
```

- [ ] **Step 4: Проверить синтаксис**

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('hermes-web/static/project-workspace.html', 'utf8');
const match = html.match(/<script>([\s\S]*?)<\/script>/);
fs.writeFileSync('/tmp/project-workspace-inline.js', match[1]);
"
node --check /tmp/project-workspace-inline.js
```

Expected: без вывода (успех).

- [ ] **Step 5: Commit**

```bash
git add hermes-web/static/project-workspace.html
git commit -m "feat(hermes-web): confirm() на потерю несохранённых правок при смене файла/закрытии панели редактора, no-op на повторный клик (Группа D шаг 3)"
```

---

### Task 4: Деплой + живая приёмка на VPS + обновление документации проекта

**Files:** нет изменений кода — только проверка задеплоенного результата
и обновление `docs/state.md`/`docs/changelog.md`.

**Interfaces:**
- Consumes: итоговый `hermes-web/static/project-workspace.html` из Task
  1–3.

- [ ] **Step 1: Задеплоить изменённый файл на VPS**

```bash
rsync -avz -e "ssh -i ~/.ssh/id_ed25519_hermes_user" \
  hermes-web/static/project-workspace.html \
  hermes@212.115.55.116:~/hermes-web/static/
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 \
  "systemctl --user restart hermes-web.service && systemctl --user status hermes-web.service --no-pager"
```

Expected: `active (running)`, без трейсбеков в
`journalctl --user -u hermes-web.service -n 50`.

- [ ] **Step 2: Завести одноразовый `qa_temp`-аккаунт**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 bash -s <<'EOF'
cd ~/hermes-web
venv/bin/python3 -c "
from hermes_web import auth, storage
conn = storage.get_connection('hermes-web.db')
storage.create_user(conn, 'qa_temp', auth.hash_password('qa-temp-layout-2026'), 'owner', 'QA Temp')
print('qa_temp создан')
"
EOF
```

- [ ] **Step 3: Живая проверка в браузере — по разделу «Тесты» спека**

Открыть `https://hermes.blackboxbegin.space`, войти как `qa_temp` /
`qa-temp-layout-2026`, нажать «Быстрый чат» (заводит проект и сразу ведёт
в `project-workspace.html`, поведение Группы C). Последовательно
проверить:

1. Потянуть drag-хендл дерева вправо/влево — ширина дерева меняется в
   пределах 140–360px, чат подстраивается.
2. Нажать 🌲 в топбаре — дерево пропадает (`display:none`), хендл вместе
   с ним; повторный клик — дерево возвращается той же ширины, что было.
3. То же для 🗂 (боковая панель) и её хендла.
4. Кликнуть `.md`-файл в дереве (например `about.md`) — появляется
   четвёртая колонка между деревом и чатом, чат сужается, но остаётся
   кликабельным (можно написать и отправить сообщение, пока панель
   открыта).
5. Потянуть drag-хендл на правой границе редактора — ширина меняется в
   пределах 220–560px.
6. Отредактировать текст, нажать «Сохранить» — панель **остаётся
   открытой**, вкладка «Файлы» боковой панели обновилась.
7. С несохранёнными правками (напечатать что-то, не сохраняя) кликнуть
   другой `.md`-файл в дереве — появляется `confirm()` с текстом про
   потерю изменений; «Отмена» в диалоге — редактор остался как был;
   «ОК» — открылся новый файл.
8. Кликнуть повторно по уже открытому (активному) файлу — ничего не
   происходит (без confirm, без перезагрузки содержимого — проверить, что
   текст в textarea не сбросился, если там были несохранённые правки).
9. С несохранёнными правками нажать ✕ в шапке редактора (или «Отменить»
   в футере) — тот же `confirm()`; подтверждение — панель закрылась, чат
   занял освободившееся место.
10. Перезагрузить страницу — ширины дерева/редактора(если был открыт до
    перезагрузки)/боковой панели и свёрнутость дерева/боковой панели
    восстановились из `localStorage`; редактор при этом закрыт (состояние
    открытости не персистится — по споку).

Если что-то ведёт себя не так — применить `superpowers:systematic-debugging`,
начиная с `journalctl --user -u hermes-web.service -n 50` на сервере и
консоли браузера (`DevTools`).

- [ ] **Step 4: Удалить `qa_temp` и его данные**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 bash -s <<'EOF'
cd ~/hermes-web
venv/bin/python3 -c "
from hermes_web import storage
conn = storage.get_connection('hermes-web.db')
conn.execute(\"DELETE FROM chat_sessions WHERE user = 'qa_temp'\")
conn.execute(\"DELETE FROM web_sessions WHERE username = 'qa_temp'\")
conn.execute(\"DELETE FROM group_meta WHERE user = 'qa_temp'\")
conn.execute(\"DELETE FROM users WHERE username = 'qa_temp'\")
conn.commit()
print('qa_temp удалён из БД')
"
rm -rf ~/workspace/qa_temp
EOF
```

- [ ] **Step 5: Обновить `docs/state.md` и `docs/changelog.md`, снимок в git**

Отметить Группу D как реализованную и подтверждённую живой приёмкой (дата,
краткое описание проверенного сценария — по образцу записей за
2026-07-29/2026-07-31 в `changelog.md`). В `state.md` — обновить снимок
передачи: Группа D закрыта, следующий шаг — под-проект C (админ-панель).

```bash
bash scripts/snapshot.sh "Группа D (раздвижная панель редактора) задеплоена на VPS и подтверждена вживую — весь бэклог живого тестирования (B→A→C→D) закрыт целиком"
```

---

## Self-Review (для исполняющего план)

**1. Spec coverage:**
- Модалка → раздвижная панель между деревом и чатом — Task 1 (разметка) +
  Task 2 (resize) — покрыто.
- Дерево/боковая панель — ручной resize + collapse — Task 2 — покрыто.
- Flexbox вместо Grid — Task 1, Step 1–4 — покрыто.
- Открытие файла, восстановление ширины — Task 1 Step 7 + Task 2 Step 2 —
  покрыто.
- Confirm на переключение файла с несохранёнными правками — Task 3 Step 2
  — покрыто.
- Сохранение не закрывает панель — Task 1 Step 7 (явно убрана строка
  закрытия) — покрыто.
- Закрытие панели (крестик) с confirm — Task 3 Step 2–3 — покрыто.
- No-op на повторный клик по открытому файлу — Task 3 Step 2 — покрыто.
- Границы min/max по каждой колонке — Task 2 Step 1 (140–360 / 220–560 /
  180–420) — покрыто.
- Глобальные (не per-проектные) ключи localStorage, без персистентности
  открытости редактора — Task 2 Step 1, Global Constraints — покрыто.
- Не-текстовые файлы — поведение не меняется (`downloadFile`, вне этого
  среза) — не тронуто ни в одной задаче, как и требуется.
- Ручная живая проверка по каждому пункту раздела «Тесты» спека — Task 4
  Step 3 — покрыто.

**2. Placeholder scan:** каждый шаг содержит полный код изменения (полный
`old_string`/`new_string` для CSS/HTML/JS-правок, конкретные bash-команды
для деплоя и QA) — плейсхолдеров вида «добавить обработку ошибок»/TBD нет.

**3. Type consistency:** `makeResizable(handleEl, paneEl, {min, max,
storageKey, invert})` и `collapsePane(btnEl, paneEl, {storageKey})`
вызываются в Task 2 Step 1 с теми же именами параметров, что определены в
их же сигнатурах. `showEditorPane`/`closeEditorPane`/`attemptCloseEditor`
— имена согласованы между Task 1 (создание), Task 2 (правка
`showEditorPane`) и Task 3 (обёртка `attemptCloseEditor` вокруг
`closeEditorPane`, без переименований). `currentEditorFile`/`editorDirty`
объявлены один раз в Task 3 Step 1 и используются только в коде,
добавленном в той же задаче — нет обращений к ним из Task 1/2.
