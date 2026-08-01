"""«Быстрый чат»: создаёт проект в ALL (через project_index.core напрямую,
без похода через LLM), заводит Hermes-сессию, проксирует сообщения.

project_index — уже задеплоенный Hermes-плагин (см.
docs/superpowers/specs/2026-07-25-project-index-plugin-design.md). Мы
импортируем его core-модуль напрямую: тот спроектирован именно для этого
("future caller — the planned web backend — can load this module
directly"). При импорте этого модуля мы сами читаем PROJECT_INDEX_PLUGIN_DIR
из окружения и добавляем его на sys.path, если он задан — это происходит на
уровне импорта, ещё до создания Config.
"""
from __future__ import annotations

import asyncio
import datetime
import functools
import os
import sys
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from . import hermes_client, permissions, projects, storage, workspace

_PROJECT_INDEX_DIR = os.environ.get("PROJECT_INDEX_PLUGIN_DIR")
if _PROJECT_INDEX_DIR and _PROJECT_INDEX_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_INDEX_DIR)

from project_index import core as project_index_core  # noqa: E402

import logging

logger = logging.getLogger(__name__)


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


async def create_project(db_conn, config: Config, user: str, group: str, title: str) -> dict:
    title = title.strip()
    if not title:
        raise QuickChatError("название проекта не может быть пустым")
    if not group or group.startswith(".") or "/" in group:
        raise QuickChatError(f"недопустимое имя группы: '{group}'")

    if group == "ALL":
        today = datetime.date.today().isoformat()
        leaf = f"{today}_chat-{uuid.uuid4().hex[:8]}"
    else:
        leaf = projects.slugify(title)

    # group приходит из HTTP — тот же двухслойный путь-контроль, что уже
    # проверен ревью 2026-07-26 для move_project's new_group: путь назначения
    # обязан резолвиться и проверяться ДО os.makedirs, иначе group="../rost"
    # создаёт проект в чужом пространстве пользователя.
    project_rel_path = os.path.join(user, group, leaf)
    try:
        project_abs_path = project_index_core.resolve_project_path(user, project_rel_path, _workspace_root(config))
    except project_index_core.ProjectIndexError as exc:
        raise QuickChatError(str(exc)) from exc

    if os.path.exists(project_abs_path):
        raise QuickChatError(f"в группе '{group}' уже есть проект с именем '{leaf}'")

    os.makedirs(project_abs_path, exist_ok=True)
    with open(os.path.join(project_abs_path, "about.md"), "w", encoding="utf-8") as fh:
        fh.write(ABOUT_MD_PLACEHOLDER.format(title=title))
    _backfill_project_scaffold(project_abs_path)

    loop = asyncio.get_running_loop()
    index_result = await loop.run_in_executor(
        None, functools.partial(project_index_core.index_update, user, project_rel_path, **_project_index_kwargs(config)),
    )

    return {"project_path": index_result["path"], "group": group}


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


def _sandbox_project_path(config: Config, project_path: str) -> str:
    """Файловые инструменты Hermes (write_file/read_file) при
    terminal.backend: docker реально исполняются внутри sandbox-контейнера,
    где смонтированный путь проекта — всегда /workspace/... (см.
    docker_mount_cwd_to_workspace в официальной документации Hermes), а не
    хостовый workspace_root, под которым project_path хранится в БД.
    Подтверждено живым тестом 2026-07-28: относительные пути и абсолютные
    хостовые пути write_file/read_file не понимают корректно, попадают
    мимо проекта или получают отказ — единственный надёжный вариант
    подсказать модели путь для write_file/read_file — абсолютный,
    начинающийся с /workspace."""
    root = _workspace_root(config)
    if project_path == root or project_path.startswith(root + os.sep):
        return "/workspace" + project_path[len(root):]
    return project_path


async def _new_hermes_session(http_session, config: Config) -> str:
    hermes_session_id = f"web_{uuid.uuid4().hex}"
    await hermes_client.create_session(http_session, config.hermes_base_url, config.hermes_api_key, hermes_session_id)
    return hermes_session_id


def _is_valid_result_target(result_target: str) -> bool:
    if not isinstance(result_target, str):
        return False
    if result_target == "result":
        return True
    if not result_target.startswith("result/"):
        return False
    segments = result_target[len("result/"):].split("/")
    return all(segment and segment not in (".", "..") for segment in segments)


async def create_quick_chat(db_conn, http_session, config: Config, user: str) -> dict:
    today = datetime.date.today().isoformat()
    slug = f"{today}_chat-{uuid.uuid4().hex[:8]}"
    project_rel_path = os.path.join(user, "ALL", slug)
    project_abs_path = os.path.join(_workspace_root(config), user, "ALL", slug)

    # create_session — единственный шаг здесь, который реалистично может
    # упасть (сеть/Hermes лежит), поэтому идёт первым: если он упадёт, на
    # диске/в project_index не остаётся "призрачного" проекта без сессии
    # чата. При падении на любом из следующих шагов orphan-риска нет — это
    # локальные файловые/БД операции.
    hermes_session_id = await _new_hermes_session(http_session, config)

    os.makedirs(project_abs_path, exist_ok=True)
    now_label = datetime.datetime.now().strftime("%H:%M")
    with open(os.path.join(project_abs_path, "about.md"), "w", encoding="utf-8") as fh:
        fh.write(ABOUT_MD_PLACEHOLDER.format(title=f"Новый разговор {now_label}"))
    _backfill_project_scaffold(project_abs_path)

    # project_index_core.index_update может дойти до реального HTTP-вызова
    # (эмбеддинг через wormsoft.ru, requests.post с таймаутом+ретраем — до
    # ~44с в худшем случае). aiohttp однопоточный: синхронный вызов такой
    # длины прямо в event loop замораживает ВЕСЬ процесс — не только этот
    # запрос, а всех пользователей сразу. Уносим в executor-поток.
    loop = asyncio.get_running_loop()
    index_result = await loop.run_in_executor(
        None, functools.partial(project_index_core.index_update, user, project_rel_path, **_project_index_kwargs(config)),
    )

    chat_session_id = uuid.uuid4().hex
    storage.create_chat_session(
        db_conn, chat_session_id, user, index_result["path"], hermes_session_id, created_at=time.time(),
    )

    return {
        "chat_session_id": chat_session_id,
        "project_path": index_result["path"],
        "hermes_session_id": hermes_session_id,
    }


async def get_or_open_session(db_conn, http_session, config: Config, user: str, project_path: str) -> dict:
    resolved = project_index_core.resolve_project_path(user, project_path, _workspace_root(config))
    # get_project_detail кидает ProjectIndexError, если about.md не найден —
    # значит это не проект, открывать нечего.
    project_index_core.get_project_detail(user, project_path, workspace_root=_workspace_root(config))
    _backfill_project_scaffold(resolved)

    existing = storage.get_chat_session_for_project(db_conn, user, resolved)
    if existing is not None:
        return {
            "chat_session_id": existing["id"],
            "project_path": existing["project_path"],
            "hermes_session_id": existing["hermes_session_id"],
        }

    hermes_session_id = await _new_hermes_session(http_session, config)
    chat_session_id = uuid.uuid4().hex
    storage.create_chat_session(db_conn, chat_session_id, user, resolved, hermes_session_id, created_at=time.time())
    return {"chat_session_id": chat_session_id, "project_path": resolved, "hermes_session_id": hermes_session_id}


AGENTS_MD_MAX_CHARS = 4000


def _agents_md_block(project_path: str) -> str:
    path = os.path.join(project_path, "AGENTS.md")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read(AGENTS_MD_MAX_CHARS + 1)
    except FileNotFoundError:
        return ""
    except OSError:
        logger.warning("не удалось прочитать AGENTS.md: %s", path, exc_info=True)
        return ""
    if not text.strip():
        return ""
    if len(text) > AGENTS_MD_MAX_CHARS:
        text = text[:AGENTS_MD_MAX_CHARS] + "\n[...обрезано, полный текст в AGENTS.md]"
    return f"\n\nКонвенции проекта (AGENTS.md):\n{text}"


_STATIC_CONVENTIONS_FALLBACK = (
    " Готовые файлы (решения, отчёты, сгенерированные документы) клади в "
    "подпапку result/ внутри этого проекта — оттуда их видно и можно "
    "скачать в веб-интерфейсе; произвольные файлы в корне проекта там не "
    "отображаются. Исходники — в source/, вспомогательные материалы "
    "(скачанное, промежуточное) — в outer/; внутри каждой из трёх можно "
    "заводить подпапки. После записи файла — проверь ответ инструмента: "
    "если он сообщил об ошибке или отказе, файл не сохранён, не пиши "
    "пользователю, что всё готово."
)


def _system_message_for(project_path: str, result_target: str | None = None, agents_md_block: str = "") -> str:
    message = (
        f"Текущий проект: {project_path}. "
        "Инструментам write_file/read_file передавай АБСОЛЮТНЫЙ путь, "
        f"начинающийся строго с {project_path} (например "
        f"{project_path}/result/solution.md). Путь без этого префикса "
        "резолвится не от корня текущего проекта, а от другого каталога "
        "сессии, и почти всегда попадает мимо проекта или получает отказ в "
        "записи."
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
    else:
        message += _STATIC_CONVENTIONS_FALLBACK
    return message


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


async def get_history(db_conn, http_session, config: Config, chat_session_id: str) -> list:
    row = storage.get_chat_session(db_conn, chat_session_id)
    if row is None:
        raise QuickChatError(f"неизвестная сессия чата: {chat_session_id}")
    return await hermes_client.get_messages(http_session, config.hermes_base_url, config.hermes_api_key, row["hermes_session_id"])
