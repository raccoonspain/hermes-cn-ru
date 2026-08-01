"""Группы и Проекты: слаги, серверная фильтрация по времени/статусу, поиск,
перенос. Обёртка над уже задеплоенным project_index.core — так же, как
quickchat.py, но без создания Hermes-сессий и без похода в Hermes API server
(этому модулю не нужны hermes_base_url/hermes_api_key из quickchat.Config,
только workspace_root/project_index_db_path/wormsoft_api_key).

sys.path-манипуляция для PROJECT_INDEX_PLUGIN_DIR продублирована из
quickchat.py намеренно: reaching into another module's private setup would
be more fragile than three self-contained lines here (идемпотентно — если
quickchat.py уже вставил путь, повторная вставка no-op).
"""
from __future__ import annotations

import asyncio
import datetime
import functools
import os
import re
import sys
from typing import Optional

from . import storage

_PROJECT_INDEX_DIR = os.environ.get("PROJECT_INDEX_PLUGIN_DIR")
if _PROJECT_INDEX_DIR and _PROJECT_INDEX_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_INDEX_DIR)

from project_index import core as project_index_core  # noqa: E402

ALL_GROUP_SLUG = "ALL"

TIME_RANGE_DAYS = {"week": 7, "month": 30, "quarter": 90, "half_year": 182, "year": 365}

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


class ProjectsError(Exception):
    """Raised for expected, user-facing failures (unknown group/since range)."""


def slugify(name: str) -> str:
    lowered = name.strip().lower()
    transliterated = "".join(_TRANSLIT.get(ch, ch) for ch in lowered)
    slug = re.sub(r"[^a-z0-9]+", "-", transliterated).strip("-")
    return slug or "group"


def parse_since(since: str, now: datetime.datetime) -> Optional[str]:
    if since is None or since == "all":
        return None
    days = TIME_RANGE_DAYS.get(since)
    if days is None:
        raise ProjectsError(f"неизвестный диапазон времени: {since}")
    return (now - datetime.timedelta(days=days)).isoformat()


def _workspace_root(config) -> str:
    return config.workspace_root or project_index_core.WORKSPACE_ROOT


def _project_index_kwargs(config) -> dict:
    kwargs: dict = {}
    if config.workspace_root is not None:
        kwargs["workspace_root"] = config.workspace_root
    if config.project_index_db_path is not None:
        kwargs["db_path"] = config.project_index_db_path
    if config.wormsoft_api_key is not None:
        kwargs["api_key"] = config.wormsoft_api_key
    return kwargs


def _workspace_kwargs(config) -> dict:
    """Like _project_index_kwargs but without api_key — for the read-only
    listing calls (list_projects_for_user), which take no api_key parameter
    at all (they never touch embeddings, only the already-computed SQL
    columns). Passing api_key into them would raise TypeError."""
    kwargs: dict = {}
    if config.workspace_root is not None:
        kwargs["workspace_root"] = config.workspace_root
    if config.project_index_db_path is not None:
        kwargs["db_path"] = config.project_index_db_path
    return kwargs


def _now_iso() -> str:
    return datetime.datetime.utcnow().isoformat()


def _project_counts_by_group(user: str, config) -> dict:
    all_projects = project_index_core.list_projects_for_user(user, **_workspace_kwargs(config))
    counts: dict = {}
    for p in all_projects:
        counts[p["group"]] = counts.get(p["group"], 0) + 1
    return counts


def list_groups(user: str, db_conn, config) -> list:
    root = _workspace_root(config)
    user_root = os.path.join(root, user)
    disk_slugs = set()
    if os.path.isdir(user_root):
        disk_slugs = {
            name for name in os.listdir(user_root)
            if os.path.isdir(os.path.join(user_root, name)) and not name.startswith(".")
        }
    disk_slugs.add(ALL_GROUP_SLUG)

    meta_by_slug = {row["slug"]: row for row in storage.list_group_meta(db_conn, user)}
    counts = _project_counts_by_group(user, config)

    groups = []
    for slug in sorted(disk_slugs):
        meta = meta_by_slug.get(slug)
        groups.append({
            "slug": slug,
            "display_name": meta["display_name"] if meta else slug,
            "emoji": meta["emoji"] if meta else "",
            "pinned": bool(meta["pinned"]) if meta else False,
            "project_count": counts.get(slug, 0),
        })
    return groups


def create_group(user: str, name: str, emoji: str, db_conn, config) -> dict:
    existing_slugs = {g["slug"] for g in list_groups(user, db_conn, config)}
    base_slug = slugify(name)
    slug = base_slug
    i = 2
    while slug in existing_slugs:
        slug = f"{base_slug}-{i}"
        i += 1

    os.makedirs(os.path.join(_workspace_root(config), user, slug), exist_ok=False)
    display_name = name.strip()
    storage.upsert_group_meta(db_conn, user, slug, display_name, emoji, False, created_at=_now_iso())
    return {"slug": slug, "display_name": display_name, "emoji": emoji, "pinned": False, "project_count": 0}


def update_group(
    user: str, slug: str, db_conn, config, display_name=None, emoji=None, pinned=None,
) -> dict:
    by_slug = {g["slug"]: g for g in list_groups(user, db_conn, config)}
    if slug not in by_slug:
        raise ProjectsError(f"неизвестная группа: {slug}")
    current = by_slug[slug]

    new_display_name = display_name if display_name is not None else current["display_name"]
    new_emoji = emoji if emoji is not None else current["emoji"]
    new_pinned = pinned if pinned is not None else current["pinned"]

    storage.upsert_group_meta(db_conn, user, slug, new_display_name, new_emoji, new_pinned, created_at=_now_iso())
    return {
        "slug": slug, "display_name": new_display_name, "emoji": new_emoji,
        "pinned": new_pinned, "project_count": current["project_count"],
    }


def list_projects(user: str, db_conn, config, group: str = "*", since: str = "month", status: str = "active") -> list:
    updated_since = parse_since(since, datetime.datetime.utcnow())
    filter_status = None if status == "all" else status
    return project_index_core.list_projects_for_user(
        user, updated_since=updated_since, status=filter_status, group=group, **_workspace_kwargs(config),
    )


def get_project_detail(user: str, project_path: str, config) -> dict:
    return project_index_core.get_project_detail(user, project_path, workspace_root=_workspace_root(config))


async def search_projects(user: str, query: str, config) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, functools.partial(project_index_core.search_similar, user, query, **_project_index_kwargs(config)),
    )


async def move_project(user: str, project_path: str, config, db_conn, new_group=None, new_name=None) -> dict:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        functools.partial(
            project_index_core.move_project, user, project_path,
            new_group=new_group, new_name=new_name, **_project_index_kwargs(config),
        ),
    )
    storage.update_chat_session_project_path(db_conn, result["old_path"], result["new_path"])
    return result


async def delete_project(user: str, project_path: str, config, db_conn) -> dict:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        functools.partial(project_index_core.delete_project, user, project_path, **_workspace_kwargs(config)),
    )
    storage.update_chat_session_project_path(db_conn, result["old_path"], result["trashed_path"])
    return result
