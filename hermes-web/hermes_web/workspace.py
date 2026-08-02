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

import asyncio
import datetime
import functools
import os
import re
import shutil
import sys

_PROJECT_INDEX_DIR = os.environ.get("PROJECT_INDEX_PLUGIN_DIR")
if _PROJECT_INDEX_DIR and _PROJECT_INDEX_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_INDEX_DIR)

from project_index import core as project_index_core  # noqa: E402

from . import permissions

BUCKETS = ("source", "outer", "result")
ROOT_EDITABLE_FILES = ("about.md", "AGENTS.md", "history.md")
EDITABLE_EXTENSIONS = (".md", ".txt")

_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_")


def _add_date_prefix(name: str) -> str:
    if _DATE_PREFIX_RE.match(name):
        return name
    today = datetime.date.today().isoformat()
    return f"{today}_{name}"


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
    os.path.realpath.

    Слой 1 сам по себе проверяет только "путь внутри пространства
    пользователя" — этого мало: любая директория под user-root (сам
    user-root, "группа" — просто подпапка без проекта внутри) тоже
    проходит эту проверку, хотя проектом не является. Поэтому здесь же
    дополнительно требуем about.md — как это уже делает
    project_index_core._read_about для get_project_detail/index_update —
    и поднимаем тот же ProjectIndexError, чтобы поведение (и HTTP-код)
    было одинаковым что для /api/projects/open, что для этих операций."""
    project_root = project_index_core.resolve_project_path(user, project_path, _workspace_root(config))
    about_path = os.path.join(project_root, "about.md")
    if not os.path.isfile(about_path):
        raise project_index_core.ProjectIndexError(f"about.md не найден: {about_path}")
    candidate = os.path.realpath(os.path.join(project_root, relative_path))
    if candidate != project_root and not candidate.startswith(project_root + os.sep):
        raise WorkspaceError(f"'{relative_path}' выходит за пределы проекта")
    return project_root, candidate


def _within_bucket(project_root: str, candidate: str) -> bool:
    for bucket in BUCKETS:
        bucket_dir = os.path.join(project_root, bucket)
        if candidate == bucket_dir or candidate.startswith(bucket_dir + os.sep):
            return True
    return False


def _require_within_bucket(project_root: str, candidate: str) -> None:
    if not _within_bucket(project_root, candidate):
        raise WorkspaceError("путь должен быть внутри source/outer/result")


def _iso_mtime(path: str) -> str:
    # Naive ISO (без офсета) парсится JS-датой как local time, а не UTC —
    # фронтенд (formatTime/computeFileMessageIndex в project-workspace.html)
    # сравнивает эту метку с timestamp'ами сообщений Hermes, которые ВСЕГДА
    # приходят с суффиксом UTC. datetime.UTC добавляет "+00:00", закрывая
    # рассинхронизацию систем отсчёта (и заодно deprecated utcfromtimestamp).
    return datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.UTC).isoformat()


MISC_MAX_ENTRIES = 2000


def _list_misc(project_root: str) -> tuple[list, bool]:
    """Модель не гарантированно кладёт готовые файлы в result/ (см.
    Проблему 4 в спеке 2026-07-28) — вместо того чтобы бороться с этим
    только промптом, показываем всё, что реально лежит в корне проекта
    и не относится к source/outer/result/служебным файлам, одним
    дополнительным разделом. Скрытые файлы и папки (начинающиеся с '.')
    пропускаем на любом уровне вложенности — не только в корне, но и
    внутри стрей-папок (например '.git', '.venv', случайно оставленные
    агентом через terminal). Обход ограничен MISC_MAX_ENTRIES — случайный
    git clone/pip install -t ./venv в корне проекта не должен грузить
    синхронным обходом event loop на каждый рефреш дерева; возвращает
    (entries, truncated)."""
    skip_names = set(BUCKETS) | set(ROOT_EDITABLE_FILES)
    entries = []
    truncated = False
    for entry_name in sorted(os.listdir(project_root)):
        if truncated:
            break
        if entry_name in skip_names or entry_name.startswith('.'):
            continue
        full = os.path.join(project_root, entry_name)
        if os.path.isfile(full):
            entries.append({
                "relative_path": entry_name,
                "size": os.path.getsize(full),
                "mtime": _iso_mtime(full),
            })
            if len(entries) >= MISC_MAX_ENTRIES:
                truncated = True
        elif os.path.isdir(full):
            for dirpath, dirnames, filenames in os.walk(full):
                dirnames[:] = [d for d in dirnames if not d.startswith('.')]
                for filename in filenames:
                    if filename.startswith('.'):
                        continue
                    fpath = os.path.join(dirpath, filename)
                    entries.append({
                        "relative_path": os.path.relpath(fpath, project_root),
                        "size": os.path.getsize(fpath),
                        "mtime": _iso_mtime(fpath),
                    })
                    if len(entries) >= MISC_MAX_ENTRIES:
                        truncated = True
                        break
                if truncated:
                    break
    entries = sorted(entries, key=lambda e: e["relative_path"])[:MISC_MAX_ENTRIES]
    return entries, truncated


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
        dirs = []
        if os.path.isdir(bucket_dir):
            for dirpath, _dirnames, filenames in os.walk(bucket_dir):
                if dirpath != bucket_dir:
                    dirs.append(os.path.relpath(dirpath, project_root))
                for filename in filenames:
                    full = os.path.join(dirpath, filename)
                    entries.append({
                        "relative_path": os.path.relpath(full, project_root),
                        "size": os.path.getsize(full),
                        "mtime": _iso_mtime(full),
                    })
        tree[bucket] = sorted(entries, key=lambda e: e["relative_path"])
        tree[f"{bucket}_dirs"] = sorted(dirs)
    misc_entries, misc_truncated = _list_misc(project_root)
    tree["misc"] = misc_entries
    tree["misc_truncated"] = misc_truncated
    return tree


def read_file(user: str, project_path: str, relative_path: str, config) -> dict:
    _, candidate = resolve_file_path(user, project_path, relative_path, config)
    if not os.path.isfile(candidate):
        raise WorkspaceError(f"файл не найден: {relative_path}")
    with open(candidate, "rb") as fh:
        content = fh.read()
    return {"path": candidate, "name": os.path.basename(candidate), "content": content}


async def save_file(user: str, project_path: str, relative_path: str, content: str, config) -> dict:
    ext = os.path.splitext(relative_path)[1].lower()
    if ext not in EDITABLE_EXTENSIONS:
        raise WorkspaceError(f"недопустимое расширение для сохранения: {ext or '(нет)'}")

    project_root, candidate = resolve_file_path(user, project_path, relative_path, config)
    permissions.ensure_ownership_sync(project_root)

    os.makedirs(os.path.dirname(candidate), exist_ok=True)
    with open(candidate, "w", encoding="utf-8") as fh:
        fh.write(content)

    reindexed = False
    if candidate == os.path.join(project_root, "about.md"):
        loop = asyncio.get_running_loop()
        # index_update может дойти до реального HTTP-вызова (эмбеддинг через
        # wormsoft.ru) — тот же повод, что уже закрыт в quickchat.create_quick_chat:
        # синхронный вызов такой длины прямо в event loop замораживает весь
        # процесс, не только этот запрос.
        await loop.run_in_executor(
            None, functools.partial(project_index_core.index_update, user, project_path, **_project_index_kwargs(config)),
        )
        reindexed = True
    return {"path": candidate, "reindexed": reindexed}


def make_dir(user: str, project_path: str, parent: str, name: str, config) -> dict:
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise WorkspaceError(f"недопустимое имя папки: '{name}'")

    project_root, parent_candidate = resolve_file_path(user, project_path, parent, config)
    permissions.ensure_ownership_sync(project_root)
    _require_within_bucket(project_root, parent_candidate)

    target = os.path.realpath(os.path.join(parent_candidate, name))
    if target != parent_candidate and not target.startswith(parent_candidate + os.sep):
        raise WorkspaceError(f"недопустимое имя папки: '{name}'")
    if os.path.exists(target):
        raise WorkspaceCollisionError(f"'{name}' уже существует в '{parent}'")

    os.makedirs(target)
    return {"relative_path": os.path.relpath(target, project_root)}


def save_upload(user: str, project_path: str, target_dir: str, filename: str, content: bytes, config) -> dict:
    safe_name = os.path.basename(filename)
    if not safe_name or safe_name in (".", ".."):
        raise WorkspaceError(f"недопустимое имя файла: '{filename}'")

    project_root, target_dir_candidate = resolve_file_path(user, project_path, target_dir, config)
    permissions.ensure_ownership_sync(project_root)
    _require_within_bucket(project_root, target_dir_candidate)

    dated_name = _add_date_prefix(safe_name)
    target = os.path.join(target_dir_candidate, dated_name)

    os.makedirs(target_dir_candidate, exist_ok=True)
    # O_EXCL|O_NOFOLLOW вместо os.path.exists()-проверки + open("wb"):
    #  - O_EXCL закрывает TOCTOU между проверкой коллизии и записью
    #    (см. make_dir/save_upload race, отмеченный в финальном ревью);
    #  - O_NOFOLLOW не даёт открыть target, если это symlink — иначе Hermes
    #    (пишет в свою песочницу сам, см. D-004) мог бы заранее подложить
    #    dangling symlink source/<та же dated_name> -> /home/hermes/.hermes/...
    #    и наш "безобидный" open("wb") записал бы содержимое загрузки через
    #    линк за пределы проекта/write-safe-root. os.path.exists() следует
    #    по символической ссылке и раньше "успешно" ловил только коллизию с
    #    реальным файлом — с dangling-целью запись проходила молча.
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    except FileExistsError:
        raise WorkspaceCollisionError(f"'{dated_name}' уже существует в '{target_dir}'")
    except OSError as exc:
        # ELOOP (symlink с O_NOFOLLOW) и прочие неожиданные ошибки открытия —
        # не даём голому OSError всплыть до HTTP-слоя как 500.
        raise WorkspaceError(f"не удалось сохранить '{dated_name}': {exc}") from exc

    with os.fdopen(fd, "wb") as fh:
        fh.write(content)

    return {"relative_path": os.path.relpath(target, project_root), "size": len(content)}


def move_entry(user: str, project_path: str, source: str, dest_dir: str, new_name: str | None, config) -> dict:
    project_root, source_candidate = resolve_file_path(user, project_path, source, config)
    permissions.ensure_ownership_sync(project_root)

    if not os.path.exists(source_candidate):
        raise WorkspaceError(f"'{source}' не найден")
    if source_candidate == project_root:
        raise WorkspaceError(f"'{source}' нельзя перемещать")
    for root_file in ROOT_EDITABLE_FILES:
        if source_candidate == os.path.join(project_root, root_file):
            raise WorkspaceError(f"'{source}' нельзя перемещать")
    for bucket in BUCKETS:
        if source_candidate == os.path.join(project_root, bucket):
            raise WorkspaceError(f"'{source}' нельзя перемещать — это сам bucket '{bucket}'")

    name = new_name if new_name else os.path.basename(source_candidate)
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        raise WorkspaceError(f"недопустимое имя: '{name}'")

    _, dest_dir_candidate = resolve_file_path(user, project_path, dest_dir, config)
    target = os.path.realpath(os.path.join(dest_dir_candidate, name))
    if target != dest_dir_candidate and not target.startswith(dest_dir_candidate + os.sep):
        raise WorkspaceError(f"недопустимое имя: '{name}'")
    if os.path.exists(target):
        raise WorkspaceCollisionError(f"'{name}' уже существует в целевой папке")

    if os.path.exists(dest_dir_candidate) and not os.path.isdir(dest_dir_candidate):
        raise WorkspaceError(f"'{dest_dir}' — не папка")
    os.makedirs(dest_dir_candidate, exist_ok=True)
    try:
        os.rename(source_candidate, target)
    except OSError as exc:
        raise WorkspaceError(f"не удалось переместить '{source}': {exc}") from exc

    return {"relative_path": os.path.relpath(target, project_root)}


def delete_entry(user: str, project_path: str, relative_path: str, config) -> dict:
    project_root, candidate = resolve_file_path(user, project_path, relative_path, config)
    literal_path = os.path.join(project_root, relative_path)

    if not os.path.lexists(literal_path):
        raise WorkspaceError(f"'{relative_path}' не найден")
    if candidate == project_root:
        raise WorkspaceError(f"'{relative_path}' нельзя удалить")
    for root_file in ROOT_EDITABLE_FILES:
        if candidate == os.path.join(project_root, root_file):
            raise WorkspaceError(f"'{relative_path}' нельзя удалить")
    for bucket in BUCKETS:
        if candidate == os.path.join(project_root, bucket):
            raise WorkspaceError(f"'{relative_path}' нельзя удалить — это сам bucket '{bucket}'")

    if not _within_bucket(project_root, candidate):
        rel_parts = os.path.relpath(candidate, project_root).split(os.sep)
        if any(part.startswith(".") for part in rel_parts):
            raise WorkspaceError(f"'{relative_path}' нельзя удалить")

    permissions.ensure_ownership_sync(project_root)

    if os.path.islink(literal_path):
        os.remove(literal_path)
        return {"relative_path": os.path.relpath(literal_path, project_root)}
    if os.path.isdir(candidate):
        shutil.rmtree(candidate)
    else:
        os.remove(candidate)
    return {"relative_path": os.path.relpath(candidate, project_root)}
