"""Entrypoint запускаемый systemd-юнитом hermes-web.service.

Все настройки — из окружения (EnvironmentFile=~/.hermes/.env в systemd-юните,
общий с самим Hermes — см. Task 8):
  API_SERVER_KEY          — bearer-ключ Hermes API server (обязателен)
  WORMSOFT_API_KEY         — для project_index.core.index_update (опционален,
                              index_update сам деградирует без него)
  PROJECT_INDEX_PLUGIN_DIR — путь к каталогу с пакетом project_index
                              (на сервере: /home/hermes/.hermes/plugins)
                              Потребляется на уровне импорта hermes_web.quickchat,
                              не прочитывается прямо этим скриптом.
  HERMES_WEB_DB_PATH       — путь к hermes-web.db (по умолчанию рядом с этим файлом)
  HERMES_WEB_HOST/PORT     — адрес прослушивания (по умолчанию 127.0.0.1:8643)
  HERMES_WEB_COOKIE_SECURE — "true"/"false" (по умолчанию true; false — только
                              для локальной разработки по http)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from aiohttp import web

from hermes_web.app import create_app
from hermes_web.quickchat import Config

_HERE = Path(__file__).resolve().parent


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes"}


def configure_logging() -> None:
    """Без этого корневой логгер молчит на уровне WARNING по умолчанию —
    и logger.info(...) из quickchat.py (диагностика A1: result_target,
    факт усиления системного сообщения на каждый ход) никогда не строится,
    не то что не пишется. aiohttp.web.run_app сам вешает обработчик на
    логгер "aiohttp.access", если у него уровень NOTSET — после нашего
    basicConfig() это было бы так и без пропуска сюда, отключаем propagate,
    чтобы access-строки не задваивались через корневой логгер, а поведение
    access-логов (уже полагается на них systemd journal) не изменилось."""
    logging.basicConfig(level=logging.INFO)
    # basicConfig() — no-op, если у root-логгера уже есть handler(ы) (так
    # бывает в тестах под pytest, где свой logging-плагин может повесить
    # handler раньше), а без него результата INFO не сохранился бы вообще —
    # выставляем уровень явно и отдельно, чтобы не зависеть от этого.
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger("aiohttp.access").propagate = False


def main() -> None:
    configure_logging()
    api_server_key = os.environ["API_SERVER_KEY"]
    db_path = os.environ.get("HERMES_WEB_DB_PATH", str(_HERE / "hermes-web.db"))
    host = os.environ.get("HERMES_WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("HERMES_WEB_PORT", "8643"))

    config = Config(
        hermes_base_url=os.environ.get("HERMES_API_BASE_URL", "http://127.0.0.1:8642"),
        hermes_api_key=api_server_key,
        wormsoft_api_key=os.environ.get("WORMSOFT_API_KEY"),
    )
    app = create_app(
        db_path=db_path,
        quickchat_config=config,
        cookie_secure=_bool_env("HERMES_WEB_COOKIE_SECURE", True),
        static_dir=str(_HERE / "static"),
    )
    web.run_app(app, host=host, port=port)


if __name__ == "__main__":
    main()
