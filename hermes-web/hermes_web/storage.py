"""SQLite-backed storage for hermes-web: users, web-login sessions, chat sessions."""
from __future__ import annotations

import sqlite3
import time
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
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            display_name TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS web_sessions (
            token TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            user TEXT NOT NULL,
            project_path TEXT NOT NULL,
            hermes_session_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            last_message_at REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS group_meta (
            user TEXT NOT NULL,
            slug TEXT NOT NULL,
            display_name TEXT NOT NULL,
            emoji TEXT NOT NULL DEFAULT '',
            pinned INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user, slug)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            actor TEXT NOT NULL,
            verb TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.commit()


def create_user(conn: sqlite3.Connection, username: str, password_hash: str, role: str, display_name: str) -> None:
    conn.execute(
        "INSERT INTO users (username, password_hash, role, display_name) VALUES (?, ?, ?, ?)",
        (username, password_hash, role, display_name),
    )
    conn.commit()


def get_user(conn: sqlite3.Connection, username: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def create_web_session(conn: sqlite3.Connection, token: str, username: str, expires_at: float) -> None:
    conn.execute(
        "INSERT INTO web_sessions (token, username, expires_at) VALUES (?, ?, ?)",
        (token, username, expires_at),
    )
    conn.commit()


def get_web_session(conn: sqlite3.Connection, token: str, now: float) -> Optional[dict]:
    row = conn.execute("SELECT * FROM web_sessions WHERE token = ?", (token,)).fetchone()
    if row is None or row["expires_at"] <= now:
        return None
    return dict(row)


def delete_web_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM web_sessions WHERE token = ?", (token,))
    conn.commit()


def create_chat_session(
    conn: sqlite3.Connection, id: str, user: str, project_path: str, hermes_session_id: str, created_at: float,
) -> None:
    conn.execute(
        """
        INSERT INTO chat_sessions (id, user, project_path, hermes_session_id, created_at, last_message_at)
        VALUES (?, ?, ?, ?, ?, NULL)
        """,
        (id, user, project_path, hermes_session_id, created_at),
    )
    conn.commit()


def get_chat_session(conn: sqlite3.Connection, id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (id,)).fetchone()
    return dict(row) if row else None


def touch_chat_session(conn: sqlite3.Connection, id: str, last_message_at: float) -> None:
    conn.execute("UPDATE chat_sessions SET last_message_at = ? WHERE id = ?", (last_message_at, id))
    conn.commit()


def get_chat_session_for_project(conn: sqlite3.Connection, user: str, project_path: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM chat_sessions WHERE user = ? AND project_path = ? ORDER BY created_at DESC LIMIT 1",
        (user, project_path),
    ).fetchone()
    return dict(row) if row else None


def get_group_meta(conn: sqlite3.Connection, user: str, slug: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM group_meta WHERE user = ? AND slug = ?", (user, slug)
    ).fetchone()
    return dict(row) if row else None


def upsert_group_meta(
    conn: sqlite3.Connection, user: str, slug: str, display_name: str, emoji: str, pinned: bool, created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO group_meta (user, slug, display_name, emoji, pinned, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user, slug) DO UPDATE SET
            display_name=excluded.display_name,
            emoji=excluded.emoji,
            pinned=excluded.pinned
        """,
        (user, slug, display_name, emoji, int(pinned), created_at),
    )
    conn.commit()


def list_group_meta(conn: sqlite3.Connection, user: str) -> list:
    rows = conn.execute("SELECT * FROM group_meta WHERE user = ?", (user,)).fetchall()
    return [dict(r) for r in rows]


def update_chat_session_project_path(conn: sqlite3.Connection, old_path: str, new_path: str) -> None:
    conn.execute(
        "UPDATE chat_sessions SET project_path = ? WHERE project_path = ?", (new_path, old_path)
    )
    conn.commit()


def list_users(conn: sqlite3.Connection) -> list:
    rows = conn.execute("SELECT username, role, display_name FROM users ORDER BY username").fetchall()
    return [dict(row) for row in rows]


def update_user(conn: sqlite3.Connection, username: str, display_name: str, role: str) -> None:
    conn.execute(
        "UPDATE users SET display_name = ?, role = ? WHERE username = ?",
        (display_name, role, username),
    )
    conn.commit()


def update_user_password(conn: sqlite3.Connection, username: str, password_hash: str) -> None:
    conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (password_hash, username))
    conn.commit()


def count_active_sessions(conn: sqlite3.Connection, now: float) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS sessions, COUNT(DISTINCT username) AS users FROM web_sessions WHERE expires_at > ?",
        (now,),
    ).fetchone()
    return {"sessions": row["sessions"], "users": row["users"]}


def get_last_activity(conn: sqlite3.Connection, user: str) -> Optional[float]:
    row = conn.execute(
        "SELECT MAX(COALESCE(last_message_at, created_at)) AS last_active FROM chat_sessions WHERE user = ?",
        (user,),
    ).fetchone()
    return row["last_active"]


def log_event(conn: sqlite3.Connection, actor: str, verb: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO events (ts, actor, verb, detail) VALUES (?, ?, ?, ?)",
        (time.time(), actor, verb, detail),
    )
    conn.commit()


def list_events(conn: sqlite3.Connection, limit: int = 50) -> list:
    rows = conn.execute(
        "SELECT ts, actor, verb, detail FROM events ORDER BY id DESC LIMIT ?", (limit,),
    ).fetchall()
    return [dict(row) for row in rows]
