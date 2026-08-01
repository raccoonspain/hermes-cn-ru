import pytest

from project_index import storage


def test_upsert_and_get_project_roundtrip(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(
        conn,
        path="/workspace/dem/ALL/2026-01-01_test",
        title="Тестовый проект",
        tags=["excel", "работа"],
        status="active",
        embedding=[0.1, 0.2, 0.3],
        updated_at="2026-01-01T00:00:00",
    )
    row = storage.get_project(conn, "/workspace/dem/ALL/2026-01-01_test")
    assert row["title"] == "Тестовый проект"
    assert row["tags"] == ["excel", "работа"]
    assert row["status"] == "active"
    assert row["embedding"] == pytest.approx([0.1, 0.2, 0.3], rel=1e-5)
    assert row["updated_at"] == "2026-01-01T00:00:00"


def test_upsert_overwrites_existing_row(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/p/a", "старое", [], "active", None, "2026-01-01T00:00:00")
    storage.upsert_project(conn, "/p/a", "новое", ["x"], "archived", [1.0, 0.0], "2026-01-02T00:00:00")
    row = storage.get_project(conn, "/p/a")
    assert row["title"] == "новое"
    assert row["tags"] == ["x"]
    assert row["status"] == "archived"
    assert row["embedding"] == pytest.approx([1.0, 0.0])


def test_get_project_missing_returns_none(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    assert storage.get_project(conn, "/nope") is None


def test_upsert_without_embedding_leaves_it_none(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/p/b", "название", [], "active", None, "2026-01-01T00:00:00")
    row = storage.get_project(conn, "/p/b")
    assert row["embedding"] is None


def test_rename_path_moves_the_row(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/old/path", "т", [], "active", [1.0], "2026-01-01T00:00:00")
    storage.rename_path(conn, "/old/path", "/new/path")
    assert storage.get_project(conn, "/old/path") is None
    assert storage.get_project(conn, "/new/path")["title"] == "т"


def test_delete_project_removes_the_row(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/p/a", "т", [], "active", None, "2026-01-01T00:00:00")
    storage.delete_project(conn, "/p/a")
    assert storage.get_project(conn, "/p/a") is None


def test_list_projects_for_user_filters_by_prefix(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/x", "dem-x", [], "active", None, "t")
    storage.upsert_project(conn, "/workspace/dem/1С/y", "dem-y", [], "active", None, "t")
    storage.upsert_project(conn, "/workspace/rost/ALL/z", "rost-z", [], "active", None, "t")
    dem_projects = storage.list_projects_for_user(conn, "/workspace", "dem")
    assert {p["path"] for p in dem_projects} == {"/workspace/dem/ALL/x", "/workspace/dem/1С/y"}


def test_cosine_similarity_known_values():
    assert storage.cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert storage.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert storage.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert storage.cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_search_similar_orders_by_score_and_respects_top_k(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/close", "близко", [], "active", [1.0, 0.0], "t")
    storage.upsert_project(conn, "/workspace/dem/ALL/far", "далеко", [], "active", [0.0, 1.0], "t")
    storage.upsert_project(conn, "/workspace/dem/ALL/mid", "средне", [], "active", [0.7, 0.7], "t")
    storage.upsert_project(conn, "/workspace/dem/ALL/no-embedding", "без эмбеддинга", [], "active", None, "t")
    results = storage.search_similar(conn, "/workspace", "dem", [1.0, 0.0], top_k=2)
    assert [r["path"] for r in results] == [
        "/workspace/dem/ALL/close",
        "/workspace/dem/ALL/mid",
    ]


def test_upsert_project_stores_description(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(
        conn, "/p/a", "т", [], "active", None, "2026-01-01T00:00:00", description="краткое описание",
    )
    row = storage.get_project(conn, "/p/a")
    assert row["description"] == "краткое описание"


def test_upsert_project_description_defaults_to_empty_string(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/p/a", "т", [], "active", None, "2026-01-01T00:00:00")
    row = storage.get_project(conn, "/p/a")
    assert row["description"] == ""


def test_init_db_migrates_existing_table_without_description_column(tmp_path):
    import sqlite3

    db_path = str(tmp_path / "index.db")
    old_conn = sqlite3.connect(db_path)
    old_conn.execute(
        """
        CREATE TABLE projects (
            path TEXT PRIMARY KEY, title TEXT NOT NULL, tags TEXT NOT NULL,
            status TEXT NOT NULL, embedding BLOB, updated_at TEXT NOT NULL
        )
        """
    )
    old_conn.execute(
        "INSERT INTO projects (path, title, tags, status, embedding, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("/p/a", "старый", "[]", "active", None, "2026-01-01T00:00:00"),
    )
    old_conn.commit()
    old_conn.close()

    conn = storage.get_connection(db_path)
    row = storage.get_project(conn, "/p/a")
    assert row["title"] == "старый"
    assert row["description"] == ""


def test_list_projects_filtered_by_status(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/a", "a", [], "active", None, "2026-01-01T00:00:00")
    storage.upsert_project(conn, "/workspace/dem/ALL/b", "b", [], "archived", None, "2026-01-01T00:00:00")
    result = storage.list_projects_filtered(conn, "/workspace", "dem", status="active")
    assert {p["path"] for p in result} == {"/workspace/dem/ALL/a"}


def test_list_projects_filtered_by_updated_since(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/old", "old", [], "active", None, "2020-01-01T00:00:00")
    storage.upsert_project(conn, "/workspace/dem/ALL/new", "new", [], "active", None, "2026-07-01T00:00:00")
    result = storage.list_projects_filtered(conn, "/workspace", "dem", updated_since="2026-01-01T00:00:00")
    assert {p["path"] for p in result} == {"/workspace/dem/ALL/new"}


def test_list_projects_filtered_by_group(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/a", "a", [], "active", None, "t")
    storage.upsert_project(conn, "/workspace/dem/1С/b", "b", [], "active", None, "t")
    result = storage.list_projects_filtered(conn, "/workspace", "dem", group="ALL")
    assert {p["path"] for p in result} == {"/workspace/dem/ALL/a"}


def test_list_projects_filtered_group_star_means_everywhere(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/a", "a", [], "active", None, "t")
    storage.upsert_project(conn, "/workspace/dem/1С/b", "b", [], "active", None, "t")
    result = storage.list_projects_filtered(conn, "/workspace", "dem", group="*")
    assert {p["path"] for p in result} == {"/workspace/dem/ALL/a", "/workspace/dem/1С/b"}


def test_list_projects_filtered_strips_embedding(tmp_path):
    """Сырой эмбеддинг (1024 float на проект) не должен утекать в листинг:
    его сериализация в JSON на ~1000 проектов — это ~20 МБ ответа и >1 с
    блокировки однопоточного event loop в hermes-web."""
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/a", "a", [], "active", [0.1, 0.2, 0.3], "t")
    result = storage.list_projects_filtered(conn, "/workspace", "dem")
    assert len(result) == 1
    assert "embedding" not in result[0]
    assert result[0]["title"] == "a"


def test_list_projects_filtered_keeps_search_similar_working(tmp_path):
    """Страховка: search_similar ходит через list_projects_for_user, а не
    через list_projects_filtered, поэтому эмбеддинг ему всё ещё доступен."""
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/close", "близко", [], "active", [1.0, 0.0], "t")
    results = storage.search_similar(conn, "/workspace", "dem", [1.0, 0.0], top_k=1)
    assert results[0]["score"] == pytest.approx(1.0)


def test_list_projects_filtered_scoped_to_user(tmp_path):
    conn = storage.get_connection(str(tmp_path / "index.db"))
    storage.upsert_project(conn, "/workspace/dem/ALL/a", "a", [], "active", None, "t")
    storage.upsert_project(conn, "/workspace/rost/ALL/b", "b", [], "active", None, "t")
    result = storage.list_projects_filtered(conn, "/workspace", "dem")
    assert {p["path"] for p in result} == {"/workspace/dem/ALL/a"}
