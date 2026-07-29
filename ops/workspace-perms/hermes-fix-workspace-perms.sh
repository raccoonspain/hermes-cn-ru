#!/bin/bash
# Разворачивается на сервере как /usr/local/bin/hermes-fix-workspace-perms.sh,
# root:root, chmod 700. Единственная задача: chown -R hermes:hermes на
# путь, переданный первым аргументом — но только если он лежит внутри
# /home/hermes/workspace (см. docs/superpowers/specs/
# 2026-07-29-workspace-permissions-self-heal-design.md). Сам перепроверяет
# резолвленный путь — не полагается только на sudoers-шаблон.
set -euo pipefail
target="$(readlink -f "$1")"
root="/home/hermes/workspace"
if [[ "$target" != "$root" && "$target" != "$root"/* ]]; then
    echo "refuse: '$target' is outside $root" >&2
    exit 1
fi
chown -R hermes:hermes "$target"
