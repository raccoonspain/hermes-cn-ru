"""Finding 1 финального ревью (2026-07-29): без явной настройки root-логгера
его эффективный уровень по умолчанию — WARNING, поэтому logger.info(...) из
quickchat.py (диагностика A1: result_target, факт усиления системного
сообщения) никогда не строится, не то что не пишется никуда. caplog здесь
намеренно не используется: caplog сам ставит handler и форсирует уровень на
время теста, поэтому не поймал бы регресс "никто вообще не сконфигурировал
root-логгер" — тест ниже проверяет эффективный уровень напрямую."""
import logging

import run


def test_configure_logging_sets_effective_info_level():
    root = logging.getLogger()
    previous_level = root.level
    previous_handlers = list(root.handlers)
    try:
        run.configure_logging()
        assert root.getEffectiveLevel() <= logging.INFO
    finally:
        root.handlers = previous_handlers
        root.setLevel(previous_level)
