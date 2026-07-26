"""SQLite-backed storage for project embeddings — pure Python, no numpy.

One row per project, keyed by absolute path (path validation/resolution
lives in core.py, not here). Cosine similarity is computed in plain
Python; at the expected scale (thousands of projects, not millions) this
is fast enough and avoids a numpy/sqlite-vec dependency that isn't
already installed on the Hermes venv this plugin runs in (numpy is only
pulled in by Hermes's own optional `voice` extra).
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Optional


def get_connection(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            path TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            tags TEXT NOT NULL,
            status TEXT NOT NULL,
            embedding BLOB,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def pack_embedding(vector: list) -> bytes:
    import struct

    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_embedding(blob: bytes) -> list:
    import struct

    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


def upsert_project(
    conn: sqlite3.Connection,
    path: str,
    title: str,
    tags: list,
    status: str,
    embedding: Optional[list],
    updated_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO projects (path, title, tags, status, embedding, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            title=excluded.title,
            tags=excluded.tags,
            status=excluded.status,
            embedding=excluded.embedding,
            updated_at=excluded.updated_at
        """,
        (
            path,
            title,
            json.dumps(tags, ensure_ascii=False),
            status,
            pack_embedding(embedding) if embedding is not None else None,
            updated_at,
        ),
    )
    conn.commit()


def rename_path(conn: sqlite3.Connection, old_path: str, new_path: str) -> None:
    conn.execute("UPDATE projects SET path = ? WHERE path = ?", (new_path, old_path))
    conn.commit()


def delete_project(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM projects WHERE path = ?", (path,))
    conn.commit()


def get_project(conn: sqlite3.Connection, path: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM projects WHERE path = ?", (path,)).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def list_projects_for_user(conn: sqlite3.Connection, workspace_root: str, user: str) -> list:
    prefix = f"{workspace_root.rstrip('/')}/{user}/"
    rows = conn.execute("SELECT * FROM projects").fetchall()
    return [_row_to_dict(r) for r in rows if r["path"].startswith(prefix)]


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "path": row["path"],
        "title": row["title"],
        "tags": json.loads(row["tags"]),
        "status": row["status"],
        "embedding": unpack_embedding(row["embedding"]) if row["embedding"] is not None else None,
        "updated_at": row["updated_at"],
    }


def cosine_similarity(a: list, b: list) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def search_similar(
    conn: sqlite3.Connection,
    workspace_root: str,
    user: str,
    query_embedding: list,
    top_k: int = 5,
) -> list:
    candidates = [
        p for p in list_projects_for_user(conn, workspace_root, user)
        if p["embedding"] is not None
    ]
    scored = [
        {**p, "score": cosine_similarity(query_embedding, p["embedding"])}
        for p in candidates
    ]
    scored.sort(key=lambda p: p["score"], reverse=True)
    return scored[:top_k]
