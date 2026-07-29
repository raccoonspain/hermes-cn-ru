import asyncio
import datetime as _dt
import os
import sys
import threading

import pytest

sys.path.insert(0, os.environ["PROJECT_INDEX_PLUGIN_DIR"])
from project_index import core as project_index_core  # noqa: E402

from hermes_web import workspace
from hermes_web.quickchat import Config


def _config(tmp_path):
    return Config(
        hermes_base_url="http://fake-hermes.invalid",
        hermes_api_key="fake-key",
        workspace_root=str(tmp_path / "workspace"),
        project_index_db_path=str(tmp_path / "project_index.db"),
        wormsoft_api_key=None,
    )


ABOUT_MD = """---
tags: []
status: active
---

# Название проекта
Тест

# Краткое описание
Описание

# Опорные точки

# На чём остановились
"""


def _write_project(tmp_path, config, rel_dir):
    project_dir = tmp_path / "workspace" / rel_dir
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(ABOUT_MD, encoding="utf-8")
    user = rel_dir.split("/")[0]
    project_index_core.index_update(
        user, rel_dir, workspace_root=config.workspace_root, db_path=config.project_index_db_path,
    )
    return project_dir


def test_resolve_file_path_accepts_file_inside_project(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    project_root, candidate = workspace.resolve_file_path("dem", "dem/ALL/a", "about.md", config)
    assert project_root == str(tmp_path / "workspace" / "dem" / "ALL" / "a")
    assert candidate == str(tmp_path / "workspace" / "dem" / "ALL" / "a" / "about.md")


def test_resolve_file_path_rejects_traversal_outside_project(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.resolve_file_path("dem", "dem/ALL/a", "../../etc/passwd", config)


def test_resolve_file_path_rejects_foreign_project(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(project_index_core.ProjectIndexError):
        workspace.resolve_file_path("rost", "dem/ALL/a", "about.md", config)


def test_list_tree_includes_only_existing_root_files(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert [f["name"] for f in tree["root_files"]] == ["about.md"]
    assert tree["source"] == []
    assert tree["outer"] == []
    assert tree["result"] == []


def test_list_tree_lists_nested_folders(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    nested = project_dir / "source" / "Иванов"
    nested.mkdir(parents=True)
    (nested / "2026-07-27_glava1.pdf").write_bytes(b"pdf-bytes")

    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert [f["relative_path"] for f in tree["source"]] == ["source/Иванов/2026-07-27_glava1.pdf"]
    assert tree["source"][0]["size"] == len(b"pdf-bytes")


def test_list_tree_includes_empty_subfolder_created_via_make_dir(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    workspace.make_dir("dem", "dem/ALL/a", "result", "kirik", config)

    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert tree["result"] == []
    assert tree["result_dirs"] == ["result/kirik"]
    assert tree["source_dirs"] == []
    assert tree["outer_dirs"] == []


def test_list_tree_dirs_includes_intermediate_folder_without_own_files(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    nested = project_dir / "result" / "kirik" / "3-23-29"
    nested.mkdir(parents=True)
    (nested / "solution.md").write_text("x", encoding="utf-8")

    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert tree["result_dirs"] == ["result/kirik", "result/kirik/3-23-29"]


def test_list_tree_rejects_foreign_project(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(project_index_core.ProjectIndexError):
        workspace.list_tree("rost", "dem/ALL/a", config)


def test_list_tree_rejects_bare_user_root(tmp_path):
    """Finding 4 (важное, финальное ревью): user-root проходит слой-1
    проверку resolve_project_path (это часть пространства пользователя),
    но проектом не является — про него нет about.md. Должно падать так
    же, как для несуществующего проекта, а не отдавать пустое дерево."""
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    (tmp_path / "workspace" / "dem").mkdir(parents=True, exist_ok=True)
    with pytest.raises(project_index_core.ProjectIndexError):
        workspace.list_tree("dem", "dem", config)


def test_list_tree_rejects_bare_group_dir(tmp_path):
    """То же самое для группы: dem/ALL — папка-контейнер для проектов,
    у неё самой about.md нет."""
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(project_index_core.ProjectIndexError):
        workspace.list_tree("dem", "dem/ALL", config)


def test_make_dir_rejects_bare_group_dir(tmp_path):
    """До фикса Finding 4: POST /api/projects/mkdir с path=dem/ALL (группа,
    не проект) создавал директорию прямо под user-root/группой, и та потом
    ошибочно всплывала в /api/groups как "проект". Теперь должно падать
    как для несуществующего проекта."""
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(project_index_core.ProjectIndexError):
        workspace.make_dir("dem", "dem/ALL", "source", "pwned", config)


def test_read_file_returns_bytes(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("привет", encoding="utf-8")

    result = workspace.read_file("dem", "dem/ALL/a", "source/note.txt", config)
    assert result["content"] == "привет".encode("utf-8")
    assert result["name"] == "note.txt"


def test_read_file_missing_raises(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.read_file("dem", "dem/ALL/a", "source/nope.txt", config)


@pytest.mark.asyncio
async def test_save_file_writes_content(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()

    result = await workspace.save_file("dem", "dem/ALL/a", "source/note.txt", "новый текст", config)
    assert (project_dir / "source" / "note.txt").read_text(encoding="utf-8") == "новый текст"
    assert result["reindexed"] is False


@pytest.mark.asyncio
async def test_save_file_rejects_non_editable_extension(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        await workspace.save_file("dem", "dem/ALL/a", "source/data.bin", "x", config)


@pytest.mark.asyncio
async def test_save_file_allows_path_outside_bucket(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")

    result = await workspace.save_file("dem", "dem/ALL/a", "note.txt", "текст вне бакетов", config)
    assert (project_dir / "note.txt").read_text(encoding="utf-8") == "текст вне бакетов"
    assert result["reindexed"] is False


@pytest.mark.asyncio
async def test_save_file_rejects_traversal_outside_project(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        await workspace.save_file("dem", "dem/ALL/a", "../../etc/passwd.txt", "x", config)


@pytest.mark.asyncio
async def test_save_root_about_md_triggers_reindex(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")

    calls = []

    def fake_index_update(user, project_path, **kwargs):
        calls.append((user, project_path))
        return {"path": project_path, "indexed": False, "message": "ok"}

    monkeypatch.setattr(workspace.project_index_core, "index_update", fake_index_update)

    result = await workspace.save_file("dem", "dem/ALL/a", "about.md", "новый about", config)
    assert result["reindexed"] is True
    assert calls == [("dem", "dem/ALL/a")]
    assert (project_dir / "about.md").read_text(encoding="utf-8") == "новый about"


@pytest.mark.asyncio
async def test_save_about_md_alternative_spelling_triggers_reindex(tmp_path, monkeypatch):
    # Finding 3 финального ревью (2026-07-29): проверка на reindex раньше
    # сравнивала сырой relative_path со строкой "about.md" — "./about.md"
    # (тот же файл, другое написание пути) не совпадал, и индекс молча
    # оставался устаревшим после успешного сохранения.
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")

    calls = []

    def fake_index_update(user, project_path, **kwargs):
        calls.append((user, project_path))
        return {"path": project_path, "indexed": False, "message": "ok"}

    monkeypatch.setattr(workspace.project_index_core, "index_update", fake_index_update)

    result = await workspace.save_file("dem", "dem/ALL/a", "./about.md", "новый about", config)
    assert result["reindexed"] is True
    assert calls == [("dem", "dem/ALL/a")]
    assert (project_dir / "about.md").read_text(encoding="utf-8") == "новый about"


@pytest.mark.asyncio
async def test_save_nested_about_md_does_not_trigger_reindex(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()

    calls = []
    monkeypatch.setattr(workspace.project_index_core, "index_update", lambda *a, **k: calls.append(1))

    result = await workspace.save_file("dem", "dem/ALL/a", "source/about.md", "текст", config)
    assert result["reindexed"] is False
    assert calls == []


@pytest.mark.asyncio
async def test_save_about_md_reindex_runs_off_event_loop(tmp_path, monkeypatch):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    calling_thread = threading.current_thread()
    seen = {}

    def fake_index_update(user, project_path, **kwargs):
        seen["thread"] = threading.current_thread()
        return {"path": project_path, "indexed": False, "message": "ok"}

    monkeypatch.setattr(workspace.project_index_core, "index_update", fake_index_update)
    await workspace.save_file("dem", "dem/ALL/a", "about.md", "текст", config)
    assert seen["thread"] is not calling_thread
    assert seen["thread"] is not threading.main_thread()


@pytest.mark.asyncio
async def test_save_file_ensures_ownership_before_write(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()

    calls = []
    monkeypatch.setattr(workspace.permissions, "ensure_ownership_sync", lambda root: calls.append(root))

    await workspace.save_file("dem", "dem/ALL/a", "source/note.txt", "текст", config)

    assert calls == [str(project_dir)]


def test_make_dir_ensures_ownership_before_write(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")

    calls = []
    monkeypatch.setattr(workspace.permissions, "ensure_ownership_sync", lambda root: calls.append(root))

    workspace.make_dir("dem", "dem/ALL/a", "source", "Иванов", config)

    assert calls == [str(project_dir)]


def test_save_upload_ensures_ownership_before_write(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")

    calls = []
    monkeypatch.setattr(workspace.permissions, "ensure_ownership_sync", lambda root: calls.append(root))

    workspace.save_upload("dem", "dem/ALL/a", "source", "scan.pdf", b"content", config)

    assert calls == [str(project_dir)]


def test_make_dir_creates_folder_inside_bucket(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    result = workspace.make_dir("dem", "dem/ALL/a", "source", "Иванов", config)
    assert result["relative_path"] == "source/Иванов"
    assert (project_dir / "source" / "Иванов").is_dir()


def test_make_dir_bootstraps_missing_bucket_dir(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    assert not (project_dir / "outer").exists()
    workspace.make_dir("dem", "dem/ALL/a", "outer", "новое", config)
    assert (project_dir / "outer" / "новое").is_dir()


def test_make_dir_nested_parent(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    workspace.make_dir("dem", "dem/ALL/a", "source", "Иванов", config)
    result = workspace.make_dir("dem", "dem/ALL/a", "source/Иванов", "глава1", config)
    assert result["relative_path"] == "source/Иванов/глава1"


def test_make_dir_collision_raises(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    workspace.make_dir("dem", "dem/ALL/a", "source", "Иванов", config)
    with pytest.raises(workspace.WorkspaceCollisionError):
        workspace.make_dir("dem", "dem/ALL/a", "source", "Иванов", config)


def test_make_dir_rejects_parent_outside_buckets(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.make_dir("dem", "dem/ALL/a", ".", "новая-папка", config)


def test_make_dir_rejects_bad_name(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.make_dir("dem", "dem/ALL/a", "source", "../escape", config)


def test_save_upload_adds_date_prefix(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    result = workspace.save_upload("dem", "dem/ALL/a", "source", "scan.jpg", b"jpeg-bytes", config)
    today = _dt.date.today().isoformat()
    assert result["relative_path"] == f"source/{today}_scan.jpg"
    assert result["size"] == len(b"jpeg-bytes")
    assert (project_dir / "source" / f"{today}_scan.jpg").read_bytes() == b"jpeg-bytes"


def test_save_upload_keeps_existing_date_prefix(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    result = workspace.save_upload("dem", "dem/ALL/a", "source", "2026-01-01_old.jpg", b"x", config)
    assert result["relative_path"] == "source/2026-01-01_old.jpg"


def test_save_upload_into_nested_folder(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source" / "Иванов").mkdir(parents=True)
    result = workspace.save_upload("dem", "dem/ALL/a", "source/Иванов", "glava1.pdf", b"pdf", config)
    assert result["relative_path"].startswith("source/Иванов/")


def test_save_upload_bootstraps_missing_target_dir(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    workspace.save_upload("dem", "dem/ALL/a", "source/новая-папка", "x.txt", b"x", config)
    assert (project_dir / "source" / "новая-папка").is_dir()


def test_save_upload_collision_raises(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    workspace.save_upload("dem", "dem/ALL/a", "source", "2026-01-01_old.jpg", b"x", config)
    with pytest.raises(workspace.WorkspaceCollisionError):
        workspace.save_upload("dem", "dem/ALL/a", "source", "2026-01-01_old.jpg", b"y", config)


def test_save_upload_rejects_target_outside_buckets(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.save_upload("dem", "dem/ALL/a", ".", "x.txt", b"x", config)


def test_save_upload_rejects_dangling_symlink_target(tmp_path):
    """Finding 1 (critical, финальное ревью): Hermes пишет в свою песочницу
    сам (D-004) и мог бы заранее подложить dangling symlink с именем,
    которое upload соберёт как dated_name, указывающий за пределы
    write-safe-root. Раньше os.path.exists() на такой цели возвращал
    False (dangling — файла-то нет), проверка коллизии проходила, и
    open(target, "wb") молча писал содержимое загрузки ЧЕРЕЗ линк наружу.
    С O_EXCL|O_NOFOLLOW открытие такой цели должно упасть, а сама цель
    ссылки — остаться нетронутой."""
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    escape_target = tmp_path / "outside_escape.txt"
    assert not escape_target.exists()

    today = _dt.date.today().isoformat()
    dated_name = f"{today}_pwn.txt"
    project_dir = tmp_path / "workspace" / "dem" / "ALL" / "a"
    (project_dir / "source").mkdir(parents=True, exist_ok=True)
    os.symlink(str(escape_target), str(project_dir / "source" / dated_name))

    with pytest.raises(workspace.WorkspaceError):
        workspace.save_upload("dem", "dem/ALL/a", "source", "pwn.txt", b"attacker-controlled", config)

    assert not escape_target.exists()


def test_save_upload_strips_path_from_filename(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    today = _dt.date.today().isoformat()
    result = workspace.save_upload("dem", "dem/ALL/a", "source", "../../etc/evil.txt", b"x", config)
    # basename() из имени файла убрал ../../etc/ — файл лёг прямо в source/,
    # а не по пути evil.txt из непроверенного имени.
    assert result["relative_path"] == f"source/{today}_evil.txt"
    assert (project_dir / "source" / f"{today}_evil.txt").read_bytes() == b"x"
    assert list(project_dir.glob("etc")) == []


def test_list_tree_surfaces_files_outside_buckets(tmp_path):
    """Проблема 4 (спек 2026-07-28): агент иногда кладёт готовые файлы в
    произвольную папку прямо в корне проекта, а не в result/ — такие файлы
    должны быть видны в дереве и доступны для скачивания, а не пропадать
    молча."""
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    stray_dir = project_dir / "3-kirik-3-23-29"
    stray_dir.mkdir()
    (stray_dir / "tasks.md").write_text("решение", encoding="utf-8")
    (project_dir / "loose.txt").write_text("прямо в корне", encoding="utf-8")

    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert sorted(f["relative_path"] for f in tree["misc"]) == [
        "3-kirik-3-23-29/tasks.md",
        "loose.txt",
    ]


def test_list_tree_misc_excludes_buckets_and_root_editable_files(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "x.txt").write_text("x", encoding="utf-8")

    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert tree["misc"] == []


def test_list_tree_misc_excludes_hidden_paths_inside_stray_subfolder(tmp_path):
    """Финальное ревью (Important 4): скрытые файлы/папки внутри стрей-
    подпапки (не только в корне проекта) не должны попасть в misc — иначе
    случайный 'stray/.git/' или 'stray/.venv/' обходится целиком."""
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    stray_dir = project_dir / "stray"
    stray_dir.mkdir()
    (stray_dir / "visible.txt").write_text("видно", encoding="utf-8")
    (stray_dir / ".hidden.txt").write_text("скрыто", encoding="utf-8")
    git_dir = stray_dir / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")

    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert sorted(f["relative_path"] for f in tree["misc"]) == ["stray/visible.txt"]
    assert tree["misc_truncated"] is False


def test_list_tree_misc_truncates_when_over_limit(tmp_path, monkeypatch):
    """Финальное ревью (Important 4): неограниченный обход misc может
    заблокировать event loop на случайном git clone/venv в корне проекта —
    обход должен обрываться на MISC_MAX_ENTRIES и сообщать об усечении."""
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    monkeypatch.setattr(workspace, "MISC_MAX_ENTRIES", 3)
    stray_dir = project_dir / "stray"
    stray_dir.mkdir()
    for i in range(10):
        (stray_dir / f"file{i}.txt").write_text("x", encoding="utf-8")

    tree = workspace.list_tree("dem", "dem/ALL/a", config)
    assert len(tree["misc"]) == 3
    assert tree["misc_truncated"] is True


def test_move_entry_moves_file_between_buckets(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    result = workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", "result", None, config)

    assert result["relative_path"] == "result/note.txt"
    assert (project_dir / "result" / "note.txt").read_text(encoding="utf-8") == "текст"
    assert not (project_dir / "source" / "note.txt").exists()


def test_move_entry_renames_file(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    result = workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", "source", "renamed.txt", config)

    assert result["relative_path"] == "source/renamed.txt"
    assert (project_dir / "source" / "renamed.txt").exists()
    assert not (project_dir / "source" / "note.txt").exists()


def test_move_entry_moves_folder_with_contents(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    nested = project_dir / "outer" / "topic"
    nested.mkdir(parents=True)
    (nested / "a.txt").write_text("a", encoding="utf-8")

    result = workspace.move_entry("dem", "dem/ALL/a", "outer/topic", "result", None, config)

    assert result["relative_path"] == "result/topic"
    assert (project_dir / "result" / "topic" / "a.txt").read_text(encoding="utf-8") == "a"
    assert not (project_dir / "outer" / "topic").exists()


def test_move_entry_allows_source_outside_buckets(tmp_path):
    """A2 обобщён: работает и для файлов из misc (вне source/outer/result), не только для них в result/."""
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "loose.html").write_text("<html></html>", encoding="utf-8")

    result = workspace.move_entry("dem", "dem/ALL/a", "loose.html", "result", None, config)

    assert result["relative_path"] == "result/loose.html"
    assert (project_dir / "result" / "loose.html").exists()
    assert not (project_dir / "loose.html").exists()


def test_move_entry_allows_dest_outside_buckets(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    result = workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", ".", None, config)

    assert result["relative_path"] == "note.txt"
    assert (project_dir / "note.txt").exists()


def test_move_entry_rejects_missing_source(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.move_entry("dem", "dem/ALL/a", "source/nope.txt", "result", None, config)


def test_move_entry_rejects_traversal_in_source(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.move_entry("dem", "dem/ALL/a", "../../etc/passwd", "result", None, config)


def test_move_entry_rejects_traversal_in_dest_dir(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")
    with pytest.raises(workspace.WorkspaceError):
        workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", "../../../etc", None, config)


def test_move_entry_collision_raises(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("1", encoding="utf-8")
    (project_dir / "result").mkdir()
    (project_dir / "result" / "note.txt").write_text("2", encoding="utf-8")

    with pytest.raises(workspace.WorkspaceCollisionError):
        workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", "result", None, config)


def test_move_entry_rejects_bucket_dir_itself(tmp_path):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    with pytest.raises(workspace.WorkspaceError):
        workspace.move_entry("dem", "dem/ALL/a", "source", "result", None, config)


def test_move_entry_rejects_about_md(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.move_entry("dem", "dem/ALL/a", "about.md", "result", None, config)


def test_move_entry_ensures_ownership_before_write(tmp_path, monkeypatch):
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")

    calls = []
    monkeypatch.setattr(workspace.permissions, "ensure_ownership_sync", lambda root: calls.append(root))

    workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", "result", None, config)

    assert calls == [str(project_dir)]


def test_move_entry_rejects_about_md_via_dot_slash_spelling(tmp_path):
    """Regression: ensure path normalization catches alternative spellings like ./about.md"""
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        workspace.move_entry("dem", "dem/ALL/a", "./about.md", "result", None, config)


def test_move_entry_rejects_dest_dir_that_is_a_file(tmp_path):
    """Finding 4 финального ревью (2026-07-29): os.makedirs(dest_dir_candidate,
    exist_ok=True) кидает FileExistsError, если dest_dir_candidate уже
    существует, но это файл, а не папка — раньше эта ошибка была вне
    try/except OSError вокруг os.rename и всплывала как голый 500 (см.
    handle_project_move_entry в app.py). Пользователь легко может ошибиться
    так через обычный prompt() в moveEntry() на фронтенде."""
    config = _config(tmp_path)
    project_dir = _write_project(tmp_path, config, "dem/ALL/a")
    (project_dir / "source").mkdir()
    (project_dir / "source" / "note.txt").write_text("текст", encoding="utf-8")
    (project_dir / "not_a_dir.txt").write_text("я файл, не папка", encoding="utf-8")

    with pytest.raises(workspace.WorkspaceError):
        workspace.move_entry("dem", "dem/ALL/a", "source/note.txt", "not_a_dir.txt", None, config)
