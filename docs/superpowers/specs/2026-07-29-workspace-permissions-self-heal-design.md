# Спек: автоматическое самовосстановление владельца файлов в workspace агента

**Дата:** 2026-07-29 · **Статус:** черновик, ждёт ревью пользователя

## Контекст

Живой прогон (2026-07-29, разбор задач 3.23–3.29 из Кирика) застрял:
агент не мог ни создать, ни перезаписать файл в
`/home/hermes/workspace/dem/fizika-kinematika/physics-tasks/3-kirik-3-23-29/`.
Пользователь одобрил `chmod 777` в чате — не помогло; агент перепробовал
`write_file`, `execute_code`/`tee`, `python` — везде `permission denied`.

Диагностика на сервере (прямой SSH под `hermes`, затем под `root`)
показала точную причину: 4 файловые записи в этом дереве оказались
владением `root:root`, хотя `hermes` (uid 1001, без sudo, см. D-003)
владеет всем остальным деревом `/home/hermes/workspace`:

```
drwxr-xr-x 2 root root .../3-kirik-3-23-29        (папка целиком)
-rw-r--r-- 1 root root .../3-kirik-3-23-29/tasks.md
-rw-r--r-- 1 root root .../3-kirik-3-23-29/graph_3_26.png
drwxr-xr-x 2 root root .../3-kirik-3-20            (папка целиком)
```

Сравнение mtime (07:57–09:15 накануне) с временем создания текущего
sandbox-контейнера (`hermes-b4c63120`, создан 17:50 того же дня) говорит,
что эти записи — не свежий сбой прямо сейчас, а **не убранный вовремя
мусор от более раннего сбоя** докер-бэкенда Hermes: в какой-то момент
`mkdir`, выполненный агентом внутри Docker-песочницы
(`terminal`/`execute_code`), отработал от имени `root`, а не от `hermes`
(uid 1001) — вопреки `docker_run_as_host_user: true` (см. D-011). Это тот
же класс проблемы, что открытый и не исправленный upstream-баг
[hermes-agent#32049](https://github.com/NousResearch/hermes-agent/issues/32049)
(внутренний механизм Hermes может создавать root-владением копии в
sandbox независимо от `--user`-флага докера).

Проверено на конкретных файлах в этом же дереве, что проблема не общая, а
именно точечная: файл-вложение, присланное в чат
(`source/Кирик/2026-07-28_Кинематика задачи.pdf`), подпапка `source/Кирик`,
созданная человеком через кнопку «новая папка» в UI, и десятки `.html`-
файлов, которые агент создал сам в этом же проекте — **все** уже были
`hermes:hermes`. Ломаются только записи, созданные `mkdir` внутри
Docker-песочницы в момент сбоя — редко, но предсказуемо повторяется
(тот же класс уже чинили в D-011, всплыл снова).

**Важно:** `hermes` и так владеет своей рабочей папкой целиком
(`drwxrwxr-x hermes hermes /home/hermes/workspace`) — проблема не в
правах на директорию, а в том, что *сменить владельца конкретного файла*
(`chown`) физически может только root, кто бы ни владел папкой вокруг.
Своими силами (без sudo, без root — см. D-003) `hermes` в принципе не
может починить root-owned запись внутри собственного дерева.

## Требование

1. **Полностью избежать проблему нельзя** — первопричина в вендорном
   коде Hermes (issue #32049, `agent/file_safety.py` и внутренний
   sandbox-механизм — открытый код, но менять нельзя, потеряется при
   `hermes update`, см. CLAUDE.md).
2. Значит нужна **автоматическая починка**, не требующая ручного
   вмешательства пользователя или ручного разбора агентом: обнаруживать
   и чинить владение файлами *до* того, как оно помешает записи — не
   ждать, пока агент упрётся и начнёт городить обходные пути в чате.

## Решение

### 1. Root-скрипт с самопроверкой пути

`/usr/local/bin/hermes-fix-workspace-perms.sh` (root:root, `chmod 700`,
не редактируется `hermes`):

```bash
#!/bin/bash
set -euo pipefail
target="$(readlink -f "$1")"
root="/home/hermes/workspace"
if [[ "$target" != "$root" && "$target" != "$root"/* ]]; then
    echo "refuse: '$target' is outside $root" >&2
    exit 1
fi
chown -R hermes:hermes "$target"
```

Скрипт сам перепроверяет резолвленный (`readlink -f`) путь — даже если
sudoers-шаблон совпадёт с чем-то неожиданным по glob-маске, скрипт всё
равно откажется работать за пределами `/home/hermes/workspace`. Тот же
принцип defense-in-depth, что уже применён против path traversal в
`move_project`/`save_upload` (см. `docs/decisions.md`, срез 3 часть 1/2).

### 2. Узкое sudo-правило для `hermes`

`/etc/sudoers.d/hermes-fix-workspace-perms`:

```
hermes ALL=(root) NOPASSWD: /usr/local/bin/hermes-fix-workspace-perms.sh *
```

Единственная новая привилегия у `hermes` — вызвать ровно этот скрипт.
Не sudo вообще, не `chown` напрямую, не что-либо ещё — согласуется с
D-003 (минимальный периметр сервисного аккаунта). Устанавливается через
`visudo -c -f` перед активацией (синтаксическая проверка обязательна).

### 3. Точки вызова в `hermes-web`

Новый маленький модуль `hermes_web/permissions.py`:

```python
async def ensure_ownership(loop, project_root: str) -> None:
    """Не блокирует event loop (см. уже принятый в проекте паттерн для
    project_index_core.index_update) и не бросает исключение наверх —
    это самолечение "по возможности", а не обязательный шаг чата."""
    await loop.run_in_executor(None, _fix_ownership_sync, project_root)

def _fix_ownership_sync(project_root: str) -> None:
    result = subprocess.run(
        ["sudo", "-n", "/usr/local/bin/hermes-fix-workspace-perms.sh", project_root],
        capture_output=True, timeout=30,
    )
    if result.returncode != 0:
        logging.warning("ensure_ownership failed for %s: %s", project_root, result.stderr)
```

`sudo -n` — если sudoers-правило вдруг не применилось или не совпало,
`sudo` должен сразу вернуть ошибку, а не зависнуть в ожидании пароля
(которого у `hermes` нет — `passwd -l`, см. D-003) и не заблокировать
event-loop поток на таймауте.

Вызывается в двух местах, до фактической записи:

- **`quickchat.send_message`** (`hermes_web/quickchat.py:181`) — перед
  каждым вызовом `hermes_client.stream_chat`, на `row["project_path"]`.
  Закрывает главный наблюдаемый сценарий: агент упирается в старую
  сломанную папку посреди хода.
- **`workspace.save_file` / `workspace.make_dir` / `workspace.save_upload`**
  (`hermes_web/workspace.py:198,225,242`) — перед записью, на
  `project_root` (уже возвращается `resolve_file_path`). Закрывает тот
  же класс сбоя для человека, работающего через UI (кнопка «сохранить»/
  «новая папка»/загрузка вложения) — ровно та же root-owned папка
  помешала бы и ему, не только агенту.

Скоуп — **конкретный проект**, не всё дерево `/home/hermes/workspace`:
дёшево (одна `chown -R` на директорию проекта, не на тысячи будущих
сессий), запускается на каждый ход/операцию — то есть чинит и
свежесозданную поломку, и застарелый мусор, до того как об него
споткнутся.

## Почему не таймер

Раньше рассматривался systemd-таймер под root (`chown -R` по всему
дереву каждые 5–10 минут). Отклонено пользователем в пользу узкого
sudo: починка "по требованию" (перед каждым обращением к проекту)
закрывает окно между тиками таймера и не требует `chown -R` по всему
дереву (которое со временем вырастет до "десятков тысяч сессий" по
project-brief) на каждый прогон.

## Что не делаем

- Не патчим `agent/file_safety.py` или другой вендорный код Hermes —
  правило CLAUDE.md, ломается при `hermes update`.
- Не расширяем sudo `hermes` на что-либо, кроме этого одного скрипта.
- Не пытаемся перехватывать `permission denied` внутри самого хода
  агента (это была бы правка на границе tool-call, которая тоже упирается
  в вендорный `file_safety.py`) — чиним превентивно, до хода, а не
  реактивно, посреди него.

## Тесты

- `hermes_web/permissions.py`: юнит-тест на `_fix_ownership_sync` с
  замоканным `subprocess.run` (успех/неуспех, таймаут — не бросает).
- Интеграционные тесты `quickchat.send_message` и
  `workspace.save_file/make_dir/save_upload`: `ensure_ownership`
  вызывается с ожидаемым `project_root` до записи (мок, без реального
  `sudo` в тестовом окружении).
- Деплой-шаг (не юнит-тест): на сервере — `visudo -c`, затем живая
  проверка `sudo -u hermes sudo /usr/local/bin/hermes-fix-workspace-perms.sh /home/hermes/workspace/dem`
  и отдельно попытка вызвать скрипт на пути вне `/home/hermes/workspace`
  (должен отказать).

## Деплой

1. Скопировать скрипт на сервер (`root`), `chmod 700`.
2. Добавить sudoers-файл, `visudo -c -f /etc/sudoers.d/hermes-fix-workspace-perms`.
3. Задеплоить изменённый `hermes-web` (rsync + `systemctl --user restart hermes-web.service`, как в предыдущих срезах).
4. Живая проверка: воспроизвести на тестовом (`qa_temp`) проекте —
   намеренно испортить владельца тестовой папки под root, открыть чат,
   убедиться, что папка автоматически становится `hermes:hermes` до
   ответа агента.
