# Hermes-плагин `project_index` — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать и выкатить на реальный VPS Hermes-плагин `project_index` — три agent-facing инструмента (`project_index_update`, `project_search_similar`, `project_move`) поверх файловой структуры `workspace/<user>/{ALL,<Группа>}/<Проект>`, плюс maintenance-скрипт `reindex.py` (не agent-facing).

**Architecture:** Плагин разбит на слой хранения (`storage.py` — SQLite + косинус чистым Python), слой внешнего API (`embeddings.py` — вызов wormsoft.ru с политикой ретраев из `docs/wormsoft-api.md`) и слой бизнес-логики (`core.py` — парсинг `about.md`, валидация путей, `index_update`/`search_similar`/`move_project`/`reindex_all`). `core.py` не импортирует ничего Hermes-специфичного — только `__init__.py` регистрирует инструменты через `ctx.register_tool(...)`, тонкими обёртками поверх `core.py`. Это даёт то, что нужно спеку: весь пакет можно импортировать и тестировать где угодно (локально, без живого Hermes), а будущий веб-бэкенд (под-проект B) сможет подключить `core.py` напрямую.

**Tech Stack:** Python 3.11 (венв Hermes на сервере) / 3.12 (локальная разработка — код чистый Python+stdlib, разницы версий не касается), `requests` и `PyYAML` (оба уже реальные зависимости `hermes-agent`, не новые), `pytest` (только для тестов, не деплоится).

## Global Constraints

Точные значения — копия из спека (`docs/superpowers/specs/2026-07-25-project-index-plugin-design.md`), обязательны для всех задач ниже:

- Корень workspace на сервере: `/home/hermes/workspace` (`WORKSPACE_ROOT`).
- Пользователи (фиксированы, не расширять список без явного запроса): `dem` (заказчик), `rost` (сын, Ростислав).
- Модель эмбеддингов: `qwen/qwen3-embedding:8b`, эндпоинт `POST https://ai.wormsoft.ru/api/gpt/embedding`, ключ — `WORMSOFT_API_KEY` из окружения.
- Эмбеддится только Название + Краткое описание + tags из `about.md` — не «Опорные точки»/«На чём остановились».
- Косинус — **чистый Python, без numpy** (numpy не установлен на сервере вне `voice`-extras).
- Ошибки wormsoft.ru: 429 с текстом «reached the limit» → кредиты кончились, **без ретрая**. 429 без этого текста (rate limit) или 500 → **один ретрай** с паузой ≈4 сек. После исчерпания попыток — не бросать исключение, просто не проставлять embedding.
- `project_move`: коллизия имени → жёсткая ошибка, без авто-суффикса. Дата-префикс `ГГГГ-ММ-ДД_` снимается при выходе из `ALL`, добавляется при входе в `ALL`. Всегда пересчитывает индекс после физического переноса.
- `project_reindex_all` — **не регистрируется как agent-facing инструмент**, только функция в `core.py` + отдельный CLI-скрипт `reindex.py`.
- Все три agent-facing инструмента принимают явный параметр `user` — Hermes не передаёт платформенный аккаунт хендлеру автоматически.
- Директория плагина и имя пакета — `project_index` (подчёркивание, не дефис) — чтобы пакет был обычным импортируемым Python-модулем.
- JSON-формат результатов инструментов должен точно совпадать с контрактом `tools/registry.py` в hermes-agent: `tool_result(data)` → `json.dumps(data, ensure_ascii=False)`, `tool_error(message)` → `json.dumps({"error": str(message)}, ensure_ascii=False)`. Реализуем локальными копиями этих двух функций внутри `__init__.py` (не импортируем `tools.registry` — это убирает зависимость от внутреннего Hermes-модуля, который может исчезнуть/измениться при обновлении, и заодно делает весь пакет тестируемым без живого Hermes).

---

## Task 0: Локальное окружение для разработки и тестов

**Files:**
- Create: `/home/deploy/hermes-cn-ru/.gitignore` (дополнить)
- Create: (вне репозитория) `/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/` — локальный venv для быстрых прогонов тестов

**Interfaces:** нет (инфраструктурная задача, ничего не производит для других тасков, кроме рабочего `pytest`).

- [ ] **Step 1: Создать локальный venv и поставить зависимости для тестов**

```bash
python3 -m venv /tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pip install --quiet pytest==9.0.2 requests==2.33.0 PyYAML==6.0.3
```

Expected: устанавливается без ошибок (версии подобраны совпадающими с тем, что уже стоит в венве Hermes на сервере — см. разведку перед этим планом).

- [ ] **Step 2: Дополнить `.gitignore`**

Добавить в конец `/home/deploy/hermes-cn-ru/.gitignore`:

```
# Питон-мусор (плагин project_index)
__pycache__/
*.pyc
```

- [ ] **Step 3: Создать структуру каталогов в репозитории**

```bash
mkdir -p /home/deploy/hermes-cn-ru/hermes-plugins/project_index
mkdir -p /home/deploy/hermes-cn-ru/hermes-plugins/tests
```

- [ ] **Step 4: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add .gitignore
git commit -m "chore: gitignore для питон-мусора плагина project_index"
```

(Пустые каталоги `hermes-plugins/` git не коммитит — появятся в следующем таске вместе с первым файлом.)

---

## Task 1: Слой хранения — `storage.py`

**Files:**
- Create: `hermes-plugins/project_index/storage.py`
- Create: `hermes-plugins/project_index/__init__.py` (пока пустой — просто чтобы пакет был импортируемым в тестах; наполнится в Task 5)
- Test: `hermes-plugins/tests/conftest.py`
- Test: `hermes-plugins/tests/test_storage.py`

**Interfaces:**
- Produces: `get_connection(db_path: str) -> sqlite3.Connection`, `init_db(conn)`, `pack_embedding(vector: list[float]) -> bytes`, `unpack_embedding(blob: bytes) -> list[float]`, `upsert_project(conn, path, title, tags, status, embedding, updated_at)`, `get_project(conn, path) -> dict | None`, `list_projects_for_user(conn, workspace_root, user) -> list[dict]`, `rename_path(conn, old_path, new_path)`, `delete_project(conn, path)`, `cosine_similarity(a, b) -> float`, `search_similar(conn, workspace_root, user, query_embedding, top_k=5) -> list[dict]`. Все эти имена и сигнатуры используются в Task 3/4 — не менять без синхронной правки там.

- [ ] **Step 1: Написать `conftest.py`**

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
```

- [ ] **Step 2: Написать падающий тест `test_storage.py`**

```python
import pytest

from project_index import storage


def test_upsert_and_get_project_roundtrip(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(
        conn,
        path="/workspace/dem/ALL/2026-01-01_test",
        title="Тестовый проект",
        tags=["excel", "работа"],
        status="active",
        embedding=[0.1, 0.2, 0.3],
        updated_at="2026-01-01T00:00:00",
    )
    row = storage.get_project(conn, "/workspace/dem/ALL/2026-01-01_test")
    assert row["title"] == "Тестовый проект"
    assert row["tags"] == ["excel", "работа"]
    assert row["status"] == "active"
    assert row["embedding"] == pytest.approx([0.1, 0.2, 0.3], rel=1e-5)
    assert row["updated_at"] == "2026-01-01T00:00:00"


def test_upsert_overwrites_existing_row(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/p/a", "старое", [], "active", None, "2026-01-01T00:00:00")
    storage.upsert_project(conn, "/p/a", "новое", ["x"], "archived", [1.0, 0.0], "2026-01-02T00:00:00")
    row = storage.get_project(conn, "/p/a")
    assert row["title"] == "новое"
    assert row["tags"] == ["x"]
    assert row["status"] == "archived"
    assert row["embedding"] == pytest.approx([1.0, 0.0])


def test_get_project_missing_returns_none(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    assert storage.get_project(conn, "/nope") is None


def test_upsert_without_embedding_leaves_it_none(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/p/b", "название", [], "active", None, "2026-01-01T00:00:00")
    row = storage.get_project(conn, "/p/b")
    assert row["embedding"] is None


def test_rename_path_moves_the_row(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/old/path", "т", [], "active", [1.0], "2026-01-01T00:00:00")
    storage.rename_path(conn, "/old/path", "/new/path")
    assert storage.get_project(conn, "/old/path") is None
    assert storage.get_project(conn, "/new/path")["title"] == "т"


def test_list_projects_for_user_filters_by_prefix(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/x", "dem-x", [], "active", None, "t")
    storage.upsert_project(conn, "/workspace/dem/1С/y", "dem-y", [], "active", None, "t")
    storage.upsert_project(conn, "/workspace/rost/ALL/z", "rost-z", [], "active", None, "t")
    dem_projects = storage.list_projects_for_user(conn, "/workspace", "dem")
    assert {p["path"] for p in dem_projects} == {"/workspace/dem/ALL/x", "/workspace/dem/1С/y"}


def test_cosine_similarity_known_values():
    assert storage.cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert storage.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert storage.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert storage.cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_search_similar_orders_by_score_and_respects_top_k(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/close", "близко", [], "active", [1.0, 0.0], "t")
    storage.upsert_project(conn, "/workspace/dem/ALL/far", "далеко", [], "active", [0.0, 1.0], "t")
    storage.upsert_project(conn, "/workspace/dem/ALL/mid", "средне", [], "active", [0.7, 0.7], "t")
    storage.upsert_project(conn, "/workspace/dem/ALL/no-embedding", "без эмбеддинга", [], "active", None, "t")
    results = storage.search_similar(conn, "/workspace", "dem", [1.0, 0.0], top_k=2)
    assert [r["path"] for r in results] == [
        "/workspace/dem/ALL/close",
        "/workspace/dem/ALL/mid",
    ]
```

- [ ] **Step 3: Запустить тесты — убедиться, что падают из-за отсутствия `storage.py`**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pytest hermes-plugins/tests/test_storage.py -v
```

Expected: `ModuleNotFoundError: No module named 'project_index.storage'` (или похожее — модуля ещё нет).

- [ ] **Step 4: Написать `hermes-plugins/project_index/__init__.py`** (пустой, только докстрока-плейсхолдер — наполнится в Task 5)

```python
"""Hermes plugin: per-user project index (see Task 5 for register())."""
```

- [ ] **Step 5: Написать `hermes-plugins/project_index/storage.py`**

```python
"""SQLite-backed storage for project embeddings — pure Python, no numpy.

One row per project, keyed by absolute path (path validation/resolution
lives in core.py, not here). Cosine similarity is computed in plain
Python; at the expected scale (thousands of projects, not millions) this
is fast enough and avoids a numpy/sqlite-vec dependency that isn't
already installed on the Hermes venv this plugin runs in (numpy is only
pulled in by Hermes's own optional `voice` extra).
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Optional


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            path TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            tags TEXT NOT NULL,
            status TEXT NOT NULL,
            embedding BLOB,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def pack_embedding(vector: list) -> bytes:
    import struct

    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_embedding(blob: bytes) -> list:
    import struct

    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


def upsert_project(
    conn: sqlite3.Connection,
    path: str,
    title: str,
    tags: list,
    status: str,
    embedding: Optional[list],
    updated_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO projects (path, title, tags, status, embedding, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            title=excluded.title,
            tags=excluded.tags,
            status=excluded.status,
            embedding=excluded.embedding,
            updated_at=excluded.updated_at
        """,
        (
            path,
            title,
            json.dumps(tags, ensure_ascii=False),
            status,
            pack_embedding(embedding) if embedding is not None else None,
            updated_at,
        ),
    )
    conn.commit()


def rename_path(conn: sqlite3.Connection, old_path: str, new_path: str) -> None:
    conn.execute("UPDATE projects SET path = ? WHERE path = ?", (new_path, old_path))
    conn.commit()


def delete_project(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM projects WHERE path = ?", (path,))
    conn.commit()


def get_project(conn: sqlite3.Connection, path: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM projects WHERE path = ?", (path,)).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def list_projects_for_user(conn: sqlite3.Connection, workspace_root: str, user: str) -> list:
    prefix = f"{workspace_root.rstrip('/')}/{user}/"
    rows = conn.execute("SELECT * FROM projects").fetchall()
    return [_row_to_dict(r) for r in rows if r["path"].startswith(prefix)]


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "path": row["path"],
        "title": row["title"],
        "tags": json.loads(row["tags"]),
        "status": row["status"],
        "embedding": unpack_embedding(row["embedding"]) if row["embedding"] is not None else None,
        "updated_at": row["updated_at"],
    }


def cosine_similarity(a: list, b: list) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_similar(
    conn: sqlite3.Connection,
    workspace_root: str,
    user: str,
    query_embedding: list,
    top_k: int = 5,
) -> list:
    candidates = [
        p for p in list_projects_for_user(conn, workspace_root, user)
        if p["embedding"] is not None
    ]
    scored = [
        {**p, "score": cosine_similarity(query_embedding, p["embedding"])}
        for p in candidates
    ]
    scored.sort(key=lambda p: p["score"], reverse=True)
    return scored[:top_k]
```

- [ ] **Step 6: Запустить тесты — все должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pytest hermes-plugins/tests/test_storage.py -v
```

Expected: `8 passed`.

- [ ] **Step 7: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-plugins/
git commit -m "feat(project-index): слой хранения — SQLite + косинус чистым Python"
```

---

## Task 2: Клиент wormsoft.ru — `embeddings.py`

**Files:**
- Create: `hermes-plugins/project_index/embeddings.py`
- Test: `hermes-plugins/tests/test_embeddings.py`

**Interfaces:**
- Consumes: ничего из Task 1.
- Produces: `EMBEDDING_MODEL: str`, `EMBEDDING_URL: str`, `CreditsExhausted(Exception)`, `TransientEmbeddingError(Exception)`, `fetch_embedding(text: str, api_key: str) -> list[float] | None` — **никогда не бросает исключение**, возвращает `None` при неустранимой ошибке. Используется в Task 3/4.

- [ ] **Step 1: Написать падающий тест**

```python
import requests

from project_index import embeddings


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


def test_fetch_embedding_success(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return _FakeResponse(200, {
            "object": "list",
            "data": [{"object": "embedding", "embedding": [0.1, 0.2, 0.3], "index": 0}],
            "model": embeddings.EMBEDDING_MODEL,
        })

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    result = embeddings.fetch_embedding("текст запроса", "fake-key")
    assert result == [0.1, 0.2, 0.3]
    assert len(calls) == 1
    url, headers, payload, _timeout = calls[0]
    assert url == embeddings.EMBEDDING_URL
    assert headers["Authorization"] == "Bearer fake-key"
    assert payload == {"model": embeddings.EMBEDDING_MODEL, "content": "текст запроса"}


def test_fetch_embedding_credits_exhausted_no_retry(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(1)
        return _FakeResponse(429, text="Error: user reached the limit")

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    result = embeddings.fetch_embedding("текст", "fake-key")
    assert result is None
    assert len(calls) == 1


def test_fetch_embedding_rate_limit_retries_once_then_gives_up(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(1)
        return _FakeResponse(429, text="too many requests")

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    monkeypatch.setattr(embeddings.time, "sleep", lambda seconds: None)
    result = embeddings.fetch_embedding("текст", "fake-key")
    assert result is None
    assert len(calls) == 2


def test_fetch_embedding_rate_limit_retry_succeeds(monkeypatch):
    responses = [
        _FakeResponse(429, text="too many requests"),
        _FakeResponse(200, {"data": [{"embedding": [1.0]}]}),
    ]

    def fake_post(url, headers, json, timeout):
        return responses.pop(0)

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    monkeypatch.setattr(embeddings.time, "sleep", lambda seconds: None)
    result = embeddings.fetch_embedding("текст", "fake-key")
    assert result == [1.0]


def test_fetch_embedding_server_error_retries_once(monkeypatch):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(1)
        return _FakeResponse(500, text="internal error")

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    monkeypatch.setattr(embeddings.time, "sleep", lambda seconds: None)
    result = embeddings.fetch_embedding("текст", "fake-key")
    assert result is None
    assert len(calls) == 2


def test_fetch_embedding_network_error_returns_none(monkeypatch):
    def fake_post(url, headers, json, timeout):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(embeddings.requests, "post", fake_post)
    result = embeddings.fetch_embedding("текст", "fake-key")
    assert result is None
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pytest hermes-plugins/tests/test_embeddings.py -v
```

Expected: `ModuleNotFoundError: No module named 'project_index.embeddings'`.

- [ ] **Step 3: Написать `hermes-plugins/project_index/embeddings.py`**

```python
"""wormsoft.ru embeddings client — single supported model, explicit error taxonomy.

Implements the error matrix from docs/wormsoft-api.md (hermes-cn-ru repo):
a 429 "user reached the limit" means subscription-window credits are
gone (retrying won't help within this call); a 429 without that message
is a rate limit (120 req/min on the Payed tier), and 500 is a transient
upstream failure — both of those are worth exactly one retry.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

EMBEDDING_URL = "https://ai.wormsoft.ru/api/gpt/embedding"
EMBEDDING_MODEL = "qwen/qwen3-embedding:8b"
_TIMEOUT_SECONDS = 20.0
_RETRY_DELAY_SECONDS = 4.0


class CreditsExhausted(Exception):
    """429 'user reached the limit' — subscription window credits are gone."""


class TransientEmbeddingError(Exception):
    """Rate limit (429 without the credits message) or 500 — worth one retry."""


def _request_embedding(text: str, api_key: str) -> list:
    response = requests.post(
        EMBEDDING_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"model": EMBEDDING_MODEL, "content": text},
        timeout=_TIMEOUT_SECONDS,
    )
    if response.status_code == 429:
        body_text = (response.text or "").lower()
        if "reached the limit" in body_text:
            raise CreditsExhausted(response.text)
        raise TransientEmbeddingError(f"rate limited: {response.text}")
    if response.status_code >= 500:
        raise TransientEmbeddingError(f"server error {response.status_code}: {response.text}")
    response.raise_for_status()
    data = response.json()
    return data["data"][0]["embedding"]


def fetch_embedding(text: str, api_key: str) -> Optional[list]:
    """Fetch an embedding, tolerating transient failures.

    Never raises — returns None when the embedding could not be
    obtained, so callers can persist the project without an embedding
    rather than blocking on wormsoft.ru availability.
    """
    try:
        return _request_embedding(text, api_key)
    except CreditsExhausted:
        return None
    except TransientEmbeddingError:
        time.sleep(_RETRY_DELAY_SECONDS)
        try:
            return _request_embedding(text, api_key)
        except Exception:
            return None
    except requests.RequestException:
        return None
```

- [ ] **Step 4: Запустить тесты — все должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pytest hermes-plugins/tests/test_embeddings.py -v
```

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-plugins/
git commit -m "feat(project-index): клиент wormsoft.ru с политикой ретраев по матрице ошибок"
```

---

## Task 3: `core.py` — парсинг about.md, валидация путей, `index_update`/`search_similar`

**Files:**
- Create: `hermes-plugins/project_index/core.py`
- Test: `hermes-plugins/tests/test_core.py`

**Interfaces:**
- Consumes: `storage.get_connection/upsert_project/search_similar` (Task 1), `embeddings.fetch_embedding` (Task 2).
- Produces: `WORKSPACE_ROOT: str`, `DB_PATH: str`, `ProjectIndexError(Exception)`, `parse_about_md(text: str) -> dict` (keys: `title`, `description`, `tags`, `status`), `resolve_project_path(user, project_path, workspace_root=WORKSPACE_ROOT) -> str`, `index_update(user, project_path, workspace_root=WORKSPACE_ROOT, db_path=DB_PATH, api_key=None) -> dict` (keys: `path`, `indexed`, `message`), `search_similar(user, query, top_k=5, workspace_root=WORKSPACE_ROOT, db_path=DB_PATH, api_key=None) -> dict` (keys: `results`, `message`). Все используются в Task 4 (`move_project`/`reindex_all` через `index_update`) и в Task 5 (обёртки инструментов).

- [ ] **Step 1: Написать падающий тест**

```python
import pytest

from project_index import core


ABOUT_MD_FULL = """---
tags: [excel, работа]
status: active
---

# Название проекта
Учёт стройматериалов для гаража

# Краткое описание
Ведём таблицу закупок и остатков по стройке гаража

# Опорные точки
- начали с чистого листа

# На чём остановились
Заказали цемент
"""

ABOUT_MD_NO_FRONTMATTER = """
# Название проекта
Без фронтматтера

# Краткое описание
Проверяем дефолты
"""

ABOUT_MD_NO_TITLE = """
# Краткое описание
Нет названия — должно упасть
"""


def test_parse_about_md_full():
    result = core.parse_about_md(ABOUT_MD_FULL)
    assert result["title"] == "Учёт стройматериалов для гаража"
    assert result["description"] == "Ведём таблицу закупок и остатков по стройке гаража"
    assert result["tags"] == ["excel", "работа"]
    assert result["status"] == "active"


def test_parse_about_md_defaults_without_frontmatter():
    result = core.parse_about_md(ABOUT_MD_NO_FRONTMATTER)
    assert result["title"] == "Без фронтматтера"
    assert result["description"] == "Проверяем дефолты"
    assert result["tags"] == []
    assert result["status"] == "active"


def test_parse_about_md_missing_title_raises():
    with pytest.raises(core.ProjectIndexError):
        core.parse_about_md(ABOUT_MD_NO_TITLE)


def test_resolve_project_path_accepts_path_inside_user_root(tmp_path):
    (tmp_path / "dem" / "ALL" / "proj").mkdir(parents=True)
    resolved = core.resolve_project_path("dem", "dem/ALL/proj", workspace_root=str(tmp_path))
    assert resolved == str(tmp_path / "dem" / "ALL" / "proj")


def test_resolve_project_path_rejects_other_user(tmp_path):
    (tmp_path / "dem").mkdir()
    (tmp_path / "rost").mkdir()
    with pytest.raises(core.ProjectIndexError):
        core.resolve_project_path("dem", "rost/ALL/proj", workspace_root=str(tmp_path))


def test_resolve_project_path_rejects_traversal(tmp_path):
    (tmp_path / "dem").mkdir()
    with pytest.raises(core.ProjectIndexError):
        core.resolve_project_path("dem", "dem/../rost/x", workspace_root=str(tmp_path))


def _write_project(tmp_path, rel_dir, about_content=ABOUT_MD_FULL):
    project_dir = tmp_path / rel_dir
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(about_content, encoding="utf-8")
    return project_dir


def test_index_update_without_api_key_still_upserts_without_embedding(tmp_path):
    _write_project(tmp_path, "dem/ALL/proj")
    db_path = str(tmp_path / "index.db")
    result = core.index_update(
        "dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path, api_key=None
    )
    assert result["indexed"] is False
    assert "не пересчитан" in result["message"]


def test_index_update_with_fake_embedding(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/proj")
    db_path = str(tmp_path / "index.db")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: [0.5, 0.5])
    result = core.index_update(
        "dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path, api_key="key"
    )
    assert result["indexed"] is True
    conn = core.storage.get_connection(db_path)
    row = core.storage.get_project(conn, result["path"])
    assert row["title"] == "Учёт стройматериалов для гаража"
    assert row["embedding"] == pytest.approx([0.5, 0.5])


def test_index_update_missing_about_md_raises(tmp_path):
    (tmp_path / "dem" / "ALL" / "empty").mkdir(parents=True)
    with pytest.raises(core.ProjectIndexError):
        core.index_update(
            "dem", "dem/ALL/empty", workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db")
        )


def test_search_similar_without_api_key_raises(tmp_path):
    with pytest.raises(core.ProjectIndexError):
        core.search_similar(
            "dem", "запрос", workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"), api_key=None
        )


def test_search_similar_returns_ranked_results(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/close")
    _write_project(tmp_path, "dem/ALL/far")
    db_path = str(tmp_path / "index.db")

    fake_vectors = {"dem/ALL/close": [1.0, 0.0], "dem/ALL/far": [0.0, 1.0], "запрос про гараж": [1.0, 0.0]}
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: fake_vectors[text if text in fake_vectors else text])

    for rel in ("dem/ALL/close", "dem/ALL/far"):
        monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key, rel=rel: fake_vectors[rel])
        core.index_update("dem", rel, workspace_root=str(tmp_path), db_path=db_path, api_key="key")

    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: [1.0, 0.0])
    result = core.search_similar("dem", "запрос про гараж", workspace_root=str(tmp_path), db_path=db_path, api_key="key")
    assert result["results"][0]["path"].endswith("dem/ALL/close")
    assert result["message"] == ""


def test_search_similar_wormsoft_down_returns_empty_with_message(tmp_path, monkeypatch):
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)
    result = core.search_similar(
        "dem", "запрос", workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"), api_key="key"
    )
    assert result["results"] == []
    assert "недоступен" in result["message"]
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pytest hermes-plugins/tests/test_core.py -v
```

Expected: `ModuleNotFoundError: No module named 'project_index.core'`.

- [ ] **Step 3: Написать `hermes-plugins/project_index/core.py`** (часть 1 — без `move_project`/`reindex_all`, они добавляются в Task 4 этим же файлом)

```python
"""Core project-index logic — no Hermes types here.

Deliberately plain functions (str/dict/list in, dict/exception out) so a
future caller (the planned web backend, see the project-index design
doc's "Проверено на реальном сервере" section) can load this module
directly, without going through Hermes's tool-dispatch/LLM loop — there
is no such direct-call path in Hermes today.
"""
from __future__ import annotations

import datetime
import os
import re
from pathlib import Path
from typing import Optional

import yaml

from . import embeddings, storage

WORKSPACE_ROOT = "/home/hermes/workspace"
DB_PATH = str(Path(__file__).resolve().parent / "index.db")

_SECTION_HEADER_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_")

_TITLE_SECTION = "Название проекта"
_DESCRIPTION_SECTION = "Краткое описание"


class ProjectIndexError(Exception):
    """Raised for expected, user-facing failures (bad path, collision, missing fields)."""


def _split_sections(body: str) -> dict:
    matches = list(_SECTION_HEADER_RE.finditer(body))
    sections = {}
    for i, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[name] = body[start:end].strip()
    return sections


def parse_about_md(text: str) -> dict:
    frontmatter: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1]) or {}
            body = parts[2]

    sections = _split_sections(body)
    title = sections.get(_TITLE_SECTION, "").strip()
    description = sections.get(_DESCRIPTION_SECTION, "").strip()
    if not title:
        raise ProjectIndexError(f"about.md: отсутствует секция '{_TITLE_SECTION}'")
    if not description:
        raise ProjectIndexError(f"about.md: отсутствует секция '{_DESCRIPTION_SECTION}'")

    return {
        "title": title,
        "description": description,
        "tags": list(frontmatter.get("tags") or []),
        "status": str(frontmatter.get("status") or "active"),
    }


def resolve_project_path(user: str, project_path: str, workspace_root: str = WORKSPACE_ROOT) -> str:
    root = os.path.realpath(workspace_root)
    user_root = os.path.join(root, user)
    candidate = os.path.realpath(os.path.join(root, project_path))
    if candidate != user_root and not candidate.startswith(user_root + os.sep):
        raise ProjectIndexError(f"'{project_path}' не принадлежит пространству пользователя '{user}'")
    return candidate


def _about_md_path(project_dir: str) -> str:
    return os.path.join(project_dir, "about.md")


def _read_about(project_dir: str) -> dict:
    about_path = _about_md_path(project_dir)
    if not os.path.isfile(about_path):
        raise ProjectIndexError(f"about.md не найден: {about_path}")
    with open(about_path, "r", encoding="utf-8") as fh:
        return parse_about_md(fh.read())


def _embed_text(about: dict) -> str:
    tags_text = ", ".join(about["tags"])
    return f"{about['title']}\n{about['description']}\n{tags_text}"


def index_update(
    user: str,
    project_path: str,
    workspace_root: str = WORKSPACE_ROOT,
    db_path: str = DB_PATH,
    api_key: Optional[str] = None,
) -> dict:
    resolved = resolve_project_path(user, project_path, workspace_root)
    about = _read_about(resolved)
    api_key = api_key or os.environ.get("WORMSOFT_API_KEY")

    embedding = None
    if api_key:
        embedding = embeddings.fetch_embedding(_embed_text(about), api_key)

    conn = storage.get_connection(db_path)
    try:
        storage.upsert_project(
            conn,
            path=resolved,
            title=about["title"],
            tags=about["tags"],
            status=about["status"],
            embedding=embedding,
            updated_at=datetime.datetime.utcnow().isoformat(),
        )
    finally:
        conn.close()

    indexed = embedding is not None
    return {
        "path": resolved,
        "indexed": indexed,
        "message": (
            "проиндексировано" if indexed
            else "эмбеддинг не пересчитан (wormsoft.ru недоступен), будет проиндексировано позже"
        ),
    }


def search_similar(
    user: str,
    query: str,
    top_k: int = 5,
    workspace_root: str = WORKSPACE_ROOT,
    db_path: str = DB_PATH,
    api_key: Optional[str] = None,
) -> dict:
    api_key = api_key or os.environ.get("WORMSOFT_API_KEY")
    if not api_key:
        raise ProjectIndexError("WORMSOFT_API_KEY не задан")

    query_embedding = embeddings.fetch_embedding(query, api_key)
    if query_embedding is None:
        return {"results": [], "message": "wormsoft.ru недоступен, поиск временно невозможен"}

    conn = storage.get_connection(db_path)
    try:
        results = storage.search_similar(conn, workspace_root, user, query_embedding, top_k)
    finally:
        conn.close()

    if not results:
        return {"results": [], "message": "ничего не проиндексировано или похожего не найдено"}
    return {"results": results, "message": ""}
```

- [ ] **Step 4: Запустить тесты — все должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pytest hermes-plugins/tests/test_core.py -v
```

Expected: `11 passed`.

- [ ] **Step 5: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-plugins/
git commit -m "feat(project-index): парсинг about.md, валидация путей, index_update/search_similar"
```

---

## Task 4: `core.py` — `move_project` и `reindex_all`

**Files:**
- Modify: `hermes-plugins/project_index/core.py` (дописать в конец файла)
- Modify: `hermes-plugins/tests/test_core.py` (дописать тесты)

**Interfaces:**
- Consumes: всё из Task 3 (`resolve_project_path`, `index_update`, `_about_md_path`, `_DATE_PREFIX_RE`).
- Produces: `move_project(user, project_path, new_group=None, new_name=None, workspace_root=WORKSPACE_ROOT, db_path=DB_PATH, api_key=None) -> dict` (keys: `old_path`, `new_path`, `indexed`, `session_restart_required`), `reindex_all(user, workspace_root=WORKSPACE_ROOT, db_path=DB_PATH, api_key=None) -> dict` (keys: `indexed`, `failed`). Используются в Task 5 (обёртка `project_move`) и в Task 6 (`reindex.py`, финальный ручной тест-план).

- [ ] **Step 1: Дописать падающие тесты в `test_core.py`**

```python
def test_move_project_between_groups_with_rename(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/2026-01-01_old-name")
    db_path = str(tmp_path / "index.db")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    result = core.move_project(
        "dem", "dem/ALL/2026-01-01_old-name",
        new_group="1С", new_name="Новое имя",
        workspace_root=str(tmp_path), db_path=db_path,
    )

    assert not os.path.exists(str(tmp_path / "dem" / "ALL" / "2026-01-01_old-name"))
    new_dir = tmp_path / "dem" / "1С" / "Новое имя"
    assert new_dir.is_dir()
    about_text = (new_dir / "about.md").read_text(encoding="utf-8")
    assert "Новое имя" in about_text
    assert result["session_restart_required"] is True
    assert result["new_path"] == str(new_dir)


def test_move_project_into_all_adds_date_prefix(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/1С/накладные")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    result = core.move_project(
        "dem", "dem/1С/накладные", new_group="ALL",
        workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"),
    )
    leaf = os.path.basename(result["new_path"])
    assert core._DATE_PREFIX_RE.match(leaf)


def test_move_project_out_of_all_strips_date_prefix(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/2026-01-01_накладные")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    result = core.move_project(
        "dem", "dem/ALL/2026-01-01_накладные", new_group="1С",
        workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"),
    )
    assert os.path.basename(result["new_path"]) == "накладные"


def test_move_project_collision_raises_and_does_not_move(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/a")
    _write_project(tmp_path, "dem/1С/a")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    with pytest.raises(core.ProjectIndexError):
        core.move_project(
            "dem", "dem/ALL/a", new_group="1С",
            workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"),
        )
    assert os.path.isdir(str(tmp_path / "dem" / "ALL" / "a"))


def test_move_project_noop_call_raises(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/1С/проект")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    with pytest.raises(core.ProjectIndexError):
        core.move_project(
            "dem", "dem/1С/проект",
            workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"),
        )


def test_reindex_all_indexes_every_project_with_about_md(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/a")
    _write_project(tmp_path, "dem/1С/b")
    (tmp_path / "dem" / "ALL" / "empty").mkdir(parents=True)
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: [0.1])

    result = core.reindex_all("dem", workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"))
    assert len(result["indexed"]) == 2
    assert result["failed"] == []


def test_reindex_all_missing_user_dir_raises(tmp_path):
    with pytest.raises(core.ProjectIndexError):
        core.reindex_all("nobody", workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"))
```

Добавить `import os` наверх `test_core.py`, если его там ещё нет.

- [ ] **Step 2: Запустить — новые тесты падают (нет `move_project`/`reindex_all`)**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pytest hermes-plugins/tests/test_core.py -v
```

Expected: `AttributeError: module 'project_index.core' has no attribute 'move_project'`.

- [ ] **Step 3: Дописать в конец `hermes-plugins/project_index/core.py`**

```python
def _strip_date_prefix(name: str) -> str:
    return _DATE_PREFIX_RE.sub("", name)


def _add_date_prefix(name: str) -> str:
    if _DATE_PREFIX_RE.match(name):
        return name
    today = datetime.date.today().isoformat()
    return f"{today}_{name}"


def _rewrite_title(project_dir: str, new_title: str) -> None:
    about_path = _about_md_path(project_dir)
    with open(about_path, "r", encoding="utf-8") as fh:
        text = fh.read()

    pattern = re.compile(
        rf"(#\s+{re.escape(_TITLE_SECTION)}\s*\n)(.*?)(\n#|\Z)",
        re.DOTALL,
    )
    updated, count = pattern.subn(lambda m: m.group(1) + new_title + m.group(3), text, count=1)
    if count == 0:
        raise ProjectIndexError(f"about.md: не удалось найти секцию '{_TITLE_SECTION}' для переименования")

    with open(about_path, "w", encoding="utf-8") as fh:
        fh.write(updated)


def move_project(
    user: str,
    project_path: str,
    new_group: Optional[str] = None,
    new_name: Optional[str] = None,
    workspace_root: str = WORKSPACE_ROOT,
    db_path: str = DB_PATH,
    api_key: Optional[str] = None,
) -> dict:
    root = os.path.realpath(workspace_root)
    old_path = resolve_project_path(user, project_path, workspace_root)
    if not os.path.isdir(old_path):
        raise ProjectIndexError(f"проект не найден: {old_path}")

    old_group_dir = os.path.dirname(old_path)
    old_leaf = os.path.basename(old_path)
    old_group_name = os.path.basename(old_group_dir)
    leaving_all = old_group_name == "ALL"

    target_group = new_group if new_group is not None else old_group_name
    entering_all = target_group == "ALL"

    leaf = new_name if new_name else old_leaf
    if leaving_all and not entering_all:
        leaf = _strip_date_prefix(leaf)
    elif entering_all and not leaving_all:
        leaf = _add_date_prefix(leaf)

    new_group_dir = os.path.join(root, user, target_group)
    new_path = os.path.join(new_group_dir, leaf)

    if new_path == old_path:
        raise ProjectIndexError("не указаны new_group или new_name — нечего переносить")
    if os.path.exists(new_path):
        raise ProjectIndexError(f"в группе '{target_group}' уже есть проект с именем '{leaf}'")

    os.makedirs(new_group_dir, exist_ok=True)
    shutil.move(old_path, new_path)

    if new_name:
        _rewrite_title(new_path, new_name)

    conn = storage.get_connection(db_path)
    try:
        storage.rename_path(conn, old_path, new_path)
    finally:
        conn.close()

    index_result = index_update(
        user, os.path.relpath(new_path, root), workspace_root, db_path, api_key
    )

    return {
        "old_path": old_path,
        "new_path": new_path,
        "indexed": index_result["indexed"],
        "session_restart_required": True,
    }


def reindex_all(
    user: str,
    workspace_root: str = WORKSPACE_ROOT,
    db_path: str = DB_PATH,
    api_key: Optional[str] = None,
) -> dict:
    user_root = os.path.join(os.path.realpath(workspace_root), user)
    if not os.path.isdir(user_root):
        raise ProjectIndexError(f"пространство пользователя не найдено: {user_root}")

    indexed = []
    failed = []
    for dirpath, _dirnames, filenames in os.walk(user_root):
        if "about.md" not in filenames:
            continue
        rel_path = os.path.relpath(dirpath, os.path.realpath(workspace_root))
        try:
            result = index_update(user, rel_path, workspace_root, db_path, api_key)
            indexed.append(result["path"])
        except ProjectIndexError as exc:
            failed.append({"path": dirpath, "error": str(exc)})

    return {"indexed": indexed, "failed": failed}
```

Добавить `import shutil` в блок импортов вверху `core.py` (рядом с `import re`).

- [ ] **Step 4: Запустить тесты — все должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pytest hermes-plugins/tests/test_core.py -v
```

Expected: `17 passed`.

- [ ] **Step 5: Прогнать весь набор тестов вместе — проверить, что ничего не сломалось**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pytest hermes-plugins/tests/ -v
```

Expected: `31 passed` (8 storage + 6 embeddings + 17 core).

- [ ] **Step 6: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-plugins/
git commit -m "feat(project-index): move_project (перенос между ALL/группами) и reindex_all"
```

---

## Task 5: Регистрация инструментов — `__init__.py`, `plugin.yaml`, `reindex.py`

**Files:**
- Modify: `hermes-plugins/project_index/__init__.py` (заменить заглушку из Task 1)
- Create: `hermes-plugins/project_index/plugin.yaml`
- Create: `hermes-plugins/project_index/reindex.py`
- Test: `hermes-plugins/tests/test_register.py`

**Interfaces:**
- Consumes: `core.index_update`, `core.search_similar`, `core.move_project`, `core.reindex_all`, `core.ProjectIndexError` (все из Task 3/4).
- Produces: `register(ctx)` — вызывается напрямую Hermes-загрузчиком плагинов (см. разведку в спеке: `hermes_cli/plugins.py`, `_load_directory_module`). Ничего из этой задачи не потребляется дальнейшими тасками кода — Task 6 работает с уже собранным пакетом целиком.

- [ ] **Step 1: Написать падающий тест `test_register.py`**

```python
import project_index as plugin


class FakeCtx:
    def __init__(self):
        self.tools = {}

    def register_tool(self, name, toolset, schema, handler, requires_env=None, emoji="", **kwargs):
        self.tools[name] = {
            "toolset": toolset,
            "schema": schema,
            "handler": handler,
            "requires_env": requires_env,
            "emoji": emoji,
        }


def test_register_adds_exactly_three_tools():
    ctx = FakeCtx()
    plugin.register(ctx)
    assert set(ctx.tools) == {"project_index_update", "project_search_similar", "project_move"}


def test_each_tool_schema_is_well_formed():
    ctx = FakeCtx()
    plugin.register(ctx)
    for name, entry in ctx.tools.items():
        assert entry["schema"]["name"] == name
        assert "description" in entry["schema"]
        assert entry["schema"]["parameters"]["type"] == "object"
        assert "user" in entry["schema"]["parameters"]["properties"]
        assert "user" in entry["schema"]["parameters"]["required"]
        assert entry["requires_env"] == ["WORMSOFT_API_KEY"]


def test_handle_index_update_success(monkeypatch):
    monkeypatch.setattr(
        plugin.core, "index_update",
        lambda user, project_path: {"path": "/x", "indexed": True, "message": "проиндексировано"},
    )
    result = plugin._handle_index_update({"user": "dem", "project_path": "dem/ALL/x"})
    assert result == '{"path": "/x", "indexed": true, "message": "проиндексировано"}'


def test_handle_index_update_missing_param_returns_json_error():
    result = plugin._handle_index_update({"user": "dem"})
    assert result.startswith('{"error"')


def test_handle_search_similar_defaults_top_k(monkeypatch):
    captured = {}

    def fake_search(user, query, top_k):
        captured["top_k"] = top_k
        return {"results": [], "message": ""}

    monkeypatch.setattr(plugin.core, "search_similar", fake_search)
    plugin._handle_search_similar({"user": "dem", "query": "гараж"})
    assert captured["top_k"] == 5


def test_handle_move_wraps_project_index_error(monkeypatch):
    def fake_move(**kwargs):
        raise plugin.core.ProjectIndexError("коллизия имён")

    monkeypatch.setattr(plugin.core, "move_project", fake_move)
    result = plugin._handle_move({"user": "dem", "project_path": "dem/ALL/x"})
    assert result == '{"error": "коллизия имён"}'
```

- [ ] **Step 2: Запустить — падает (нет `register`/обработчиков)**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pytest hermes-plugins/tests/test_register.py -v
```

Expected: `AttributeError: module 'project_index' has no attribute 'register'`.

- [ ] **Step 3: Написать `hermes-plugins/project_index/__init__.py`**

```python
"""Hermes plugin: per-user project index.

Registers three agent-facing tools (project_index_update,
project_search_similar, project_move) as thin wrappers over core.py.
`project_reindex_all` is deliberately NOT registered here — it's a rare
maintenance operation (backfill / index-loss recovery), run manually via
`reindex.py`, not something the model should trigger from chat.

_tool_result/_tool_error mirror the exact JSON contract of
tools/registry.py's tool_result()/tool_error() in hermes-agent, but are
defined locally rather than imported — this plugin has zero dependency
on Hermes internals beyond ctx.register_tool() itself, so the whole
package (including this file) is importable and testable outside a
running Hermes process.
"""
from __future__ import annotations

import json

from . import core

_COMMON_USER = {
    "type": "string",
    "description": "Логин пользователя, например 'dem' или 'rost'",
}

PROJECT_INDEX_UPDATE_SCHEMA = {
    "name": "project_index_update",
    "description": (
        "Пересчитать embedding-запись проекта в индексе по его about.md "
        "(Название + Краткое описание + tags). Вызывать сразу после "
        "создания или правки about.md."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user": _COMMON_USER,
            "project_path": {
                "type": "string",
                "description": (
                    "Путь к проекту относительно корня workspace, например "
                    "'dem/ALL/2026-07-25_stroymateriali'"
                ),
            },
        },
        "required": ["user", "project_path"],
    },
}

PROJECT_SEARCH_SIMILAR_SCHEMA = {
    "name": "project_search_similar",
    "description": (
        "Найти похожие по смыслу проекты этого пользователя по описанию "
        "запроса. Использовать только по явной просьбе человека "
        "'поищи похожие темы' — не автоматически при каждом новом сообщении."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user": _COMMON_USER,
            "query": {"type": "string", "description": "Что ищем, свободным текстом"},
            "top_k": {"type": "integer", "description": "Сколько кандидатов вернуть (по умолчанию 5)"},
        },
        "required": ["user", "query"],
    },
}

PROJECT_MOVE_SCHEMA = {
    "name": "project_move",
    "description": (
        "Перенести проект между ALL и именной группой (или между группами), "
        "опционально переименовав его. Требует перезапуска сессии после "
        "переноса (меняются пути)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user": _COMMON_USER,
            "project_path": {
                "type": "string",
                "description": "Текущий путь к проекту относительно корня workspace",
            },
            "new_group": {
                "type": "string",
                "description": (
                    "Новая группа (создаётся, если не существует). Не "
                    "указывать, чтобы оставить в текущей группе"
                ),
            },
            "new_name": {
                "type": "string",
                "description": "Новое имя проекта. Не указывать, чтобы оставить прежнее",
            },
        },
        "required": ["user", "project_path"],
    },
}


def _tool_result(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)


def _tool_error(message: str) -> str:
    return json.dumps({"error": str(message)}, ensure_ascii=False)


def _handle_index_update(args: dict, **kwargs) -> str:
    try:
        result = core.index_update(user=args["user"], project_path=args["project_path"])
    except core.ProjectIndexError as exc:
        return _tool_error(str(exc))
    except KeyError as exc:
        return _tool_error(f"отсутствует обязательный параметр: {exc}")
    return _tool_result(result)


def _handle_search_similar(args: dict, **kwargs) -> str:
    try:
        result = core.search_similar(
            user=args["user"],
            query=args["query"],
            top_k=int(args.get("top_k") or 5),
        )
    except core.ProjectIndexError as exc:
        return _tool_error(str(exc))
    except KeyError as exc:
        return _tool_error(f"отсутствует обязательный параметр: {exc}")
    return _tool_result(result)


def _handle_move(args: dict, **kwargs) -> str:
    try:
        result = core.move_project(
            user=args["user"],
            project_path=args["project_path"],
            new_group=args.get("new_group"),
            new_name=args.get("new_name"),
        )
    except core.ProjectIndexError as exc:
        return _tool_error(str(exc))
    except KeyError as exc:
        return _tool_error(f"отсутствует обязательный параметр: {exc}")
    return _tool_result(result)


def register(ctx) -> None:
    ctx.register_tool(
        name="project_index_update",
        toolset="project_index",
        schema=PROJECT_INDEX_UPDATE_SCHEMA,
        handler=_handle_index_update,
        requires_env=["WORMSOFT_API_KEY"],
        emoji="🗂️",
    )
    ctx.register_tool(
        name="project_search_similar",
        toolset="project_index",
        schema=PROJECT_SEARCH_SIMILAR_SCHEMA,
        handler=_handle_search_similar,
        requires_env=["WORMSOFT_API_KEY"],
        emoji="🔍",
    )
    ctx.register_tool(
        name="project_move",
        toolset="project_index",
        schema=PROJECT_MOVE_SCHEMA,
        handler=_handle_move,
        requires_env=["WORMSOFT_API_KEY"],
        emoji="📁",
    )
```

- [ ] **Step 4: Запустить тесты — все должны пройти**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pytest hermes-plugins/tests/test_register.py -v
```

Expected: `6 passed`.

- [ ] **Step 5: Написать `hermes-plugins/project_index/plugin.yaml`**

```yaml
name: project_index
version: "1.0.0"
description: >-
  Per-user индекс проектов для архитектуры "сессия это проект":
  embeddings-поиск (project_search_similar) и организация папок
  (project_index_update, project_move) над workspace/<user>/{ALL,<Группа>}/<Проект>.
  См. docs/hermes-prj-structure.md и docs/superpowers/specs/2026-07-25-project-index-plugin-design.md
  в репозитории hermes-cn-ru.
author: "hermes-cn-ru project"
requires_env:
  - WORMSOFT_API_KEY
```

- [ ] **Step 6: Написать `hermes-plugins/project_index/reindex.py`**

```python
"""Manual maintenance script: recompute the embeddings index for every
project under a user's workspace.

Not registered as an agent tool (see the project-index design doc) —
this is a rare backfill/index-loss-recovery operation, not something
the model should be able to trigger from chat.

Run with the same interpreter Hermes uses, as a module, from the
directory that CONTAINS project_index/ (so `-m` can resolve the
package and its relative imports):

    cd ~/.hermes/plugins
    ~/.hermes/hermes-agent/venv/bin/python3 -m project_index.reindex --user dem
"""
from __future__ import annotations

import argparse
import json
import sys

from . import core


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True, help="Логин пользователя, например 'dem' или 'rost'")
    args = parser.parse_args()

    try:
        result = core.reindex_all(user=args.user)
    except core.ProjectIndexError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Прогнать весь набор тестов вместе**

```bash
/tmp/claude-1000/-home-deploy-hermes-cn-ru/3c65cd1c-ddc0-4f6f-8d3c-8d00646d6ddb/scratchpad/project-index-venv/bin/pytest hermes-plugins/tests/ -v
```

Expected: `37 passed` (31 из Task 1-4 + 6 из этой задачи).

- [ ] **Step 8: Commit**

```bash
cd /home/deploy/hermes-cn-ru
git add hermes-plugins/
git commit -m "feat(project-index): регистрация трёх agent-facing инструментов + plugin.yaml + reindex.py"
```

---

## Task 6: Развёртывание на VPS и приёмочный тест

**Files:**
- Deploy (rsync, не git): `hermes-plugins/project_index/{plugin.yaml,__init__.py,core.py,embeddings.py,storage.py,reindex.py}` → `hermes@212.115.55.116:~/.hermes/plugins/project_index/`
- Modify (на сервере, не в этом репозитории): `~/.hermes/SOUL.md`, `~/.hermes/config.yaml` (через `hermes plugins enable`, не руками)
- Modify (в этом репозитории): `docs/state.md`, `docs/changelog.md`

**Interfaces:** нет новых — это чисто операционная задача поверх уже протестированного пакета из Task 1-5.

- [ ] **Step 1: Скопировать пакет на сервер (без `tests/`, без `__pycache__`)**

```bash
rsync -av --exclude='__pycache__' --exclude='*.pyc' \
  /home/deploy/hermes-cn-ru/hermes-plugins/project_index/ \
  -e "ssh -i ~/.ssh/id_ed25519_hermes_user" \
  hermes@212.115.55.116:~/.hermes/plugins/project_index/
```

Expected: файлы `plugin.yaml`, `__init__.py`, `core.py`, `embeddings.py`, `storage.py`, `reindex.py` появились на сервере (без `index.db` — его там ещё нет, он появится сам при первом вызове `index_update`).

- [ ] **Step 2: Прогнать локальные тесты ещё раз, но интерпретатором сервера — убедиться, что реальный venv (3.11, requests 2.33.0, PyYAML 6.0.3) тоже всё принимает**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  mkdir -p /tmp/project-index-check && cd /tmp/project-index-check
  rsync -a ~/.hermes/plugins/project_index ./
'
scp -i ~/.ssh/id_ed25519_hermes_user -r hermes-plugins/tests hermes@212.115.55.116:/tmp/project-index-check/
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  ~/.hermes/hermes-agent/venv/bin/pip install --quiet pytest==9.0.2
  cd /tmp/project-index-check && ~/.hermes/hermes-agent/venv/bin/python3.11 -m pytest tests/ -v
  rm -rf /tmp/project-index-check
'
```

Expected: `37 passed` — теперь уже реальным интерпретатором и версиями библиотек, которые будут исполнять плагин в проде.

- [ ] **Step 3: Включить плагин через `hermes plugins enable` (не руками через config.yaml)**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  ~/.local/bin/hermes plugins enable project_index --no-allow-tool-override
  ~/.local/bin/hermes plugins list | grep -i project_index
'
```

Expected: строка `project_index | enabled | 1.0.0 | ... | user`.

- [ ] **Step 4: Bootstrap-папки для двух пользователей**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  mkdir -p ~/workspace/dem/ALL ~/workspace/rost/ALL
  ls -la ~/workspace/
'
```

Expected: `dem/` и `rost/` появились рядом с уже существующим `physics-tasks/`.

- [ ] **Step 5: Добавить правило переиндексации в `SOUL.md`**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 'cat ~/.hermes/SOUL.md | tail -5'
```

Прочитать текущий конец файла (чтобы не сломать форматирование), затем дописать в конец `~/.hermes/SOUL.md` через `cat >> ~/.hermes/SOUL.md << 'EOF' ... EOF` (по SSH) следующий блок:

```markdown

## Индекс проектов (project_index)

После создания или правки `about.md` в любом проекте — сразу вызови
`project_index_update(user=..., project_path=...)`, чтобы embeddings-
индекс не расходился с содержимым файла. Это общее правило для всех
проектов, не конвенция конкретной темы.
```

Выполнить и проверить:

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 "cat >> ~/.hermes/SOUL.md << 'EOF'

## Индекс проектов (project_index)

После создания или правки about.md в любом проекте — сразу вызови
project_index_update(user=..., project_path=...), чтобы embeddings-
индекс не расходился с содержимым файла. Это общее правило для всех
проектов, не конвенция конкретной темы.
EOF"
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 'tail -10 ~/.hermes/SOUL.md'
```

Expected: новый блок виден в конце файла.

- [ ] **Step 6: Перезапустить gateway, чтобы подхватил новый плагин**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  systemctl --user restart hermes-gateway.service
  sleep 2
  systemctl --user status hermes-gateway.service --no-pager | head -5
'
```

Expected: `Active: active (running)` с недавним временем старта.

- [ ] **Step 7: Ручной приёмочный тест — 5 пунктов из спека, через `hermes -z`**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
mkdir -p ~/workspace/dem/ALL/2026-99-99_test
cat > ~/workspace/dem/ALL/2026-99-99_test/about.md << "EOF"
---
tags: [тест]
status: active
---

# Название проекта
Тестовый проект для приёмки плагина

# Краткое описание
Проверяем, что project_index_update реально работает

# Опорные точки

# На чём остановились
EOF
'
```

Затем (интерактивно или через `hermes -z`, в зависимости от того, что удобнее в моменте выполнения — если `-z` не подходит для tool-calling сценария, взаимодействовать через реальный чат с ботом в Matrix/веб, раз гейтвей уже перезапущен):

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 "~/.local/bin/hermes -z 'Вызови project_index_update с user=dem и project_path=dem/ALL/2026-99-99_test'"
```

Проверить результат:

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 "sqlite3 ~/.hermes/plugins/project_index/index.db \"select path,title,status from projects where path like '%2026-99-99_test%'\""
```

Expected: одна строка с `title = Тестовый проект для приёмки плагина`, `status = active`.

Повторить аналогично оставшиеся 4 пункта тест-плана из спека (поиск похожего, перенос с коллизией, перенос без коллизии, недоступность `WORMSOFT_API_KEY`) — каждый раз через `hermes -z` с соответствующей формулировкой и проверкой результата в `index.db`/на диске. Если что-то ведёт себя не так, как в тестах Task 1-5 — это сигнал разрыва между модельным поведением (как LLM формулирует вызов инструмента) и тем, что предполагает схема; в таком случае применить systematic-debugging, а не тащить в код workaround без диагностики.

- [ ] **Step 8: Удалить тестовый проект после приёмки**

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  rm -rf ~/workspace/dem/ALL/2026-99-99_test
  sqlite3 ~/.hermes/plugins/project_index/index.db "delete from projects where path like \"%2026-99-99_test%\""
'
```

- [ ] **Step 9: Мигрировать существующий `physics-tasks`**

Написать `about.md` для него (текст — по содержимому `physics-tasks/`, посмотреть, что там реально лежит, прежде чем формулировать Название/Описание — не выдумывать вслепую), затем:

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  ls ~/workspace/physics-tasks/
'
```

(Прочитать содержимое, сформулировать about.md по факту, положить его в `~/workspace/physics-tasks/about.md`, затем:)

```bash
ssh -i ~/.ssh/id_ed25519_hermes_user hermes@212.115.55.116 '
  mv ~/workspace/physics-tasks ~/workspace/dem/ALL/2026-07-25_physics-tasks
  ~/.local/bin/hermes -z "Вызови project_index_update с user=dem и project_path=dem/ALL/2026-07-25_physics-tasks"
'
```

- [ ] **Step 10: Обновить `docs/state.md` и `docs/changelog.md` в этом репозитории**

В `state.md`: отметить под-проект A («Hermes-плагин project_index») как выполненный, со ссылкой на этот план и итог приёмочного теста; следующий шаг — под-проект B (веб-бэкенд).

В `changelog.md`: новая запись за 2026-07-25 (или актуальную дату на момент выполнения) — что реализовано, что проверено, что перенесено (`physics-tasks`).

- [ ] **Step 11: Commit и snapshot**

```bash
cd /home/deploy/hermes-cn-ru
git add docs/state.md docs/changelog.md
bash scripts/snapshot.sh "Hermes-плагин project_index реализован и выкачен на VPS — приёмочный тест пройден, physics-tasks мигрирован"
```

---

## Self-Review (сверка со спеком)

- Все три agent-facing инструмента + `project_reindex_all` как отдельный CLI — покрыто (Task 3-5).
- Явный `user` во всех инструментах — покрыто (схемы Task 5, `resolve_project_path` Task 3).
- Косинус без numpy — покрыто (Task 1, `storage.cosine_similarity`).
- Матрица ошибок wormsoft.ru (кредиты vs rate limit vs 500) — покрыто (Task 2).
- `project_move`: коллизия/дата-префикс/пересчёт индекса после переноса — покрыто (Task 4).
- Директория/пакет `project_index` (подчёркивание) — выдержано во всех тасках.
- `core.py` не зависит от Hermes-типов, импортируем отдельно от `__init__.py` — выдержано (Task 3/4 не трогают `ctx`/`tool_result`).
- Развёртывание (`hermes plugins enable`, bootstrap-папки, правило в `SOUL.md`, миграция `physics-tasks`, перезапуск gateway) — покрыто (Task 6).
- Ручной тест-план из 5 пунктов спека — покрыт (Task 6, Step 7).
