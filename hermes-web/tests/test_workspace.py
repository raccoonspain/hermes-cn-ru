import os
import sys

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
