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
