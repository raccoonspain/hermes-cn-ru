import datetime
import os
import sys

import pytest

sys.path.insert(0, os.environ["PROJECT_INDEX_PLUGIN_DIR"])
from project_index import core as project_index_core  # noqa: E402

from hermes_web import projects, storage
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


def _write_project(tmp_path, config, rel_dir, mtime=None):
    project_dir = tmp_path / "workspace" / rel_dir
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(ABOUT_MD, encoding="utf-8")
    if mtime is not None:
        os.utime(project_dir / "about.md", (mtime, mtime))
    user = rel_dir.split("/")[0]
    project_index_core.index_update(
        user, rel_dir, workspace_root=config.workspace_root, db_path=config.project_index_db_path,
    )
    return project_dir


def test_slugify_transliterates_russian_and_dashes():
    assert projects.slugify("Дом и ремонт") == "dom-i-remont"


def test_slugify_blank_name_falls_back_to_group():
    assert projects.slugify("   ") == "group"


def test_list_groups_always_includes_all(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    groups = projects.list_groups("dem", conn, config)
    assert [g["slug"] for g in groups] == ["ALL"]
    assert groups[0]["display_name"] == "ALL"
    assert groups[0]["project_count"] == 0


def test_create_group_creates_folder_and_meta(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    result = projects.create_group("dem", "Дом и ремонт", "🏠", conn, config)
    assert result["slug"] == "dom-i-remont"
    assert os.path.isdir(os.path.join(config.workspace_root, "dem", "dom-i-remont"))
    by_slug = {g["slug"]: g for g in projects.list_groups("dem", conn, config)}
    assert by_slug["dom-i-remont"]["display_name"] == "Дом и ремонт"
    assert by_slug["dom-i-remont"]["emoji"] == "🏠"


def test_create_group_dedupes_slug_collision(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    projects.create_group("dem", "IT", "🖥️", conn, config)
    second = projects.create_group("dem", "IT", "🖥️", conn, config)
    assert second["slug"] == "it-2"


def test_update_group_changes_display_name_and_pin(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    result = projects.update_group("dem", "ALL", conn, config, display_name="Неразобранное", pinned=True)
    assert result["display_name"] == "Неразобранное"
    assert result["pinned"] is True
    by_slug = {g["slug"]: g for g in projects.list_groups("dem", conn, config)}
    assert by_slug["ALL"]["display_name"] == "Неразобранное"


def test_update_group_partial_update_keeps_other_fields(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    projects.update_group("dem", "ALL", conn, config, display_name="Неразобранное", emoji="📦")
    result = projects.update_group("dem", "ALL", conn, config, pinned=True)
    assert result["display_name"] == "Неразобранное"
    assert result["emoji"] == "📦"
    assert result["pinned"] is True


def test_update_group_unknown_slug_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    with pytest.raises(projects.ProjectsError):
        projects.update_group("dem", "nope", conn, config, display_name="x")


def test_list_projects_defaults_to_month_and_active(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    old_mtime = (datetime.datetime.utcnow() - datetime.timedelta(days=400)).timestamp()
    _write_project(tmp_path, config, "dem/ALL/old", mtime=old_mtime)
    _write_project(tmp_path, config, "dem/ALL/new")

    result = projects.list_projects("dem", conn, config)
    assert {p["path"] for p in result} == {str(tmp_path / "workspace" / "dem" / "ALL" / "new")}


def test_list_projects_since_all_includes_old(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    old_mtime = (datetime.datetime.utcnow() - datetime.timedelta(days=400)).timestamp()
    _write_project(tmp_path, config, "dem/ALL/old", mtime=old_mtime)

    result = projects.list_projects("dem", conn, config, since="all", status="all")
    assert len(result) == 1


def test_list_projects_filters_by_group(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    _write_project(tmp_path, config, "dem/1С/b")

    result = projects.list_projects("dem", conn, config, group="1С", since="all", status="all")
    assert [p["group"] for p in result] == ["1С"]


def test_list_projects_unknown_since_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    with pytest.raises(projects.ProjectsError):
        projects.list_projects("dem", conn, config, since="decade")


def test_get_project_detail_returns_group_and_points(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    detail = projects.get_project_detail("dem", "dem/ALL/a", config)
    assert detail["title"] == "Тест"
    assert detail["group"] == "ALL"


@pytest.mark.asyncio
async def test_search_projects_runs_in_executor_and_delegates_to_core(tmp_path, monkeypatch):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)

    def fake_search_similar(user, query, **kwargs):
        assert user == "dem"
        assert query == "гараж"
        return {"results": [], "message": ""}

    monkeypatch.setattr(projects.project_index_core, "search_similar", fake_search_similar)
    result = await projects.search_projects("dem", "гараж", config)
    assert result == {"results": [], "message": ""}


@pytest.mark.asyncio
async def test_move_project_updates_chat_session_path(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    old_path = str(tmp_path / "workspace" / "dem" / "ALL" / "a")
    storage.create_chat_session(conn, "chat1", "dem", old_path, "web_1", created_at=1.0)

    result = await projects.move_project("dem", "dem/ALL/a", config, conn, new_group="ALL", new_name="b")

    row = storage.get_chat_session(conn, "chat1")
    assert row["project_path"] == result["new_path"]


@pytest.mark.asyncio
async def test_move_project_collision_raises(tmp_path):
    conn = storage.get_connection(str(tmp_path / "hermes-web.db"))
    config = _config(tmp_path)
    _write_project(tmp_path, config, "dem/ALL/a")
    _write_project(tmp_path, config, "dem/1С/a")

    with pytest.raises(project_index_core.ProjectIndexError):
        await projects.move_project("dem", "dem/ALL/a", config, conn, new_group="1С")
