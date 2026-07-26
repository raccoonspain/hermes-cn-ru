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
