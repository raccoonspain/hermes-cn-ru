"""Файловые операции внутри проекта для рабочего экрана
(project-workspace.html): дерево source/outer/result, чтение/сохранение
текстовых файлов, создание подпапок, загрузка вложений.

Не часть Hermes-плагина project_index — эта логика специфична для веб-
морды (агенту такое не нужно, у него прямой доступ к файловой системе
своей песочницы). sys.path-манипуляция для PROJECT_INDEX_PLUGIN_DIR
продублирована из quickchat.py/projects.py намеренно (тот же повод, см.
их докстринги — reaching into another module's private setup would be
more fragile than a few self-contained lines here).
"""
from __future__ import annotations

import datetime
import os
import sys

_PROJECT_INDEX_DIR = os.environ.get("PROJECT_INDEX_PLUGIN_DIR")
if _PROJECT_INDEX_DIR and _PROJECT_INDEX_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_INDEX_DIR)

from project_index import core as project_index_core  # noqa: E402

BUCKETS = ("source", "outer", "result")
ROOT_EDITABLE_FILES = ("about.md", "AGENTS.md", "history.md")


class WorkspaceError(Exception):
    """Raised for expected, user-facing failures (bad path, bad extension, bad name)."""


class WorkspaceCollisionError(WorkspaceError):
    """Raised when mkdir/upload target already exists — no silent auto-suffix."""


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


def resolve_file_path(user: str, project_path: str, relative_path: str, config) -> tuple[str, str]:
    """Двухслойная проверка: проект принадлежит user (слой 1, через уже
    проверенный project_index_core.resolve_project_path — там же уже
    закрыт path-traversal баг, который реально эксплуатировали в
    move_project), запрошенный файл не выходит за пределы этого
    проекта (слой 2). Возвращает (project_root, candidate), оба —
    os.path.realpath."""
    project_root = project_index_core.resolve_project_path(user, project_path, _workspace_root(config))
    candidate = os.path.realpath(os.path.join(project_root, relative_path))
    if candidate != project_root and not candidate.startswith(project_root + os.sep):
        raise WorkspaceError(f"'{relative_path}' выходит за пределы проекта")
    return project_root, candidate


def _require_within_bucket(project_root: str, candidate: str) -> None:
    for bucket in BUCKETS:
        bucket_dir = os.path.join(project_root, bucket)
        if candidate == bucket_dir or candidate.startswith(bucket_dir + os.sep):
            return
    raise WorkspaceError("путь должен быть внутри source/outer/result")


def _iso_mtime(path: str) -> str:
    return datetime.datetime.utcfromtimestamp(os.path.getmtime(path)).isoformat()


def list_tree(user: str, project_path: str, config) -> dict:
    project_root, _ = resolve_file_path(user, project_path, ".", config)

    root_files = []
    for name in ROOT_EDITABLE_FILES:
        full = os.path.join(project_root, name)
        if os.path.isfile(full):
            root_files.append({"name": name, "size": os.path.getsize(full), "mtime": _iso_mtime(full)})

    tree = {"root_files": root_files}
    for bucket in BUCKETS:
        bucket_dir = os.path.join(project_root, bucket)
        entries = []
        if os.path.isdir(bucket_dir):
            for dirpath, _dirnames, filenames in os.walk(bucket_dir):
                for filename in filenames:
                    full = os.path.join(dirpath, filename)
                    entries.append({
                        "relative_path": os.path.relpath(full, project_root),
                        "size": os.path.getsize(full),
                        "mtime": _iso_mtime(full),
                    })
        tree[bucket] = sorted(entries, key=lambda e: e["relative_path"])
    return tree
