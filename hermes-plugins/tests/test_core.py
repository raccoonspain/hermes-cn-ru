import datetime
import os

import pytest

from project_index import core


ABOUT_MD_FULL = """---
tags: [excel, работа]
status: active
---

# Название проекта
Учёт стройматериалов для гаража

# Краткое описание
Ведём таблицу закупок и остатков по стройке гаража

# Опорные точки
- начали с чистого листа

# На чём остановились
Заказали цемент
"""

ABOUT_MD_NO_FRONTMATTER = """
# Название проекта
Без фронтматтера

# Краткое описание
Проверяем дефолты
"""

ABOUT_MD_NO_TITLE = """
# Краткое описание
Нет названия — должно упасть
"""


def test_parse_about_md_full():
    result = core.parse_about_md(ABOUT_MD_FULL)
    assert result["title"] == "Учёт стройматериалов для гаража"
    assert result["description"] == "Ведём таблицу закупок и остатков по стройке гаража"
    assert result["tags"] == ["excel", "работа"]
    assert result["status"] == "active"


def test_parse_about_md_defaults_without_frontmatter():
    result = core.parse_about_md(ABOUT_MD_NO_FRONTMATTER)
    assert result["title"] == "Без фронтматтера"
    assert result["description"] == "Проверяем дефолты"
    assert result["tags"] == []
    assert result["status"] == "active"


def test_parse_about_md_missing_title_raises():
    with pytest.raises(core.ProjectIndexError):
        core.parse_about_md(ABOUT_MD_NO_TITLE)


def test_resolve_project_path_accepts_path_inside_user_root(tmp_path):
    (tmp_path / "dem" / "ALL" / "proj").mkdir(parents=True)
    resolved = core.resolve_project_path("dem", "dem/ALL/proj", workspace_root=str(tmp_path))
    assert resolved == str(tmp_path / "dem" / "ALL" / "proj")


def test_resolve_project_path_rejects_other_user(tmp_path):
    (tmp_path / "dem").mkdir()
    (tmp_path / "rost").mkdir()
    with pytest.raises(core.ProjectIndexError):
        core.resolve_project_path("dem", "rost/ALL/proj", workspace_root=str(tmp_path))


def test_resolve_project_path_rejects_traversal(tmp_path):
    (tmp_path / "dem").mkdir()
    with pytest.raises(core.ProjectIndexError):
        core.resolve_project_path("dem", "dem/../rost/x", workspace_root=str(tmp_path))


def _write_project(tmp_path, rel_dir, about_content=ABOUT_MD_FULL):
    project_dir = tmp_path / rel_dir
    project_dir.mkdir(parents=True)
    (project_dir / "about.md").write_text(about_content, encoding="utf-8")
    return project_dir


def test_index_update_without_api_key_still_upserts_without_embedding(tmp_path):
    _write_project(tmp_path, "dem/ALL/proj")
    db_path = str(tmp_path / "index.db")
    result = core.index_update(
        "dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path, api_key=None
    )
    assert result["indexed"] is False
    assert "не пересчитан" in result["message"]


def test_index_update_with_fake_embedding(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/proj")
    db_path = str(tmp_path / "index.db")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: [0.5, 0.5])
    result = core.index_update(
        "dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path, api_key="key"
    )
    assert result["indexed"] is True
    conn = core.storage.get_connection(db_path)
    row = core.storage.get_project(conn, result["path"])
    assert row["title"] == "Учёт стройматериалов для гаража"
    assert row["embedding"] == pytest.approx([0.5, 0.5])


def test_index_update_missing_about_md_raises(tmp_path):
    (tmp_path / "dem" / "ALL" / "empty").mkdir(parents=True)
    with pytest.raises(core.ProjectIndexError):
        core.index_update(
            "dem", "dem/ALL/empty", workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db")
        )


def test_search_similar_without_api_key_raises(tmp_path):
    with pytest.raises(core.ProjectIndexError):
        core.search_similar(
            "dem", "запрос", workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"), api_key=None
        )


def test_search_similar_returns_ranked_results(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/close")
    _write_project(tmp_path, "dem/ALL/far")
    db_path = str(tmp_path / "index.db")

    fake_vectors = {"dem/ALL/close": [1.0, 0.0], "dem/ALL/far": [0.0, 1.0], "запрос про гараж": [1.0, 0.0]}
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: fake_vectors[text if text in fake_vectors else text])

    for rel in ("dem/ALL/close", "dem/ALL/far"):
        monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key, rel=rel: fake_vectors[rel])
        core.index_update("dem", rel, workspace_root=str(tmp_path), db_path=db_path, api_key="key")

    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: [1.0, 0.0])
    result = core.search_similar("dem", "запрос про гараж", workspace_root=str(tmp_path), db_path=db_path, api_key="key")
    assert result["results"][0]["path"].endswith("dem/ALL/close")
    assert result["message"] == ""


def test_search_similar_wormsoft_down_returns_empty_with_message(tmp_path, monkeypatch):
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)
    result = core.search_similar(
        "dem", "запрос", workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"), api_key="key"
    )
    assert result["results"] == []
    assert "недоступен" in result["message"]


def test_move_project_between_groups_with_rename(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/2026-01-01_old-name")
    db_path = str(tmp_path / "index.db")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    result = core.move_project(
        "dem", "dem/ALL/2026-01-01_old-name",
        new_group="1С", new_name="Новое имя",
        workspace_root=str(tmp_path), db_path=db_path,
    )

    assert not os.path.exists(str(tmp_path / "dem" / "ALL" / "2026-01-01_old-name"))
    new_dir = tmp_path / "dem" / "1С" / "Новое имя"
    assert new_dir.is_dir()
    about_text = (new_dir / "about.md").read_text(encoding="utf-8")
    assert "Новое имя" in about_text
    assert result["session_restart_required"] is True
    assert result["new_path"] == str(new_dir)


def test_move_project_into_all_adds_date_prefix(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/1С/накладные")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    result = core.move_project(
        "dem", "dem/1С/накладные", new_group="ALL",
        workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"),
    )
    leaf = os.path.basename(result["new_path"])
    assert core._DATE_PREFIX_RE.match(leaf)


def test_move_project_out_of_all_strips_date_prefix(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/2026-01-01_накладные")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    result = core.move_project(
        "dem", "dem/ALL/2026-01-01_накладные", new_group="1С",
        workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"),
    )
    assert os.path.basename(result["new_path"]) == "накладные"


def test_move_project_collision_raises_and_does_not_move(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/a")
    _write_project(tmp_path, "dem/1С/a")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    with pytest.raises(core.ProjectIndexError):
        core.move_project(
            "dem", "dem/ALL/a", new_group="1С",
            workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"),
        )
    assert os.path.isdir(str(tmp_path / "dem" / "ALL" / "a"))


def test_move_project_new_group_traversal_raises_and_does_not_move(tmp_path, monkeypatch):
    """new_group приходит из HTTP (POST /api/projects/move) — путь назначения
    обязан валидироваться ДО любых изменений на диске, иначе проект уезжает
    в чужое пространство, а вызывающий видит только ошибку."""
    _write_project(tmp_path, "dem/ALL/a")
    (tmp_path / "rost").mkdir()
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    with pytest.raises(core.ProjectIndexError):
        core.move_project(
            "dem", "dem/ALL/a", new_group="../rost",
            workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"),
        )

    assert os.path.isdir(str(tmp_path / "dem" / "ALL" / "a"))
    assert os.listdir(str(tmp_path / "rost")) == []


def test_move_project_new_group_escaping_workspace_root_raises(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    _write_project(workspace, "dem/ALL/a")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    with pytest.raises(core.ProjectIndexError):
        core.move_project(
            "dem", "dem/ALL/a", new_group="../../escaped",
            workspace_root=str(workspace), db_path=str(tmp_path / "index.db"),
        )

    assert os.path.isdir(str(workspace / "dem" / "ALL" / "a"))
    assert not os.path.exists(str(tmp_path / "escaped"))
    assert not os.path.exists(str(tmp_path.parent / "escaped"))


def test_move_project_new_name_traversal_raises_and_does_not_move(tmp_path, monkeypatch):
    """new_name тоже приходит из HTTP и попадает в leaf — он не должен
    позволять выйти за пределы пространства пользователя даже при
    безопасной new_group."""
    _write_project(tmp_path, "dem/1С/a")
    (tmp_path / "rost").mkdir()
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    with pytest.raises(core.ProjectIndexError):
        core.move_project(
            "dem", "dem/1С/a", new_name="../../rost/угнанный",
            workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"),
        )

    assert os.path.isdir(str(tmp_path / "dem" / "1С" / "a"))
    assert os.listdir(str(tmp_path / "rost")) == []


def test_move_project_noop_call_raises(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/1С/проект")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: None)

    with pytest.raises(core.ProjectIndexError):
        core.move_project(
            "dem", "dem/1С/проект",
            workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"),
        )


def test_reindex_all_indexes_every_project_with_about_md(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/a")
    _write_project(tmp_path, "dem/1С/b")
    (tmp_path / "dem" / "ALL" / "empty").mkdir(parents=True)
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: [0.1])

    result = core.reindex_all("dem", workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"))
    assert len(result["indexed"]) == 2
    assert result["failed"] == []


def test_reindex_all_missing_user_dir_raises(tmp_path):
    with pytest.raises(core.ProjectIndexError):
        core.reindex_all("nobody", workspace_root=str(tmp_path), db_path=str(tmp_path / "index.db"))


def test_parse_about_md_extracts_points_and_now():
    result = core.parse_about_md(ABOUT_MD_FULL)
    assert result["points"] == "- начали с чистого листа"
    assert result["now"] == "Заказали цемент"


def test_parse_about_md_missing_points_and_now_default_to_empty_string():
    result = core.parse_about_md(ABOUT_MD_NO_FRONTMATTER)
    assert result["points"] == ""
    assert result["now"] == ""


def test_index_update_uses_about_md_mtime_not_call_time(tmp_path):
    project_dir = _write_project(tmp_path, "dem/ALL/proj")
    about_path = project_dir / "about.md"
    fixed_mtime = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
    os.utime(about_path, (fixed_mtime, fixed_mtime))
    db_path = str(tmp_path / "index.db")

    result = core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path)

    conn = core.storage.get_connection(db_path)
    row = core.storage.get_project(conn, result["path"])
    assert row["updated_at"].startswith("2020-01-01")


def test_index_update_repeated_call_without_change_keeps_updated_at(tmp_path):
    project_dir = _write_project(tmp_path, "dem/ALL/proj")
    fixed_mtime = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
    os.utime(project_dir / "about.md", (fixed_mtime, fixed_mtime))
    db_path = str(tmp_path / "index.db")

    core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path)
    result = core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path)

    conn = core.storage.get_connection(db_path)
    row = core.storage.get_project(conn, result["path"])
    assert row["updated_at"].startswith("2020-01-01")


def test_index_update_stores_description(tmp_path):
    _write_project(tmp_path, "dem/ALL/proj")
    db_path = str(tmp_path / "index.db")
    result = core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path)
    conn = core.storage.get_connection(db_path)
    row = core.storage.get_project(conn, result["path"])
    assert row["description"] == "Ведём таблицу закупок и остатков по стройке гаража"


def test_list_projects_for_user_includes_group_and_description(tmp_path):
    _write_project(tmp_path, "dem/ALL/a")
    _write_project(tmp_path, "dem/1С/b")
    db_path = str(tmp_path / "index.db")
    core.index_update("dem", "dem/ALL/a", workspace_root=str(tmp_path), db_path=db_path)
    core.index_update("dem", "dem/1С/b", workspace_root=str(tmp_path), db_path=db_path)

    result = core.list_projects_for_user("dem", workspace_root=str(tmp_path), db_path=db_path)
    by_group = {p["group"] for p in result}
    assert by_group == {"ALL", "1С"}
    assert all(p["description"] == "Ведём таблицу закупок и остатков по стройке гаража" for p in result)


def test_list_projects_for_user_filters_by_since_and_status(tmp_path):
    old_dir = _write_project(tmp_path, "dem/ALL/old")
    _write_project(tmp_path, "dem/ALL/new")
    db_path = str(tmp_path / "index.db")
    old_mtime = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
    os.utime(old_dir / "about.md", (old_mtime, old_mtime))
    core.index_update("dem", "dem/ALL/old", workspace_root=str(tmp_path), db_path=db_path)
    core.index_update("dem", "dem/ALL/new", workspace_root=str(tmp_path), db_path=db_path)

    result = core.list_projects_for_user(
        "dem", workspace_root=str(tmp_path), db_path=db_path, updated_since="2025-01-01T00:00:00",
    )
    assert {p["path"] for p in result} == {str(tmp_path / "dem" / "ALL" / "new")}


def test_get_project_detail_includes_points_now_and_group(tmp_path):
    _write_project(tmp_path, "dem/ALL/proj")
    detail = core.get_project_detail("dem", "dem/ALL/proj", workspace_root=str(tmp_path))
    assert detail["title"] == "Учёт стройматериалов для гаража"
    assert detail["points"] == "- начали с чистого листа"
    assert detail["now"] == "Заказали цемент"
    assert detail["group"] == "ALL"
    assert detail["path"] == str(tmp_path / "dem" / "ALL" / "proj")


def test_get_project_detail_rejects_other_user(tmp_path):
    (tmp_path / "dem").mkdir()
    _write_project(tmp_path, "rost/ALL/proj")
    with pytest.raises(core.ProjectIndexError):
        core.get_project_detail("dem", "rost/ALL/proj", workspace_root=str(tmp_path))


def test_search_similar_includes_group(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/proj")
    db_path = str(tmp_path / "index.db")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: [1.0, 0.0])
    core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path, api_key="key")

    result = core.search_similar("dem", "гараж", workspace_root=str(tmp_path), db_path=db_path, api_key="key")
    assert result["results"][0]["group"] == "ALL"


def test_search_similar_does_not_return_raw_embedding(tmp_path, monkeypatch):
    """Эмбеддинг нужен только внутри scoring — наружу (в контекст LLM и в
    HTTP-ответ) он уходить не должен: это ~30k токенов шума на вызов."""
    _write_project(tmp_path, "dem/ALL/proj")
    db_path = str(tmp_path / "index.db")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: [1.0, 0.0])
    core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path, api_key="key")

    result = core.search_similar("dem", "гараж", workspace_root=str(tmp_path), db_path=db_path, api_key="key")
    assert "embedding" not in result["results"][0]
    assert result["results"][0]["score"] == pytest.approx(1.0)


def test_list_projects_for_user_does_not_return_raw_embedding(tmp_path, monkeypatch):
    _write_project(tmp_path, "dem/ALL/proj")
    db_path = str(tmp_path / "index.db")
    monkeypatch.setattr(core.embeddings, "fetch_embedding", lambda text, api_key: [0.1, 0.2])
    core.index_update("dem", "dem/ALL/proj", workspace_root=str(tmp_path), db_path=db_path, api_key="key")

    result = core.list_projects_for_user("dem", workspace_root=str(tmp_path), db_path=db_path)
    assert "embedding" not in result[0]
