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
