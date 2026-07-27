import asyncio
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


def test_list_tree_rejects_foreign_project(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(project_index_core.ProjectIndexError):
        workspace.list_tree("rost", "dem/ALL/a", config)


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
async def test_save_file_rejects_path_outside_bucket(tmp_path):
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    with pytest.raises(workspace.WorkspaceError):
        await workspace.save_file("dem", "dem/ALL/a", "note.txt", "x", config)


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
