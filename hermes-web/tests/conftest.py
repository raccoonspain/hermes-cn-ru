import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Локально project_index лежит в hermes-plugins/ этого же репозитория —
# hermes_web.quickchat читает PROJECT_INDEX_PLUGIN_DIR из окружения, чтобы
# найти пакет project_index на sys.path (на сервере это /home/hermes/.hermes/plugins).
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
os.environ.setdefault(
    "PROJECT_INDEX_PLUGIN_DIR",
    os.path.abspath(os.path.join(_REPO_ROOT, "hermes-plugins")),
)
