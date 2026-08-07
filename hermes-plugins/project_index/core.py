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
import uuid
from pathlib import Path
from typing import Optional

import yaml

from . import embeddings, storage

WORKSPACE_ROOT = "/home/hermes/workspace"
DB_PATH = str(Path(__file__).resolve().parent / "index.db")
TRASH_DIR_NAME = ".trash"

_SECTION_HEADER_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_")

_TITLE_SECTION = "Название проекта"
_DESCRIPTION_SECTION = "Краткое описание"
_POINTS_SECTION = "Опорные точки"
_NOW_SECTION = "На чём остановились"


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
    points = sections.get(_POINTS_SECTION, "").strip()
    now = sections.get(_NOW_SECTION, "").strip()
    if not title:
        raise ProjectIndexError(f"about.md: отсутствует секция '{_TITLE_SECTION}'")
    if not description:
        raise ProjectIndexError(f"about.md: отсутствует секция '{_DESCRIPTION_SECTION}'")

    return {
        "title": title,
        "description": description,
        "points": points,
        "now": now,
        "tags": [str(t) for t in (frontmatter.get("tags") or [])],
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


def _project_group(user: str, workspace_root: str, path: str) -> str:
    root = os.path.realpath(workspace_root)
    rel = os.path.relpath(path, os.path.join(root, user))
    return rel.split(os.sep)[0]


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

    updated_at = datetime.datetime.utcfromtimestamp(
        os.path.getmtime(_about_md_path(resolved))
    ).isoformat()

    conn = storage.get_connection(db_path)
    try:
        storage.upsert_project(
            conn,
            path=resolved,
            title=about["title"],
            description=about["description"],
            tags=about["tags"],
            status=about["status"],
            embedding=embedding,
            updated_at=updated_at,
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
    # Эмбеддинг нужен был только для scoring внутри storage.search_similar —
    # наружу (в контекст LLM и в HTTP-ответ) он не отдаётся.
    results = [
        {
            **{k: v for k, v in r.items() if k != "embedding"},
            "group": _project_group(user, workspace_root, r["path"]),
        }
        for r in results
    ]
    return {"results": results, "message": ""}


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

    # new_group/new_name приходят снаружи (в том числе из HTTP —
    # POST /api/projects/move), поэтому путь назначения валидируется тем же
    # resolve_project_path, что и исходный, и ДО любых изменений на диске:
    # иначе makedirs/shutil.move успевали унести проект в чужое пространство
    # (или за пределы workspace), а вызывающий видел лишь ошибку в конце.
    new_rel_path = os.path.join(user, target_group, leaf)
    new_path = resolve_project_path(user, new_rel_path, workspace_root)
    new_group_dir = os.path.dirname(new_path)

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


def delete_project(
    user: str,
    project_path: str,
    workspace_root: str = WORKSPACE_ROOT,
    db_path: str = DB_PATH,
) -> dict:
    root = os.path.realpath(workspace_root)
    old_path = resolve_project_path(user, project_path, workspace_root)

    conn = storage.get_connection(db_path)
    try:
        if not os.path.isfile(_about_md_path(old_path)):
            # The directory can outlive its removal from disk while still
            # having an index row (e.g. manually rm -rf'd before this
            # function existed). Self-heal: drop the ghost row instead of
            # raising, since the row is otherwise permanently stuck.
            if storage.get_project(conn, old_path) is None:
                raise ProjectIndexError(f"'{project_path}' не проект (нет about.md)")
            storage.delete_project(conn, old_path)
            return {"old_path": old_path, "trashed_path": old_path}

        user_root = os.path.join(root, user)
        trash_dir = os.path.join(user_root, TRASH_DIR_NAME)
        os.makedirs(trash_dir, exist_ok=True)

        leaf = os.path.basename(old_path)
        stamp = f"{datetime.date.today().isoformat()}_{uuid.uuid4().hex[:8]}"
        trashed_path = os.path.join(trash_dir, f"{stamp}_{leaf}")

        shutil.move(old_path, trashed_path)
        storage.delete_project(conn, old_path)
        return {"old_path": old_path, "trashed_path": trashed_path}
    finally:
        conn.close()


def _rewrite_frontmatter(project_dir: str, tags: list | None = None, status: str | None = None) -> None:
    about_path = _about_md_path(project_dir)
    with open(about_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if not text.startswith("---"):
        raise ProjectIndexError("about.md: отсутствует YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ProjectIndexError("about.md: некорректный YAML frontmatter")

    frontmatter = yaml.safe_load(parts[1]) or {}
    if tags is not None:
        frontmatter["tags"] = tags
    if status is not None:
        frontmatter["status"] = status

    new_frontmatter_text = yaml.safe_dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False)
    updated = f"---\n{new_frontmatter_text}---{parts[2]}"
    with open(about_path, "w", encoding="utf-8") as fh:
        fh.write(updated)


def update_project_metadata(
    user: str,
    project_path: str,
    tags: list | None = None,
    status: str | None = None,
    workspace_root: str = WORKSPACE_ROOT,
    db_path: str = DB_PATH,
    api_key: Optional[str] = None,
) -> dict:
    resolved = resolve_project_path(user, project_path, workspace_root)
    if not os.path.isfile(_about_md_path(resolved)):
        raise ProjectIndexError(f"'{project_path}' не проект (нет about.md)")

    _rewrite_frontmatter(resolved, tags=tags, status=status)
    index_update(user, project_path, workspace_root, db_path, api_key)
    return get_project_detail(user, project_path, workspace_root)


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
    for dirpath, dirnames, filenames in os.walk(user_root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if "about.md" not in filenames:
            continue
        rel_path = os.path.relpath(dirpath, os.path.realpath(workspace_root))
        try:
            result = index_update(user, rel_path, workspace_root, db_path, api_key)
            indexed.append(result["path"])
        except ProjectIndexError as exc:
            failed.append({"path": dirpath, "error": str(exc)})

    return {"indexed": indexed, "failed": failed}


def list_projects_for_user(
    user: str,
    workspace_root: str = WORKSPACE_ROOT,
    db_path: str = DB_PATH,
    updated_since: Optional[str] = None,
    status: Optional[str] = None,
    group: Optional[str] = None,
) -> list:
    conn = storage.get_connection(db_path)
    try:
        rows = storage.list_projects_filtered(
            conn, workspace_root, user, updated_since=updated_since, status=status, group=group,
        )
    finally:
        conn.close()
    return [{**r, "group": _project_group(user, workspace_root, r["path"])} for r in rows]


def get_project_detail(user: str, project_path: str, workspace_root: str = WORKSPACE_ROOT) -> dict:
    resolved = resolve_project_path(user, project_path, workspace_root)
    about = _read_about(resolved)
    return {**about, "path": resolved, "group": _project_group(user, workspace_root, resolved)}
