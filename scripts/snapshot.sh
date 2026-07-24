#!/usr/bin/env bash
# Снимок проекта в git — «коммитим всё, что произошло» — локально и на GitHub.
#
# Зачем: история проекта = история коммитов. Чтобы другая нейронка могла
# восстановить «что делали, где сейчас и куда идём», каждый осмысленный шаг
# должен оказаться в git — и локально, и в GitHub-зеркале — вместе с
# обновлёнными docs/.
#
# Использование:
#   bash scripts/snapshot.sh "что сделали этим шагом"
#   npm run snapshot -- "что сделали"      # если добавлен в package.json
#
# Что делает:
#   1. Инициализирует git-репозиторий (ветка main), если его ещё нет.
#   2. Подключает GitHub-зеркало origin, если оно ещё не подключено.
#   3. git add -A  (всё, кроме того что в .gitignore: .env, node_modules, data/)
#   4. Коммитит с твоим сообщением (+ датой), если есть что коммитить.
#   5. Пушит в origin/main. Если пуш не удался (нет сети/доступа) — коммит
#      всё равно остаётся локально, скрипт предупреждает, но не падает.
#
set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE_URL="git@github.com:raccoonspain/hermes-cn-ru.git"
BRANCH="main"

MSG="${1:-}"
if [ -z "$MSG" ]; then
  echo "Укажи сообщение: bash scripts/snapshot.sh \"что сделали\""
  exit 1
fi

# git-репозиторий: создаём при первом запуске
if [ ! -d .git ]; then
  echo "Первый снимок — инициализирую git…"
  git init -q -b "$BRANCH"
  git config user.name  >/dev/null 2>&1 || git config user.name  "vibe-student"
  git config user.email >/dev/null 2>&1 || git config user.email "student@vibe.local"
fi

# GitHub-зеркало: подключаем, если ещё не подключено
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "Подключаю GitHub-зеркало: $REMOTE_URL"
  git remote add origin "$REMOTE_URL"
fi

git add -A

if git diff --cached --quiet; then
  echo "Изменений нет — коммитить нечего (но всё равно проверю, всё ли запушено)."
else
  DATE="$(date +%Y-%m-%d)"
  git commit -q -m "$MSG" -m "snapshot: $DATE"
  echo "✓ Снимок сохранён локально: $MSG"
fi

# Пуш на GitHub. Локальный коммит уже сделан и важнее — если пуш не
# прошёл (нет сети, нет доступа и т.п.), не валим скрипт, а предупреждаем.
if git push -u origin "$BRANCH"; then
  echo "✓ Запушено в GitHub: origin/$BRANCH"
else
  echo "⚠ Не удалось запушить в GitHub — коммит сохранён только локально."
  echo "  Проверь доступ к $REMOTE_URL и повтори: git push -u origin $BRANCH"
fi

echo "  Вся история: git log --oneline"
