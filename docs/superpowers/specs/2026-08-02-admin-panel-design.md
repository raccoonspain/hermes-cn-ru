# Спек: Админ-панель (под-проект C) — метрики VPS, управление пользователями, журнал событий

**Дата:** 2026-08-02 · **Статус:** согласовано с пользователем, ждёт спек-ревью

## Контекст

Бэклог живого тестирования рабочего экрана (Группы B→A→C→D) закрыт
целиком (2026-08-02). Следующий шаг по общему плану проекта —
**под-проект C**: реализация экрана `admin.html`, дизайн которого уже
согласован в D-009 и зафиксирован кликабельным HTML-макетом в
`result/admin.html` (условные данные, без бэкенда). Этот спек описывает
бэкенд-реализацию поверх уже существующего `hermes-web` (aiohttp,
SQLite), по образцу того, как реализованы под-проекты A и B.

Макет описывает 4 экрана-раздела (nav слева: «Обзор», «Пользователи»,
«VPS и агент», «Журнал») — в согласованной с пользователем версии этого
среза «Обзор» и «Пользователи» объединены в один экран (как на самом
макете — обзор и таблица пользователей на одной странице), «Журнал» —
отдельный раздел. Раздел «VPS и агент» на макете отдельным пунктом nav
не имеет уникального контента сверх карточек «Обзор» — метрики VPS уже
показаны там же, поэтому отдельный экран не заводим (см. «Что сознательно
не делаем»).

## Global Constraints

- Доступ ко всем `/api/admin/*` эндпоинтам — только `role == "owner"`
  (403 для `participant`, 401 для неавторизованных — тот же контракт,
  что и у остальных `/api/*` в проекте).
- Никаких новых Python-зависимостей — в проекте нет `requirements.txt`,
  пакеты в venv ставятся вручную; метрики VPS читаются через stdlib
  (`/proc`, `shutil`), без `psutil`.
- Логин (`username`) — неизменяемый идентификатор: он одновременно
  primary key в SQLite (`users.username`) и имя папки на диске
  (`workspace/<username>/...`, см. `quickchat.py`/`projects.py`). Ни один
  эндпоинт этого среза не переименовывает пользователя.
- Валидация нового логина при создании пользователя: `^[a-z0-9_-]{2,32}$`
  (строчные латинские буквы, цифры, `_`, `-`), 400 при несовпадении —
  тот же принцип защиты «то, что становится именем папки на диске, всегда
  валидируется на бэкенде», что уже потребовался и был закрыт для `group`
  в под-проекте A (path traversal в `create_project`/`move_project`).
- Роль пользователя — только `"owner"` или `"participant"` (уже
  используемые в БД значения), allow-list на бэкенде, 400 на что угодно
  ещё.
- Владелец не может через `/api/admin/users/{username}` понизить роль
  **самому себе** (`request["user"]["username"] == username` и
  `role != "owner"` → 400) — защита от случайной самоблокировки от
  собственной админки. Смена роли/данных любого **другого** пользователя
  не ограничена.
- Журнал событий логирует только крупные действия (вход, создание/
  удаление проекта, создание чат-сессии, действия из раздела
  «Пользователи») — не файловые операции и не отдельные сообщения чата.
  Журнал стартует с чистого листа с момента деплоя этого среза, без
  ретроактивного восстановления истории.
- Пароль пользователя (при создании и при сбросе) вводится администратором
  напрямую в поле формы — без автогенерации, без email-рассылки.

## Что сознательно не делаем

- **Карточка «Кредиты wormsoft.ru» / rate limit с макета — убрана из этого
  среза.** Проверено эмпирически (2026-08-02): у wormsoft.ru нет
  публичного API для остатка кредитов/rate limit в реальном времени —
  только статичная таблица тарифов (`/api/user-connector/subscription-limits`,
  общедоступный список тарифных планов, не привязан к конкретному ключу)
  и каталог моделей (`/api/gpt/models`, 200 OK). Прямые запросы с реальным
  `WORMSOFT_API_KEY` на вероятные пути (`/api/gpt/usage`,
  `/api/user-connector/usage`, `/balance`, `/credits`, `/account`, `/me`)
  — везде 404. Если wormsoft.ru добавит такой API в будущем — отдельный
  небольшой довесок, не блокирует этот срез.
- **Отдельный экран «VPS и агент» в nav** — не заводим: карточки метрик
  уже на «Обзоре», второй экран с теми же цифрами не добавляет ценности
  в этом срезе.
- **Удаление пользователя** — на макете нет кнопки удаления (только
  «изменить»/«сброс пароля»), не добавляем неспрошенную функциональность.
  Если понадобится — отдельный срез (нужно решать, что делать с его
  проектами/папкой на диске, это не тривиально).
- **Смена логина** — см. Global Constraints.
- **Ретенция/очистка `events`** — при двух пользователях объём мал, не
  нужна в этом срезе.
- **Системные события Hermes** (перезапуски сервиса, ошибки провайдера)
  в журнал не попадают — это `journalctl`/логи агента, отдельный источник,
  не смешиваем с событиями `hermes-web`.

## Раздел 1: Доступ

**Файлы:** `hermes_web/app.py`

- Новая функция `_require_owner(request)`: вызывает существующий
  `_require_user(request)`, дополнительно проверяет `user["role"] ==
  "owner"`, иначе `web.HTTPForbidden`. Используется всеми хендлерами
  `/api/admin/*` вместо `_require_user`.
- `home.html`: пункт «⚙️ Админка» скрыт, если `role != "owner"` (роль уже
  приходит в ответе `/api/me`, менять бэкенд не нужно — чисто фронтенд).
- `admin.html` раздаётся как обычная статика (как `project-selector.html`
  и другие экраны) — секретов в разметке нет, реальная проверка доступа
  происходит на уровне `/api/admin/*`, при 401/403 фронтенд редиректит на
  `/login.html`/`/home.html` (тот же паттерн, что в `project-selector.js`).

## Раздел 2: «Обзор» — метрики VPS и активность

**Файлы:** новый `hermes_web/admin_metrics.py`, `hermes_web/app.py`

Один эндпоинт `GET /api/admin/overview`, отдаёт всё одним JSON:

```json
{
  "cpu_percent": 34.2,
  "ram": {"used_bytes": 5470000000, "total_bytes": 8589934592},
  "disk": {"used_bytes": 44040192000, "total_bytes": 96636764160, "path": "/home/hermes/workspace"},
  "active_sessions": 3,
  "active_users": 2
}
```

- **CPU** — два замера `/proc/stat` (агрегатная строка `cpu `) с паузой
  ~100мс между ними, дельта `(busy2-busy1)/(total2-total1)*100`. Требует
  `await asyncio.sleep(0.1)` внутри хендлера — приемлемо, страница
  админки открывается редко, не горячий путь.
- **RAM** — `/proc/meminfo`, поля `MemTotal`/`MemAvailable` (used =
  total - available, надёжнее чем `MemFree` — учитывает кэш).
- **Диск** — `shutil.disk_usage(workspace_root)` (stdlib), тот же
  `workspace_root`, что использует `quickchat.py`/`projects.py`.
- **Активные сессии/пользователи** — `SELECT COUNT(*), COUNT(DISTINCT
  username) FROM web_sessions WHERE expires_at > ?` (новая функция
  `storage.count_active_sessions(conn, now)`), не требует новых таблиц.

## Раздел 3: «Пользователи»

**Файлы:** `hermes_web/storage.py`, `hermes_web/app.py`

### Хранилище (`storage.py`)

Новые функции поверх существующей таблицы `users`:

```python
def list_users(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT username, role, display_name FROM users ORDER BY username").fetchall()
    return [dict(row) for row in rows]

def update_user(conn: sqlite3.Connection, username: str, display_name: str, role: str) -> None:
    conn.execute(
        "UPDATE users SET display_name = ?, role = ? WHERE username = ?",
        (display_name, role, username),
    )
    conn.commit()

def update_user_password(conn: sqlite3.Connection, username: str, password_hash: str) -> None:
    conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, username))
    conn.commit()
```

`create_user` уже существует (используется `seed_users.py`) — переиспользуется
как есть.

### API (`app.py`)

- `GET /api/admin/users` — список: `username`, `display_name`, `role`,
  `project_count` (через `project_index_core.list_projects(username, ...)`,
  `len(...)`), `last_active` (`MAX(COALESCE(last_message_at, created_at))`
  по `chat_sessions` этого `user` — `last_message_at` точнее отражает
  реальную активность, чем момент создания сессии, но бывает `NULL` до
  первого сообщения; может быть `null` целиком, если чат-сессий нет).
- `POST /api/admin/users` — body `{username, display_name, role,
  password}`. Валидация: username по regex + не существует уже
  (`storage.get_user` не `None` → 409), role в `{"owner", "participant"}`,
  password не пустой. При успехе — `storage.create_user` +
  `storage.log_event(actor=текущий владелец, verb="user.create",
  detail=username)`.
- `POST /api/admin/users/{username}` — body `{display_name, role}`.
  404 если пользователь не найден. 400 если `username == request["user"]["username"]
  and role != "owner"` (самоблокировка). `storage.update_user` +
  `log_event("user.update", username)`.
- `POST /api/admin/users/{username}/reset-password` — body `{password}`.
  404 если не найден, 400 на пустой пароль. `auth.hash_password` +
  `storage.update_user_password` + `log_event("user.reset_password",
  username)`.

### Фронтенд (`admin.html`)

- Модалка «Новый пользователь» на макете не имеет поля пароля — в этом
  срезе добавляется четвёртое поле «Пароль» (без него создать реально
  рабочего пользователя через UI нельзя).
- Модалка «Изменить пользователя»: поле «Логин» становится
  read-only (серым текстом, не `<input>`) — редактируются только «Имя» и
  «Роль», как решили в Global Constraints.
- Таблица пользователей рендерится из `GET /api/admin/users` вместо
  захардкоженных двух строк на макете.
- Кнопка «сброс пароля» открывает третью, новую модалку с одним полем
  «Новый пароль» + подтверждением.

## Раздел 4: «Журнал событий»

**Файлы:** `hermes_web/storage.py` (новая таблица + функции),
`hermes_web/app.py`, `hermes_web/projects.py`, `hermes_web/quickchat.py`

### Хранилище

```python
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        actor TEXT NOT NULL,
        verb TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT ''
    )
    """
)
```
(добавляется в `init_db`, как и остальные таблицы)

```python
def log_event(conn: sqlite3.Connection, actor: str, verb: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO events (ts, actor, verb, detail) VALUES (?, ?, ?, ?)",
        (time.time(), actor, verb, detail),
    )
    conn.commit()

def list_events(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT ts, actor, verb, detail FROM events ORDER BY id DESC LIMIT ?", (limit,),
    ).fetchall()
    return [dict(row) for row in rows]
```

### Точки логирования (verb — значение)

- `handle_login` (успешный вход) → `"login"`, detail пусто.
- `handle_create_project` → `"project.create"`, detail = `<group>/<slug>`.
- `handle_delete_project` → `"project.delete"`, detail = путь проекта.
- Создание новой чат-сессии (`quickchat.create_quick_chat` и обычное
  открытие проекта в `project-workspace.html`, там где заводится строка
  в `chat_sessions`) → `"chat.start"`, detail = `project_path`.
- `user.create` / `user.update` / `user.reset_password` — см. Раздел 3.

Каждый вызов — сразу после успешного завершения основного действия (не
до), чтобы неудачная операция не порождала ложную запись в журнале.

### API и фронтенд

- `GET /api/admin/events?limit=50` → `{"events": [...]}`, новые сверху.
- `admin.html`: секция «Журнал» рендерит `.log-line` из этого списка
  вместо 5 захардкоженных строк на макете. Формат времени — как в чате
  (`HH:MM:SS`), `verb` переводится в человекочитаемый текст на фронтенде
  простым словарём (`{"login": "вход", "project.create": "создал
  проект", ...}`).

## Тестирование

- `tests/test_storage.py` — новые функции (`list_users`, `update_user`,
  `update_user_password`, `count_active_sessions`, `log_event`,
  `list_events`).
- `tests/test_admin.py` (новый файл) — HTTP-уровень: 401 без сессии, 403
  для `participant`, 200 для `owner` на каждом эндпоинте; валидация
  username-regex и дубликата; запрет самопонижения роли; проверка, что
  `project.create`/`user.create` действительно пишут строку в `events`.
- Фронтенд без автотестов (как и у остальных экранов в проекте) —
  проверка построчной трассировкой + `node -e "new Function(...)"` на
  извлечённый `<script>`, как делалось для прошлых срезов.

## Развёртывание

Тот же паттерн, что и в прошлых срезах: резервная копия
`hermes-web.db`/изменённых `.py` в `~/.hermes-web-backups/<TS>/` перед
`rsync`, `rsync` изменённых файлов (`app.py`, `storage.py`, `projects.py`,
`quickchat.py`, `admin_metrics.py`, `static/admin.html`), `systemctl
--user restart hermes-web.service`. Миграция схемы БД — `CREATE TABLE IF
NOT EXISTS` в `init_db`, применяется автоматически при следующем
подключении, без отдельного скрипта.
