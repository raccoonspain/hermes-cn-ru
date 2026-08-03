# Индикация «Hermes отвечает» + кнопка STOP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Показать пользователю, что Hermes ещё отвечает (вместо тишины при
заблокированной повторной отправке), и дать реальную кнопку STOP, которая
обрывает текущий ход и разблокирует ввод для исправленного сообщения.

**Architecture:** Два независимых, но соседних изменения. (1) Бэкенд
(`hermes_web/app.py::handle_send_message`) начинает явно и тихо (уровень
`debug`, не необработанное исключение) обрабатывать обрыв клиентского
соединения — уже существующий код в `finally` при этом реально отменяет
запрос к Hermes API, просто раньше срабатывал только при случайном сетевом
сбое. (2) Фронтенд (`project-workspace.html`) получает статус-строку над
полем ввода, синхронизированную с уже приходящими SSE-событиями, и кнопку
STOP, которая через `AbortController` намеренно обрывает fetch к
`/api/chat/{id}/send` — тот же путь, что и случайный обрыв связи, теперь
вызываемый осознанно.

**Tech Stack:** Python 3 / aiohttp (бэкенд, `hermes-web/hermes_web/`),
pytest + pytest-asyncio (тесты, `hermes-web/tests/`), обычный
`<script>`/vanilla JS без сборщика (фронтенд, `hermes-web/static/`).

## Global Constraints

- Спек: [docs/superpowers/specs/2026-08-03-chat-busy-indicator-and-stop-design.md](../specs/2026-08-03-chat-busy-indicator-and-stop-design.md) — при любом расхождении плана и спека, если расхождение не описано явно в плане как сознательное решение, спек главнее.
- Переезд на `/v1/runs` — вне рамок (см. спек, раздел «Вне рамок»).
- Существующий `finally: if not pending.done(): pending.cancel()` в `handle_send_message` не меняется — только оборачивается новой обработкой исключения снаружи.
- Фронтенд без автотестов (в репозитории нет JS-фреймворка/раннера) — каждый фронтенд-шаг проверяется синтаксически через `node -e "new Function(...)"` над содержимым `<script>`-блока, по образцу уже принятого в проекте паттерна (см. `docs/state.md`, Группа A / Task 6).
- Комментарии и текст в UI — на русском, в стиле остального файла.
- Коммитить через `bash scripts/snapshot.sh "<сообщение>"` после каждой задачи (обновляет git локально и пушит в GitHub) — так делают все предыдущие срезы этого проекта.

---

### Task 1: Бэкенд — тихая обработка обрыва клиента в `handle_send_message`

**Files:**
- Modify: `hermes-web/hermes_web/app.py:128-200` (функция `handle_send_message`)
- Test: `hermes-web/tests/test_app.py`

**Interfaces:**
- Consumes: ничего нового — существующие `logger = logging.getLogger(__name__)` (уже импортирован в `app.py`), существующий `HEARTBEAT_INTERVAL` (monkeypatchable, как в соседних тестах).
- Produces: обрыв клиентского соединения во время `handle_send_message` больше не улетает необработанным исключением наружу — ловится, логируется на уровне `DEBUG`, функция возвращает `response` как обычно. Это то, на что будет полагаться Task 3 (клиентский `AbortController.abort()`), но Task 3 не читает никакой новый код отсюда — только полагается на то, что сервер не падает и уже существующая логика в `finally` реально отменяет запрос к Hermes.

- [ ] **Step 1: Написать падающий тест — обрыв во время ожидания Hermes отменяет `pending` и не роняет необработанным исключением**

Добавить в `hermes-web/tests/test_app.py` (после
`test_send_message_stops_advancing_generator_after_write_failure`, то есть
после существующей строки `assert advanced == ["a"]` того теста):

```python
@pytest.mark.asyncio
async def test_send_message_disconnect_while_waiting_cancels_pending_and_logs_debug(
    aiohttp_client, app_and_conn, monkeypatch, caplog,
):
    # STOP (или просто уход со страницы) в момент, когда мы ещё ЖДЁМ
    # следующее событие от Hermes (pending ещё не done, идёт heartbeat-
    # ожидание) — обрыв в этот момент должен: (1) реально отменить
    # ожидающий agen.__anext__() (что закрывает наш HTTP-запрос к Hermes и
    # даёт ему кооперативно остановить ход — механизм уже существует в
    # finally, здесь только характеризуется как регрессионный тест); (2) не
    # всплыть необработанным исключением из handle_send_message, а тихо
    # залогироваться на уровне DEBUG (это то, что чинит эта задача).
    monkeypatch.setattr("hermes_web.app.HEARTBEAT_INTERVAL", 0.05)
    events = []

    async def fake_send_message(db_conn, http_session, config, chat_session_id, text):
        yield "assistant.delta", {"delta": "one"}
        try:
            await asyncio.sleep(10)
            events.append("finished-uncancelled")
        except asyncio.CancelledError:
            events.append("cancelled")
            raise
        yield "done", {}

    monkeypatch.setattr("hermes_web.app.quickchat.send_message", fake_send_message)

    original_write = web.StreamResponse.write
    calls = {"n": 0}

    async def flaky_write(self, data):
        calls["n"] += 1
        # 1-й write — "event: assistant.delta" из первого yield (должен
        # пройти). 2-й write — это уже пинг heartbeat во время 10-секундного
        # сна fake_send_message, то есть pending реально не done в этот
        # момент — именно тот случай, который отличается от уже
        # протестированного test_send_message_stops_advancing_generator_after_write_failure.
        if calls["n"] == 2:
            raise ConnectionResetError("simulated client disconnect while waiting on Hermes")
        return await original_write(self, data)

    monkeypatch.setattr(web.StreamResponse, "write", flaky_write)

    caplog.set_level(logging.DEBUG, logger="hermes_web.app")

    client = await aiohttp_client(app_and_conn)
    await client.post("/login", json={"username": "dem", "password": "secret123"})
    try:
        await client.post("/api/chat/chat1/send", json={"text": "привет"})
    except Exception:
        pass  # обрыв на сервере может выглядеть с этой стороны по-разному — важны server-side эффекты ниже

    await asyncio.sleep(0.05)
    assert events == ["cancelled"]
    debug_records = [r for r in caplog.records if r.name == "hermes_web.app" and r.levelno == logging.DEBUG]
    assert any("chat1" in r.getMessage() for r in debug_records)
    error_records = [r for r in caplog.records if r.name == "hermes_web.app" and r.levelno >= logging.ERROR]
    assert error_records == []
```

Добавить `import logging` в блок импортов `hermes-web/tests/test_app.py`
(сейчас там `import asyncio`, `import json` — добавить строку `import
logging` рядом).

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `cd hermes-web && python -m pytest tests/test_app.py::test_send_message_disconnect_while_waiting_cancels_pending_and_logs_debug -v`
Expected: FAIL — `assert any("chat1" in r.getMessage() for r in debug_records)` не выполняется (`debug_records` пуст: `hermes_web.app` сегодня ничего не логирует на этом пути, а необработанный `ConnectionResetError` просто улетает наружу из хендлера).

- [ ] **Step 3: Добавить обработку обрыва соединения**

В `hermes-web/hermes_web/app.py`, в функции `handle_send_message`, найти
текущий блок:

```python
    except (quickchat.QuickChatError, hermes_client.HermesClientError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
```

и добавить перед ним новый `except`-блок (порядок важен — более
специфичный `ConnectionResetError` должен идти раньше общего перехвата):

```python
    except ConnectionResetError:
        # Клиент оборвал соединение — либо ушёл со страницы, либо нажал
        # STOP (project-workspace.html). finally выше уже отменил pending,
        # что закрыло наш запрос к Hermes API и дало ему кооперативно
        # остановить ход. Дальше писать в response нельзя — клиента уже
        # нет, это штатный путь после этой задачи, не ошибка сервера.
        logger.debug("chat_session_id=%s: клиент оборвал соединение во время хода", chat_session_id)
    except (quickchat.QuickChatError, hermes_client.HermesClientError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
```

Остальная часть функции (тело второго `except` и `return response` в
конце) не меняется.

- [ ] **Step 4: Запустить тест снова и убедиться, что он проходит**

Run: `cd hermes-web && python -m pytest tests/test_app.py::test_send_message_disconnect_while_waiting_cancels_pending_and_logs_debug -v`
Expected: PASS

- [ ] **Step 5: Прогнать весь файл тестов, убедиться, что ничего не сломалось**

Run: `cd hermes-web && python -m pytest tests/test_app.py -v`
Expected: все тесты PASS, включая уже существующий
`test_send_message_stops_advancing_generator_after_write_failure` (он не
должен был измениться в поведении — там обрыв происходит ДО того, как
`pending` переприсвоен, то есть новый `except ConnectionResetError` тоже
сработает вместо необработанного исключения, но это не меняет
проверяемый в том тесте инвариант `advanced == ["a"]`).

- [ ] **Step 6: Прогнать полный набор тестов `hermes-web`**

Run: `cd hermes-web && python -m pytest -q`
Expected: PASS, без новых падений в других файлах.

- [ ] **Step 7: Commit**

```bash
cd /home/deploy/hermes-cn-ru
bash scripts/snapshot.sh "фикс: тихая обработка обрыва клиента в handle_send_message (готовит почву для STOP)"
```

---

### Task 2: Фронтенд — индикация «Hermes отвечает»

**Files:**
- Modify: `hermes-web/static/project-workspace.html` (CSS-блок ~строки 96-104, HTML композера ~строки 172-190, функция `sendMessage()` ~строки 790-884)

**Interfaces:**
- Consumes: ничего из Task 1 (полностью независимо, чисто фронтенд).
- Produces: DOM-элементы `#busyStatus` (контейнер, класс `.on` управляет видимостью) и `#busyStatusText` (текст внутри) — Task 3 их не трогает напрямую, но должен сохранить при своей правке той же функции `sendMessage()`.

- [ ] **Step 1: Добавить CSS для статус-строки**

В `hermes-web/static/project-workspace.html`, в `<style>`-блоке, сразу
после существующего правила (строка 104):

```css
  .send-btn{background:var(--gold);border:none;color:var(--sky-deep);width:36px;height:36px;border-radius:10px;cursor:pointer;flex-shrink:0;font-size:14px}
```

добавить:

```css
  .busy-status{display:none;align-items:center;gap:6px;margin-bottom:6px;font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--text-dim)}
  .busy-status.on{display:flex}
  .busy-status .dot{width:6px;height:6px;border-radius:50%;background:var(--gold);animation:busy-pulse 1.1s ease-in-out infinite}
  @keyframes busy-pulse{0%,100%{opacity:.25}50%{opacity:1}}
```

- [ ] **Step 2: Добавить HTML статус-строки над полем ввода**

В том же файле найти:

```html
      <div class="upload-target-row">
        <span>папка для результата:</span>
        <select id="resultTargetSelect"></select>
      </div>
      <div class="compose-box">
```

Заменить на:

```html
      <div class="upload-target-row">
        <span>папка для результата:</span>
        <select id="resultTargetSelect"></select>
      </div>
      <div class="busy-status" id="busyStatus"><span class="dot"></span><span id="busyStatusText">Hermes думает…</span></div>
      <div class="compose-box">
```

- [ ] **Step 3: Обновить `sendMessage()` — показывать/обновлять/скрывать статус-строку**

Найти текущее начало функции `sendMessage()`:

```js
async function sendMessage() {
  const input = document.getElementById('composeInput');
  const sendBtn = document.getElementById('sendBtn');
  const text = input.value.trim();
  if (!text && pendingAttachments.length === 0) return;
  // Пока идёт ход — не даём отправить второй: recoverAfterStreamDrop при
  // восстановлении после обрыва целиком переприсваивает общий массив
  // messages, что гонится с параллельным readSSE-коллбэком второго хода.
  if (sendBtn.disabled) return;
  sendBtn.disabled = true;
  input.value = '';
  autosizeCompose();
```

Заменить на:

```js
async function sendMessage() {
  const input = document.getElementById('composeInput');
  const sendBtn = document.getElementById('sendBtn');
  const busyStatus = document.getElementById('busyStatus');
  const busyStatusText = document.getElementById('busyStatusText');
  const text = input.value.trim();
  if (!text && pendingAttachments.length === 0) return;
  // Пока идёт ход — не даём отправить второй: recoverAfterStreamDrop при
  // восстановлении после обрыва целиком переприсваивает общий массив
  // messages, что гонится с параллельным readSSE-коллбэком второго хода.
  if (sendBtn.disabled) return;
  sendBtn.disabled = true;
  busyStatusText.textContent = 'Hermes думает…';
  busyStatus.classList.add('on');
  input.value = '';
  autosizeCompose();
```

Затем в теле `readSSE`-колбэка найти:

```js
        else if (name === 'assistant.delta') {
          // Защита от риска выше: если предыдущий шаг уже был закрыт
          // assistant.completed, а нового message.started почему-то не
          // было — всё равно открываем новый слот здесь, а не дозаписываем
          // в уже показанный законченный пузырь.
          openFreshSlotIfClosed();
          messages[assistantIdx].content += payload.delta || ''; renderMessages();
        }
```

Заменить на:

```js
        else if (name === 'assistant.delta') {
          // Защита от риска выше: если предыдущий шаг уже был закрыт
          // assistant.completed, а нового message.started почему-то не
          // было — всё равно открываем новый слот здесь, а не дозаписываем
          // в уже показанный законченный пузырь.
          busyStatus.classList.remove('on');
          openFreshSlotIfClosed();
          messages[assistantIdx].content += payload.delta || ''; renderMessages();
        }
```

Затем сразу после этого блока найти:

```js
        else if (name === 'assistant.completed') {
          if (payload.content) messages[assistantIdx].content = payload.content;
          renderMessages();
          slotOpen = false;
        }
        else if (name === 'error') { messages[assistantIdx].content = `Ошибка: ${payload.message || 'неизвестная'}`; renderMessages(); }
        else if (name === 'done') { streamEndedCleanly = true; }
        else { appendActivity(name, payload); }
```

Заменить на:

```js
        else if (name === 'assistant.completed') {
          if (payload.content) messages[assistantIdx].content = payload.content;
          renderMessages();
          slotOpen = false;
        }
        else if (name === 'error') { messages[assistantIdx].content = `Ошибка: ${payload.message || 'неизвестная'}`; renderMessages(); }
        else if (name === 'done') { streamEndedCleanly = true; }
        else if (name === 'tool.started' || name === 'tool.progress') {
          if (payload.tool_name) busyStatusText.textContent = `Hermes использует ${payload.tool_name}…`;
          appendActivity(name, payload);
        }
        else { appendActivity(name, payload); }
```

Наконец, найти текущий `finally`-блок в конце функции:

```js
  } finally {
    sendBtn.disabled = false;
  }
}
```

Заменить на:

```js
  } finally {
    sendBtn.disabled = false;
    busyStatus.classList.remove('on');
  }
}
```

- [ ] **Step 4: Проверить синтаксис**

Извлечь содержимое `<script>...</script>` (второй, большой блок — не тот,
что подключает `app.js`) из `hermes-web/static/project-workspace.html` и
прогнать через:

Run: `node -e "new Function(require('fs').readFileSync('/tmp/pw-script.js', 'utf8'))"`
(предварительно сохранив извлечённый JS-текст в `/tmp/pw-script.js`)
Expected: без вывода — значит, синтаксически корректно (`new Function`
бросит `SyntaxError` в stderr при поломке).

- [ ] **Step 5: Ручная живая проверка (документируется, выполняется на деплое)**

Не автоматизируется (нет живого браузера в рамках этой задачи) — открыть
`project-workspace.html` любого проекта, отправить сообщение, глазами
убедиться: (а) строка «Hermes думает…» появляется сразу после отправки;
(б) если модель вызывает инструмент — текст меняется на «Hermes использует
`<имя>`…»; (в) как только приходит первый текст ответа — строка исчезает;
(г) строка не остаётся видимой после завершения хода. Отметить как
пройдено/не пройдено в `docs/state.md` при следующей живой приёмке (после
Task 3, вместе).

- [ ] **Step 6: Commit**

```bash
cd /home/deploy/hermes-cn-ru
bash scripts/snapshot.sh "фича: индикация «Hermes отвечает» над полем ввода чата"
```

---

### Task 3: Фронтенд — кнопка STOP

**Files:**
- Modify: `hermes-web/static/project-workspace.html` (CSS ~строка добавленная в Task 2, HTML композера, module-level `let`-переменные ~строки 205-218, функция `sendMessage()` — версия после Task 2, блок обработчиков событий ~строки 984-988)

**Interfaces:**
- Consumes: `#busyStatus`/`#busyStatusText` из Task 2 (используются как есть, не переопределяются). `apiFetch(url, options)` из `hermes-web/static/app.js` — уже прозрачно прокидывает `options` в `fetch`, включая `signal`, без изменений в `app.js`.
- Produces: модульная переменная `currentAbortController` (нужна только внутри этого файла, не экспортируется).

- [ ] **Step 1: Добавить CSS для кнопки STOP**

В `<style>`-блоке, сразу после CSS, добавленного в Task 2 (`@keyframes
busy-pulse{...}`), добавить:

```css
  #stopBtn{display:none;color:var(--red);border-color:var(--red)}
  #stopBtn.on{display:flex}
```

- [ ] **Step 2: Добавить HTML кнопки STOP рядом с кнопкой отправки**

Найти:

```html
        <textarea id="composeInput" rows="1" placeholder="Написать Hermes… (Ctrl+V — вставить изображение из буфера)"></textarea>
        <button class="send-btn" id="sendBtn" title="отправить">➤</button>
```

Заменить на:

```html
        <textarea id="composeInput" rows="1" placeholder="Написать Hermes… (Ctrl+V — вставить изображение из буфера)"></textarea>
        <button class="icon-btn" id="stopBtn" title="остановить ход">⏹</button>
        <button class="send-btn" id="sendBtn" title="отправить">➤</button>
```

- [ ] **Step 3: Добавить модульную переменную для текущего `AbortController`**

Найти блок объявлений в начале `<script>`:

```js
let currentEditorFile = null;
let editorDirty = false;
```

Заменить на:

```js
let currentEditorFile = null;
let editorDirty = false;
// Текущий AbortController активного хода — модульного уровня, чтобы
// обработчик клика по STOP (отдельный от sendMessage()) мог до него
// дотянуться. null, когда хода нет.
let currentAbortController = null;
```

- [ ] **Step 4: Обновить `sendMessage()` — завести AbortController, показать/спрятать STOP, обработать пользовательскую остановку**

Найти текущее начало функции (после правок Task 2):

```js
async function sendMessage() {
  const input = document.getElementById('composeInput');
  const sendBtn = document.getElementById('sendBtn');
  const busyStatus = document.getElementById('busyStatus');
  const busyStatusText = document.getElementById('busyStatusText');
  const text = input.value.trim();
  if (!text && pendingAttachments.length === 0) return;
  // Пока идёт ход — не даём отправить второй: recoverAfterStreamDrop при
  // восстановлении после обрыва целиком переприсваивает общий массив
  // messages, что гонится с параллельным readSSE-коллбэком второго хода.
  if (sendBtn.disabled) return;
  sendBtn.disabled = true;
  busyStatusText.textContent = 'Hermes думает…';
  busyStatus.classList.add('on');
  input.value = '';
  autosizeCompose();
```

Заменить на:

```js
async function sendMessage() {
  const input = document.getElementById('composeInput');
  const sendBtn = document.getElementById('sendBtn');
  const stopBtn = document.getElementById('stopBtn');
  const busyStatus = document.getElementById('busyStatus');
  const busyStatusText = document.getElementById('busyStatusText');
  const text = input.value.trim();
  if (!text && pendingAttachments.length === 0) return;
  // Пока идёт ход — не даём отправить второй: recoverAfterStreamDrop при
  // восстановлении после обрыва целиком переприсваивает общий массив
  // messages, что гонится с параллельным readSSE-коллбэком второго хода.
  if (sendBtn.disabled) return;
  sendBtn.disabled = true;
  stopBtn.classList.add('on');
  busyStatusText.textContent = 'Hermes думает…';
  busyStatus.classList.add('on');
  input.value = '';
  autosizeCompose();
  currentAbortController = new AbortController();
  let stoppedByUser = false;
```

Затем найти вызов `apiFetch` внутри той же функции:

```js
    const resp = await apiFetch(`/api/chat/${encodeURIComponent(chatSessionId)}/send`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: fullText,
        result_target: document.getElementById('resultTargetSelect').value || 'result',
      }),
    });
```

Заменить на:

```js
    const resp = await apiFetch(`/api/chat/${encodeURIComponent(chatSessionId)}/send`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: fullText,
        result_target: document.getElementById('resultTargetSelect').value || 'result',
      }),
      signal: currentAbortController.signal,
    });
```

Затем найти блок с `readSSE`/обработкой конца потока:

```js
    try {
      await readSSE(resp, (name, payload) => {
```

и весь блок до (включительно):

```js
    } catch (err) {
      streamEndedCleanly = false;
    }
    // Соединение иногда рвётся раньше, чем агент реально закончил ход (долгая
    // тихая пауза — wormsoft.ru/докер). Бэкенд продолжает работать и допишет
    // ответ в историю чата — целиком перечитываем историю вместо того, чтобы
    // гадать, сколько ещё сообщений придёт в этом ходе (см. Проблему 3 в
    // спеке — позиционное отслеживание несовместимо с переменным числом
    // сообщений за один ход).
    if (streamEndedCleanly) await reconcileWithHistory();
    else await recoverAfterStreamDrop();
    await refreshTreeAndFiles();
  } finally {
    sendBtn.disabled = false;
    busyStatus.classList.remove('on');
  }
}
```

заменить целиком на:

```js
    } catch (err) {
      streamEndedCleanly = false;
      stoppedByUser = err.name === 'AbortError';
    }
    // Соединение иногда рвётся раньше, чем агент реально закончил ход (долгая
    // тихая пауза — wormsoft.ru/докер). Бэкенд продолжает работать и допишет
    // ответ в историю чата — целиком перечитываем историю вместо того, чтобы
    // гадать, сколько ещё сообщений придёт в этом ходе (см. Проблему 3 в
    // спеке — позиционное отслеживание несовместимо с переменным числом
    // сообщений за один ход).
    if (streamEndedCleanly) {
      await reconcileWithHistory();
    } else if (stoppedByUser) {
      // Осознанная остановка пользователем — не сетевой сбой, поэтому НЕ
      // зовём recoverAfterStreamDrop() (он рассчитан на случайный обрыв и
      // ждёт/опрашивает историю до MAX_WAIT_MS). Оставляем то, что уже было
      // отрендерено вживую, с пометкой; один быстрый reconcileWithHistory()
      // на случай, если Hermes всё же успел что-то сохранить в свою
      // историю к этому моменту.
      messages[assistantIdx].content += '\n\n⏹ _остановлено пользователем_';
      renderMessages();
      await reconcileWithHistory();
    } else {
      await recoverAfterStreamDrop();
    }
    await refreshTreeAndFiles();
  } finally {
    sendBtn.disabled = false;
    stopBtn.classList.remove('on');
    busyStatus.classList.remove('on');
    currentAbortController = null;
  }
}
```

- [ ] **Step 5: Добавить обработчик клика по STOP**

Найти:

```js
document.getElementById('sendBtn').addEventListener('click', sendMessage);
```

Заменить на:

```js
document.getElementById('sendBtn').addEventListener('click', sendMessage);
document.getElementById('stopBtn').addEventListener('click', () => {
  if (currentAbortController) currentAbortController.abort();
});
```

- [ ] **Step 6: Проверить синтаксис**

Run: тот же способ, что в Task 2 Step 4 — извлечь `<script>`-блок,
прогнать через `node -e "new Function(...)"`.
Expected: без вывода (синтаксически корректно).

- [ ] **Step 7: Ручная живая проверка (документируется, выполняется на деплое)**

Открыть `project-workspace.html`, отправить сообщение, нажать STOP до
завершения хода, глазами убедиться: (а) поле ввода и кнопка отправки
разблокируются почти сразу; (б) частично написанный ответ остаётся виден
с пометкой «⏹ остановлено пользователем»; (в) можно сразу отправить новое,
скорректированное сообщение без перезагрузки страницы; (г) перезагрузить
страницу и посмотреть — сохранился ли частичный ответ в истории (см. риск
в спеке, раздел «Известный риск» — задокументировать фактический результат
в `docs/state.md`, это не обязательно баг, если ответ исчез).

- [ ] **Step 8: Commit**

```bash
cd /home/deploy/hermes-cn-ru
bash scripts/snapshot.sh "фича: кнопка STOP — реально обрывает ход через AbortController"
```

---

## После реализации (вне задач плана, для контроллера)

- Задеплоить на VPS (`rsync` изменённых файлов + `systemctl --user restart hermes-web.service`), по образцу всех предыдущих срезов (см. `docs/state.md`).
- Живая приёмка обеих ручных проверок (Task 2 Step 5, Task 3 Step 7) на реальном сервере — включая фиксацию, сохраняется ли частичный ответ в истории Hermes после STOP (открытый вопрос спека).
- Обновить `docs/state.md`/`docs/changelog.md` по итогам.
