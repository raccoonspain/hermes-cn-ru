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
import shutil
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
