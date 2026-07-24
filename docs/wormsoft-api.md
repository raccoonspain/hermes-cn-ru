# Wormsoft.ru LLM API — справочник

> Провайдер моделей: https://ai.wormsoft.ru (портал), API-эндпоинт вида
> `https://ai.wormsoft.ru/api/gpt` (OpenAI-совместимый, подтверждено
> практически при настройке Hermes — см. `docs/decisions.md` D-001).
>
> **Важно:** и портал, и `/docs/llm/*` — client-side rendered SPA (Nuxt,
> `data-ssr="false"`). `WebFetch` и обычный `curl` видят только пустой JS-
> каркас, реальный контент подгружается в браузере. Все страницы `/docs/llm/*`
> (authentication, responses, chat-completions, embeddings, models-overview,
> models, system-aliases, subscriptions) **не получилось спарсить
> автоматически** — ниже только то, что переслал заказчик (скриншот error
> matrix, 2026-07-24). Если понадобится остальное — присылать текстом/
> скриншотом, как в этот раз.

## Матрица ошибок (со скриншота заказчика, 2026-07-24)

| Endpoint | Status | Meaning |
|---|---|---|
| `/responses` | 400 | Unsupported params, incompatible request body, `store: true` |
| `/responses` | 429 | User reached the limit |
| `/responses` | 500 | Primary and fallback processing both failed |
| `/chat/completions` | 400 | Unsupported model or invalid request body |
| `/chat/completions` | 429 | User reached the limit |
| `/embedding` | 400 | Unsupported model or invalid request body |
| `/embedding` | 429 | User reached the limit |
| `/models` | 401/403 | Authorization issues |

### 429 Limit reached
Если пользователь достиг лимита, сервис не выполняет запрос и возвращает
429 с сообщением **user reached the limit**. В контексте нашей подписки
(Payed, 3 000 000 кредитов / 4 часа — см. D-001) это и есть сигнал «бюджет
текущего 4-часового окна исчерпан».

### 400 Bad Request
Возвращается при unsupported model, несовместимых параметрах или
специальных ограничениях вроде `store: true` для `/responses`.

### Fallback and transparency
Сервис использует резервные механизмы для повышения стабильности.
Fallback — это редкий защитный сценарий, а не обычная маршрутизация. Для
клиента важна прозрачность: ориентируйтесь на **фактическую модель**,
указанную в ответе (а не в запросе) — при fallback она может отличаться от
запрошенной.

## Что это значит для нас практически

- **429** от wormsoft ⇒ не баг Hermes и не баг конфига — исчерпан лимит
  кредитов на 4-часовое окно. Реакция: подождать до следующего окна, либо
  (если системно) пересмотреть роутинг моделей D-001 (слишком много
  запросов ушло на дорогие тиры).
- **400** ⇒ почти всегда либо опечатка в имени модели/алиаса, либо Hermes
  отправил параметр, который wormsoft не поддерживает (например `store: true`
  на `/responses`) — смотреть, через какой эндпоинт Hermes фактически бьёт
  (`/responses` vs `/chat/completions`) и что из специфичных полей могло не
  дойти.
- **500** ⇒ упали и основной, и fallback-путь на стороне wormsoft — не
  наша сторона, повторить запрос позже.
- **401/403 на `/models`** ⇒ проблема с API-ключом (протух/неверный/не тот
  scope) — проверить `~/.hermes/.env` на сервере.
- В логах/ответах стоит фиксировать **фактическую** модель, а не только ту,
  что запрашивали — из-за fallback они могут не совпадать.

## Открыто
- Точный формат аутентификации (заголовок, формат ключа) — не подтверждён
  доками, но практически ключ передаётся при настройке через
  `hermes model` → custom OpenAI-compatible endpoint (см. скриншот в истории
  проекта, эндпоинт `https://ai.wormsoft.ru/api/gpt`).
- Детали `/responses` vs `/chat/completions` (когда Hermes использует
  какой), лимиты `/embedding`, точная семантика `system-aliases`
  (`wormsoft/agent/*`, `wormsoft/code/*`, `wormsoft/vision/*`) — не собраны,
  см. предупреждение выше.
