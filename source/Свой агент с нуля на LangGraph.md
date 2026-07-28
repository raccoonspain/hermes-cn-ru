# Проектно-ориентированная агентская система: архитектурный бриф для обсуждения в Claude Code

## Цель

Нужно спроектировать self-hosted open-source агентскую систему, в которой **проект является основной единицей памяти и работы**, а не одноразовый чат или сессия. Система должна позволять вернуться к любому проекту через месяцы или годы без потери контекста, правил работы, накопленных знаний, артефактов и project-specific skills [cite:60][cite:62].

Ключевая идея: не хранить память как бесконечный transcript. Вместо этого проект должен жить как долговременная сущность со структурированным состоянием, а отдельные рабочие заходы должны быть thread/session/run внутри проекта [cite:60][cite:64].

## Проблема, которую нужно решить

Текущий опыт с тяжелыми агентами показывает несколько болей:

- Долгая и дорогая кастомизация.
- Сильный расход токенов на настройку и на реальную работу.
- Сложность возврата к старым проектам без повторного прогрева контекста.
- Плохая управляемость памяти: слишком много хранится как диалог, а не как знания проекта.
- Тяжелые runtime'ы и завышенное потребление ресурсов даже в простое.
- Сложность безопасного tool execution и контроля над правилами/скиллами проекта.

Нужна архитектура, где агент не "помнит всё в одном контексте", а **восстанавливает проект из структурированной памяти**.

## Базовые принципы

1. **Проект — корневая сущность.**
   Каждый проект имеет свой `project_id`, постоянную папку, набор файлов, память, решения, артефакты и локальные правила.

2. **Сессия — это рабочий заход в проект.**
   Сессия не равна всей памяти проекта. Это отдельный thread/run, который можно завершать, архивировать и потом снова открывать [cite:60][cite:64].

3. **Память многослойная.**
   Должны быть отдельно:
   - thread memory,
   - project memory,
   - artifact memory,
   - procedural memory,
   - personal/global memory.

4. **Диалог — не источник истины.**
   Истина хранится в `about.md`, `decisions.md`, `history.md`, индексах, summaries, facts и артефактах проекта.

5. **Специализированные исполнители лучше одного монолита.**
   Coding-задачи, research, browser work, file transforms и summarization должны решаться разными worker'ами/узлами, а не одним универсальным агентом.

6. **Система должна быть экономной.**
   При возврате к проекту агент сначала читает краткое структурированное состояние и только потом дозагружает релевантные куски по поиску, а не тащит весь transcript в prompt.

## Предлагаемое ядро

В качестве orchestration core предлагается **LangGraph**, потому что он поддерживает checkpointers, thread-scoped persistence и более долгоживущие stores, что хорошо ложится на модель “проект + отдельные рабочие треды” [cite:60][cite:62].

Для coding-слоя стоит рассмотреть:

- **Aider** как легкий git/terminal coding worker [cite:35].
- **OpenHands SDK** как более тяжелый, но мощный software-agent runtime с model-agnostic подходом и context condensation [cite:54][cite:31].

Идея: не заменять всё одним framework'ом, а собрать архитектуру из слоев.

## Целевая архитектура слоев

### 1. Project memory layer

Долговременная память проекта:

- описание проекта,
- цели,
- ограничения,
- история,
- решения,
- glossary,
- статус,
- связи с источниками,
- project-specific skills,
- embeddings и keyword index.

### 2. Orchestration layer

LangGraph как state machine / agent graph:

- intake,
- recall,
- planning,
- routing,
- execution,
- verification,
- summarization,
- persistence [cite:60][cite:62].

### 3. Execution layer

Специализированные worker'ы:

- coding worker,
- browser/research worker,
- file/document worker,
- shell/python sandbox worker,
- critic/verifier.

### 4. Gateway layer

Каналы входа:

- CLI,
- web UI,
- Matrix,
- Telegram,
- возможно API/webhooks.

Важно: gateways не должны быть центром архитектуры. Они только подают задачи в project-centric core.

## Предлагаемая структура проекта на диске

```text
projects/
  <project_id>/
    project.json
    about.md
    history.md
    decisions.md
    AGENTS.md
    SOUL.md
    inbox/
    sources/
    workspace/
    results/
    memory/
      summaries/
      facts/
      embeddings/
    sessions/
      <session_id>/
        session.json
        transcript.md
        checkpoints/
        outputs/
    skills/
      local/
      imported/
```

### Назначение основных файлов

- `project.json` — системные метаданные проекта.
- `about.md` — что это за проект, цели, ограничения, стек, KPI, definition of done.
- `history.md` — хронология изменений и важных событий.
- `decisions.md` — архитектурные и продуктовые решения с обоснованием.
- `AGENTS.md` — локальные правила поведения агентов в рамках проекта.
- `SOUL.md` — более общие/стратегические принципы проекта, если такой слой действительно нужен.
- `sources/` — входные материалы.
- `results/` — итоговые артефакты и промежуточные deliverables.
- `memory/summaries/` — durable summaries по сессиям и этапам.
- `memory/facts/` — нормализованные извлеченные факты проекта.
- `sessions/` — отдельные рабочие заходы.
- `skills/` — project-specific шаблоны, playbooks, tool presets, review rules.

## Предлагаемые сущности БД

Минимальный набор таблиц/коллекций:

### `projects`
- `id`
- `owner_id`
- `title`
- `status`
- `created_at`
- `updated_at`
- `archived_at`

### `project_state`
- `project_id`
- `current_goal`
- `active_plan`
- `pinned_facts`
- `active_artifacts`
- `open_questions`
- `next_actions`
- `updated_at`

### `sessions`
- `session_id`
- `project_id`
- `started_at`
- `ended_at`
- `entrypoint`
- `summary`
- `status`

### `runs`
- `run_id`
- `session_id`
- `graph_node`
- `worker_type`
- `model`
- `status`
- `token_usage`
- `cost`
- `started_at`
- `ended_at`

### `artifacts`
- `artifact_id`
- `project_id`
- `session_id`
- `path`
- `kind`
- `mime_type`
- `source_ref`
- `derived_from`
- `created_at`

### `memories`
- `memory_id`
- `project_id`
- `scope`
- `type`
- `text`
- `confidence`
- `source_ref`
- `created_at`
- `updated_at`

### `decisions`
- `decision_id`
- `project_id`
- `title`
- `context`
- `decision`
- `rationale`
- `consequences`
- `created_at`

### `skills_registry`
- `id`
- `project_id`
- `skill_name`
- `version`
- `path`
- `enabled`
- `updated_at`

### `search_index`
- keyword/FTS index
- embedding references
- tags
- timestamps

На старте разумно использовать **SQLite + FTS5 + embeddings index**, а не сразу усложнять систему внешней БД. Такая схема уже хорошо подходит для локального или VPS-first self-hosted проекта [cite:60].

## Типы памяти

### 1. Thread memory
Краткоживущая память конкретной сессии/треда. Хранится через checkpointer и используется для resume, human-in-the-loop и восстановления после сбоев [cite:62].

### 2. Project memory
Долговременное знание о проекте:

- цели,
- ограничения,
- стек,
- glossary,
- key facts,
- known assumptions,
- decisions,
- unresolved issues.

### 3. Artifact memory
Память, извлеченная из файлов, документов, веб-страниц, изображений, кода, результатов запусков и других артефактов проекта.

### 4. Procedural memory
Как именно работать с этим проектом:

- preferred outputs,
- review rules,
- allowed tools,
- coding conventions,
- acceptance criteria,
- publication flow,
- security restrictions.

### 5. Personal/global memory
То, что относится не к одному проекту, а к владельцу системы в целом: устойчивые предпочтения, стиль, инфраструктурные привычки, любимые форматы, запреты.

## Как должен происходить возврат в проект через годы

При открытии проекта система не должна просто поднимать последний transcript. Правильный flow такой:

1. Загрузить `project.json`.
2. Загрузить `about.md`, `project_state`, активные решения и pinned facts.
3. Поднять последние durable summaries.
4. Выполнить FTS/semantic recall по релевантным memories и artifacts.
5. Создать новую session/thread.
6. Только затем строить ответ/план/действия.
7. После завершения обновить summaries, facts, decisions, artifacts и state [cite:60][cite:64].

Это резко снижает токенозатраты и делает систему устойчивой к очень длинной истории проекта [cite:60].

## Предлагаемый LangGraph workflow

Базовый граф узлов:

1. **Intake**
   - определить `project_id`
   - определить intent
   - проверить active session или создать новую

2. **Context Recall**
   - загрузить pinned memory
   - найти релевантные facts
   - достать прошлые summaries
   - подтянуть связанные артефакты

3. **Planner**
   - классифицировать задачу: answer / research / code / files / planning / decision update
   - выбрать нужные workers

4. **Router**
   - direct answer
   - coding worker
   - browser/research worker
   - file worker
   - shell/python worker

5. **Executor**
   - выполнить задачу
   - зафиксировать outputs и provenance

6. **Critic / Verifier**
   - проверить полноту
   - проверить соответствие правилам проекта
   - проверить безопасность
   - проверить качество результата

7. **Summarizer**
   - записать краткий durable summary
   - извлечь новые facts
   - определить, появились ли новые decisions

8. **Persister**
   - обновить state
   - обновить memories
   - обновить search index
   - сохранить checkpoint [cite:62].

## Open-source компоненты по слоям

| Слой | Рекомендуемый компонент | Роль |
|---|---|---|
| Orchestration | LangGraph | Граф узлов, thread state, checkpoints, resume [cite:60][cite:62] |
| Coding worker | Aider | Легкий coding worker для git/terminal задач [cite:35] |
| Advanced software worker | OpenHands SDK | Более мощный software-agent runtime, model-agnostic, context condensation [cite:54][cite:31] |
| Retrieval | SQLite FTS5 + embeddings | Keyword + semantic recall по проекту |
| Artifact store | Локальная файловая структура | Источники, результаты, provenance |
| Sandbox | Docker/isolated runtime | Безопасное выполнение команд и кода |
| Gateway | Matrix / Telegram / Web UI / CLI | Каналы доступа, но не ядро системы |

## Практический v1

Предлагаемый **v1**:

- LangGraph как orchestration core.
- SQLite как metadata/state DB.
- SQLite FTS5 для keyword search.
- Embeddings index для semantic recall.
- Папочная project-структура как основное хранилище артефактов и markdown memory.
- Aider как основной coding worker.
- Позже, при необходимости, OpenHands SDK как более мощный software worker [cite:35][cite:54].

Это даст:

- хорошую управляемость,
- низкую зависимость от одного фреймворка,
- меньший расход токенов,
- более легкое idle-состояние,
- понятную архитектуру для эволюции.

## Вопросы для обсуждения с Claude Code

Ниже список вопросов, которые стоит обсудить и превратить в конкретные решения.

### Архитектура памяти
- Какой exact contract между `project_state`, `about.md`, `history.md`, `decisions.md` и `memories`?
- Что должно быть источником истины для активного состояния проекта?
- Когда информация попадает в `history.md`, а когда в нормализованные `memories`?
- Какой lifecycle у pinned facts?

### Session / thread model
- Что считать session, а что run?
- Нужен ли один `thread_id` на session или несколько thread'ов внутри session?
- Какой retention policy у transcript'ов?
- Как делать resume после долгого перерыва?

### Search / recall
- Как сочетать keyword search и embeddings recall?
- Как ранжировать результаты: recency, confidence, pinned status, artifact importance?
- Как избегать подтягивания лишнего контекста?

### Decision management
- Когда найденный вывод должен становиться decision?
- Нужен ли полуавтоматический decision extraction?
- Как versioning decisions должно работать?

### Skills
- Что такое skill в этом проекте: prompt template, tool preset, executable workflow или knowledge pack?
- Где хранить global skills, а где project-local skills?
- Какой механизм наследования и override?

### Workers
- Что поручать Aider, а что оставлять основному orchestrator?
- Нужен ли OpenHands уже в v1 или только позже?
- Какие worker'ы обязательны в самом начале?

### Безопасность
- Какой allowlist у tools?
- Где проходит boundary между project files и host system?
- Как защитить memory files и skills от prompt injection?
- Как организовать approvals, особенно для destructive действий?

### Эволюция v1 → v2
- Какие части стоит сразу строить модульно?
- Что должно быть интерфейсом, а что пока можно hardcode?
- Когда переходить с SQLite на Postgres, если вообще переходить?

## Желаемый следующий шаг

Нужно перейти от этого архитектурного брифа к **конкретной технической спецификации v1**, включающей:

1. точную структуру папок;
2. SQLite schema;
3. Pydantic-модели сущностей;
4. LangGraph state schema;
5. список graph nodes и contracts между ними;
6. memory write/read policy;
7. search/ranking policy;
8. boundaries между orchestrator, workers и gateways.

## Формулировка задачи для Claude Code

Нужно спроектировать v1 self-hosted project-centric agent system.

Требования:

- Проект — основная единица памяти.
- Возврат к проекту через годы без потери контекста.
- Структурированная память вместо бесконечного transcript.
- LangGraph как основной orchestration framework.
- SQLite + FTS5 + embeddings как стартовый storage/retrieval stack.
- Aider как базовый coding worker.
- Возможность позже подключить OpenHands SDK.
- Безопасный sandbox/tool execution.
- Четкое разделение project memory, session memory, artifact memory и procedural memory.
- Markdown-first хранение ключевых знаний проекта.

Нужно выдать:

- целевую архитектуру v1;
- файловую структуру;
- схему данных;
- граф узлов;
- contracts между слоями;
- список компромиссов и рисков;
- рекомендуемый порядок реализации.
