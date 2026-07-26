"""SQLite-backed storage for hermes-web: users, web-login sessions, chat sessions."""
from __future__ import annotations

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
