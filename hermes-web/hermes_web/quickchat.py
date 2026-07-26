"""«Быстрый чат»: создаёт проект в ALL (через project_index.core напрямую,
без похода через LLM), заводит Hermes-сессию, проксирует сообщения.

project_index — уже задеплоенный Hermes-плагин (см.
docs/superpowers/specs/2026-07-25-project-index-plugin-design.md). Мы
импортируем его core-модуль напрямую: тот спроектирован именно для этого
("future caller — the planned web backend — can load this module
directly"). PROJECT_INDEX_PLUGIN_DIR добавляется на sys.path тем, кто
собирает Config (см. run.py в Task 5 / conftest.py в тестах), не этим
модулем — чтобы quickchat.py не был жёстко привязан к переменным
окружения на верхнем уровне импорта.
"""
from __future__ import annotations

import datetime
import os
import sys
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from . import hermes_client, storage

_PROJECT_INDEX_DIR = os.environ.get("PROJECT_INDEX_PLUGIN_DIR")
if _PROJECT_INDEX_DIR and _PROJECT_INDEX_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_INDEX_DIR)

from project_index import core as project_index_core  # noqa: E402


class QuickChatError(Exception):
    """Raised for expected, user-facing failures (unknown chat session, etc.)."""


@dataclass
class Config:
    hermes_base_url: str
    hermes_api_key: str
    workspace_root: Optional[str] = None
    project_index_db_path: Optional[str] = None
    wormsoft_api_key: Optional[str] = None


ABOUT_MD_PLACEHOLDER = """---
tags: []
status: active
---

# Название проекта
{title}

# Краткое описание
Ждёт первого сообщения

# Опорные точки

# На чём остановились
"""


def _project_index_kwargs(config: Config) -> dict:
    kwargs = {}
    if config.workspace_root is not None:
        kwargs["workspace_root"] = config.workspace_root
    if config.project_index_db_path is not None:
        kwargs["db_path"] = config.project_index_db_path
    if config.wormsoft_api_key is not None:
        kwargs["api_key"] = config.wormsoft_api_key
    return kwargs


def _workspace_root(config: Config) -> str:
    return config.workspace_root or project_index_core.WORKSPACE_ROOT


async def create_quick_chat(db_conn, http_session, config: Config, user: str) -> dict:
    today = datetime.date.today().isoformat()
    slug = f"{today}_chat-{uuid.uuid4().hex[:8]}"
    project_rel_path = os.path.join(user, "ALL", slug)
    project_abs_path = os.path.join(_workspace_root(config), user, "ALL", slug)

    os.makedirs(project_abs_path, exist_ok=True)
    now_label = datetime.datetime.now().strftime("%H:%M")
    with open(os.path.join(project_abs_path, "about.md"), "w", encoding="utf-8") as fh:
        fh.write(ABOUT_MD_PLACEHOLDER.format(title=f"Новый разговор {now_label}"))

    index_result = project_index_core.index_update(user, project_rel_path, **_project_index_kwargs(config))

    hermes_session_id = f"web_{uuid.uuid4().hex}"
    await hermes_client.create_session(http_session, config.hermes_base_url, config.hermes_api_key, hermes_session_id)

    chat_session_id = uuid.uuid4().hex
    storage.create_chat_session(
        db_conn, chat_session_id, user, index_result["path"], hermes_session_id, created_at=time.time(),
    )

    return {
        "chat_session_id": chat_session_id,
        "project_path": index_result["path"],
        "hermes_session_id": hermes_session_id,
    }


def _system_message_for(project_path: str) -> str:
    return (
        f"Текущий проект: {project_path}. Все файлы для этого разговора клади "
        "в подпапки внутри этого пути (см. правило про подпапки на задачу и "
        "project_index в SOUL.md)."
    )


async def send_message(db_conn, http_session, config: Config, chat_session_id: str, text: str) -> AsyncIterator[tuple[str, dict]]:
    row = storage.get_chat_session(db_conn, chat_session_id)
    if row is None:
        raise QuickChatError(f"неизвестная сессия чата: {chat_session_id}")

    async for name, payload in hermes_client.stream_chat(
        http_session,
        config.hermes_base_url,
        config.hermes_api_key,
        row["hermes_session_id"],
        text,
        system_message=_system_message_for(row["project_path"]),
    ):
        yield name, payload

    storage.touch_chat_session(db_conn, chat_session_id, last_message_at=time.time())


async def get_history(db_conn, http_session, config: Config, chat_session_id: str) -> list:
    row = storage.get_chat_session(db_conn, chat_session_id)
    if row is None:
        raise QuickChatError(f"неизвестная сессия чата: {chat_session_id}")
    return await hermes_client.get_messages(http_session, config.hermes_base_url, config.hermes_api_key, row["hermes_session_id"])
