"""Разовый ручной сид пользователей — без UI в этом срезе (см. спек,
управление пользователями — отдельный срез 4, admin.html).

Запуск на сервере:
    cd ~/hermes-web
    venv/bin/python3 -m hermes_web.seed_users dem owner "Дмитрий"
(пароль запрашивается интерактивно, не передаётся аргументом — не
светится в истории шелла/логах процессов)
"""
from __future__ import annotations

import argparse
import getpass
import sys

from . import auth, storage

DEFAULT_DB_PATH = "hermes-web.db"


def seed_user(conn, username: str, password: str, role: str, display_name: str) -> None:
    storage.create_user(conn, username, auth.hash_password(password), role, display_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("role", choices=["owner", "participant"])
    parser.add_argument("display_name")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    password = getpass.getpass(f"Пароль для {args.username}: ")
    password_confirm = getpass.getpass("Повторите пароль: ")
    if password != password_confirm:
        print("Пароли не совпадают", file=sys.stderr)
        return 1

    conn = storage.get_connection(args.db_path)
    seed_user(conn, args.username, password, args.role, args.display_name)
    print(f"Пользователь {args.username} ({args.role}) создан")
    return 0


if __name__ == "__main__":
    sys.exit(main())
