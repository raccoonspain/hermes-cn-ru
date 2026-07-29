"""Самопочинка владельца файлов внутри /home/hermes/workspace.

Терминал/execute_code-инструменты Hermes при terminal.backend: docker
иногда создают файлы/папки от root вместо ожидаемого uid хоста (тот же
класс бага, что и открытый upstream-баг hermes-agent#32049) — root-owned
запись потом блокирует ЛЮБУЮ последующую запись в это же место, потому
что chown чужого файла может выполнить только root, вне зависимости от
того, кто владеет папкой вокруг (см. docs/superpowers/specs/
2026-07-29-workspace-permissions-self-heal-design.md). hermes не имеет
sudo вообще (D-003) — здесь у него ровно одно узкое исключение: вызвать
этот один root-скрипт, который сам же отказывается работать за
пределами /home/hermes/workspace.

Это самолечение "по возможности": обе функции никогда не бросают
исключение — сбой самопочинки не должен ронять чат или файловую
операцию, которая её вызвала.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess

logger = logging.getLogger(__name__)

FIX_SCRIPT_PATH = "/usr/local/bin/hermes-fix-workspace-perms.sh"


def ensure_ownership_sync(project_root: str) -> None:
    try:
        result = subprocess.run(
            ["sudo", "-n", FIX_SCRIPT_PATH, project_root],
            capture_output=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ensure_ownership_sync timed out for %s", project_root)
        return
    if result.returncode != 0:
        logger.warning(
            "ensure_ownership_sync failed for %s: %s", project_root, result.stderr.decode(errors="replace"),
        )


async def ensure_ownership(project_root: str) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, ensure_ownership_sync, project_root)
