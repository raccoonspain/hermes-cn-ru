# Wormsoft.ru LLM API — справочник

> Провайдер моделей: https://ai.wormsoft.ru (портал), API-эндпоинт
> `https://ai.wormsoft.ru/api/gpt` (OpenAI-совместимый, подключён к Hermes
> как custom endpoint — см. `docs/decisions.md` D-001).
>
> **Как собрано:** сайт и `/docs/llm/*` — client-side rendered SPA (Nuxt),
> `WebFetch`/`curl` видят только пустой JS-каркас. Всё содержимое ниже —
> со скриншотов, присланных заказчиком (2026-07-24), а не автопарсинг.
> Если что-то изменится на сайте — обновлять тем же способом (скриншоты).

## Аутентификация

Bearer-токен в заголовке, как у OpenAI:

```
Authorization: Bearer YOUR_API_KEY
Content-Type: application/json
```

Подтверждено на всех трёх эндпоинтах (Responses, Chat Completions,
Embeddings, Models) — единый ключ на весь API.

## Эндпоинты

### Responses API — основной универсальный
```
POST https://ai.wormsoft.ru/api/gpt/responses
```
Legacy-алиасы: `/api/gpt/v1/responses`, `/api/gpt/v1/v1/responses`.

- Документируется как OpenAI-compatible **Responses API**.
- Обязательное поле: `model`. Основной вход — поле `input` (не `messages`).
- Поддерживает text input, multimodal input (`input_text` + `input_image`
  content-блоки, OpenAI-style) и `stream: true`.
- **`store: true` не поддерживается → 400 Bad Request.** Это единственное
  явно задокументированное ограничение параметров.

Минимальный пример:
```bash
curl --request POST \
  --url https://ai.wormsoft.ru/api/gpt/responses \
  --header 'Authorization: Bearer YOUR_API_KEY' \
  --header 'Content-Type: application/json' \
  --data '{
    "model": "openai/gpt-5.4-mini",
    "input": [
      { "role": "user", "content": [
        { "type": "input_text", "text": "Привет" }
      ]}
    ],
    "stream": false
  }'
```

Multimodal вход:
```json
{
  "model": "openai/gpt-5.4",
  "input": [
    { "role": "user", "content": [
      { "type": "input_text", "text": "Опиши..." },
      { "type": "input_image", "image_url": "..." }
    ]}
  ]
}
```

### Chat Completions API — привычный OpenAI-style
```
POST https://ai.wormsoft.ru/api/gpt/chat/completions
```
Legacy-алиасы: `/api/gpt/v1/chat/completions`, `/api/gpt/v1/completions`.

- Обязательные поля: `model`, `messages`.
- Поддерживает `tools`, tool calls, `stream`.
- Ответ с tool call — стандартный OpenAI-формат
  (`choices[0].message.tool_calls[].function.{name,arguments}`,
  `finish_reason: "tool_calls"`).

Минимальный пример — как в Responses API, только `messages` вместо `input`
(`[{"role": "user", "content": "Привет"}]`).

### Embeddings API
```
POST https://ai.wormsoft.ru/api/gpt/embedding
POST https://ai.wormsoft.ru/api/gpt/embeddings
```
Два равнозначных алиаса пути. Возвращает векторное представление текста —
**не для генерации ответа ассистента**.

**Поддерживается ровно одна модель: `qwen/qwen3-embedding:8b`.** Это и
есть та модель, которую мы наметили под embeddings/память в D-001 — других
вариантов на этой подписке нет.

```bash
curl --request POST \
  --url https://ai.wormsoft.ru/api/gpt/embedding \
  --header 'Authorization: Bearer YOUR_API_KEY' \
  --header 'Content-Type: application/json' \
  --data '{ "model": "qwen/qwen3-embedding:8b", "content": "Что такое машинное обучение?" }'
```
Ответ: `{"object":"list","data":[{"object":"embedding","embedding":[...],"index":0}],"model":"qwen/qwen3-embedding:8b"}`.

### Models API — каталог моделей (discovery)
```
GET https://ai.wormsoft.ru/api/gpt/models
```
Возвращает `{"object":"list","data":[{"id","object":"model","input_modalities":[...],"output_modalities":[...],"capabilities":{"vision":true,...}}]}`.
Полезно для программной проверки, какие модели/capabilities реально
доступны на ключе, без хардкода — можно дёрнуть при старте настройки
Hermes вместо ручной сверки таблицы ниже.

## Матрица ошибок

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

### 429 — два РАЗНЫХ источника (важно!)
429 может означать **два независимых лимита**, и их нужно различать:
1. **Кончились кредиты** окна подписки (напр. 3 000 000 / 4 часа на Payed).
2. **Rate limit** — превышена скорость запросов (запросов/сек), *отдельно*
   от кредитов. Формат `N / T` в таблице подписок (см. ниже). На Payed это
   **120 запросов/минуту**. Даже если кредиты ещё есть — 121-й запрос за
   минуту получит 429.

Для агентных сценариев (Hermes делает много быстрых tool-call-ходов подряд,
особенно при параллельной делегации) rate limit может сработать раньше,
чем кончатся кредиты. Смотреть на сообщение об ошибке — оно должно
различать "user reached the limit" (кредиты) от превышения rate limit
(судя по докам — тоже 429, текст сообщения может отличаться; сама
документация ошибок явно не разделяет эти два случая одним и тем же
статусом, будем проверять эмпирически).

### 400 Bad Request
Unsupported model, несовместимые параметры, `store: true` на `/responses`.

### 500
И основной, и fallback-путь на стороне wormsoft не смогли обработать
запрос — не наша сторона, повторить позже.

### Fallback and transparency
Сервис может использовать резервный маршрут при редких технических сбоях
— это защитный сценарий, не обычная маршрутизация. **Ориентироваться на
фактическую модель в ответе, а не в запросе** — особенно важно для наших
`wormsoft/*`-алиасов, см. ниже: они и так всегда маршрутизируются через
список моделей, это отдельный (штатный) механизм, не «fallback» из этого
раздела.

## Полная таблица моделей (24 модели, цены за 1M токенов)

Формат: Input / Output / Cache / Context / Capabilities.

| Model | Input | Output | Cache | Context | Caps |
|---|---|---|---|---|---|
| deepseek-ai/deepseek-v4-flash | 100 000 | 800 000 | 10 000 | 1 000 000 | tools, reasoning |
| deepseek-ai/deepseek-v4-pro | 1 100 000 | 2 000 000 | 300 000 | 1 000 000 | tools, reasoning |
| google/gemma4:31b | 40 000 | 200 000 | 500 | 262 144 | vision, tools, reasoning |
| kimi/kimi-k2.6 | 250 000 | 1 500 000 | 35 000 | 260 000 | vision, tools, reasoning |
| kimi/kimi-k2.7-code | 1 100 000 | 4 500 000 | 50 000 | 256 000 | vision, tools, reasoning |
| minimaxai/minimax-m2.5 | 40 000 | 100 000 | 10 000 | 196 608 | tools, reasoning |
| minimaxai/minimax-m3 | 1 100 000 | 2 000 000 | 300 000 | 1 000 000 | vision, tools |
| nvidia/nemotron-3-ultra | 1 100 000 | 2 000 000 | 300 000 | 256 000 | tools, reasoning |
| openai/gpt-oss:120b | 5 000 | 8 000 | 0 | 131 072 | tools, reasoning |
| openai/gpt-oss:20b | 1 000 | 4 000 | 0 | 131 072 | tools, reasoning |
| qwen/qwen3-embedding:8b | 8 000 | 0 | 0 | 16 000 | — (embeddings only) |
| qwen/qwen3.6:27b | 80 000 | 350 000 | 1 000 | 150 000 | vision, tools |
| qwen/qwen3.6:35b-a3b | 20 000 | 800 000 | 1 000 | 100 000 | vision, tools |
| wormsoft/agent/high | 650 000 | 3 400 000 | 20 000 | 400 000 | tools, reasoning |
| wormsoft/agent/low | 400 | 4 200 | 50 | 130 000 | tools, reasoning |
| wormsoft/agent/medium | 25 000 | 800 000 | 50 | 200 000 | tools, reasoning |
| wormsoft/code/high | 200 000 | 3 000 000 | 30 000 | 400 000 | tools, reasoning |
| wormsoft/code/low | 500 | 5 000 | 50 | 130 000 | tools, reasoning |
| wormsoft/code/medium | 30 000 | 1 000 000 | 50 | 200 000 | tools, reasoning |
| wormsoft/vision/high | 1 100 000 | 4 200 000 | 35 000 | 400 000 | vision, tools, reasoning |
| wormsoft/vision/low | 800 | 5 500 | 50 | 110 000 | vision, tools, reasoning |
| wormsoft/vision/medium | 35 000 | 1 100 000 | 50 | 200 000 | vision, tools, reasoning |
| zai/glm-5.1 | 900 000 | 3 500 000 | 100 000 | 200 000 | tools, reasoning |
| zai/glm-5.2 | 1 300 000 | 4 000 000 | 150 000 | 1 000 000 | tools, reasoning |

Также в каталоге (страница Models Overview) фигурируют `openai/gpt-5.2`,
`gpt-5.2-codex`, `gpt-5.3-codex`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.5`,
`qwen/qwen3.5-35b`, `qwen3.5-plus`, `qwen3.6-plus`, `google/gemma4:26b` —
без цен на скриншотах (не входят в таблицу «24 модели» с ценами; вероятно
превью/более широкий список, чем прайс-лист). Для расчётов ориентируемся
на таблицу выше как на основной источник цен.

## System Aliases — `wormsoft/<type>/<level>` это НЕ одна модель

Важное уточнение к D-001: каждый алиас `wormsoft/agent|code|vision/low|medium|high`
— это не конкретная модель, а **упорядоченный список моделей-кандидатов**
(видимо, fallback-цепочка: если первая недоступна/перегружена — пробуют
следующую). Биллинг идёт по цене самого алиаса из таблицы выше —
независимо от того, какая модель в цепочке реально ответила (см.
«Прозрачность ответа» — фактическую модель нужно смотреть в ответе).

| Алиас | Цепочка моделей (по порядку) |
|---|---|
| `wormsoft/agent/low` | qwen/qwen3-v1 → qwen/qwen3.5:235b-a22b → qwen/qwen3.6:35b-a3b → deepseek-ai/deepseek-v3.1 |
| `wormsoft/code/low` | qwen/qwen3.6:35b-a3b → deepseek-ai/deepseek-v3.1 |
| `wormsoft/vision/low` | google/gemma4:31b → qwen/qwen3-v1 |
| `wormsoft/agent/medium` | google/gemma4:31b → qwen/qwen3.6:27b → qwen/qwen3.6:35b-a3b → minimaxai/minimax-m2.7 |
| `wormsoft/code/medium` | google/gemma4:31b → qwen/qwen3.6:27b → minimaxai/minimax-m2.7 |
| `wormsoft/vision/medium` | google/gemma4:31b → qwen/qwen3.6:27b |
| `wormsoft/agent/high` | minimaxai/minimax-m3 → kimi/kimi-k2.6 → zai/glm-5.1 |
| `wormsoft/code/high` | minimaxai/minimax-m3 → kimi/kimi-k2.7-code → kimi/kimi-k2.6 → zai/glm-5.1 |
| `wormsoft/vision/high` | minimaxai/minimax-m3 → kimi/kimi-k2.6 |

Часть моделей в цепочках (`qwen/qwen3-v1`, `qwen/qwen3.5:235b-a22b`,
`deepseek-ai/deepseek-v3.1`, `minimaxai/minimax-m2.7`) вообще не встречаются
как самостоятельные строки в таблице цен — то есть напрямую их вызвать
(и узнать их цену) нельзя, только через алиас.

## Таблица подписок и rate limit

Данные грузятся динамически из `/api/user-connector/subscription-limits`.

**Rate limit — это отдельный от кредитов лимит.** Кредиты — сколько
токенов можно потратить между сбросами. Rate limit (`N / T`) — сколько
*запросов* можно отправить за период `T`, независимо от того, сколько
кредитов осталось. Пример из доки: тариф Free — 10 запросов/600 сек; даже
с полным запасом кредитов 11-й запрос за 10 минут получит 429.

Для интерактивного чата — с запасом. Для пакетных задач (обработка файлов,
агентные сценарии, скрипты) документация прямо рекомендует **делать паузы
между запросами / распределять нагрузку во времени**.

| Подписка | Кредиты | Период сброса | Rate limit | Стоимость |
|---|---|---|---|---|
| Free | 5 000 | каждые 20 часов | 10 / 10 мин | 0 ₽/мес |
| Promo | 150 000 | каждые 8 часов | 30 / 2 мин | 500 ₽/мес |
| Simple | 500 000 | каждые 5 часов | 60 / 1 мин | 1 500 ₽/мес |
| **Payed** (наш тариф) | **3 000 000** | **каждые 4 часа** | **120 / 1 мин** | 2 500 ₽/мес |
| Wormsoft developer | 5 000 000 | каждые 2 часа | 150 / 1 мин | 6 000 ₽/мес |
| Wormsoft boss | 10 000 000 | каждый 1 час | 200 / 1 мин | 12 000 ₽/мес |

## Что это значит для нас практически

- **429 "user reached the limit"** ⇒ кончились кредиты 4-часового окна.
  Реакция: подождать до сброса, либо пересмотреть роутинг (D-001) —
  меньше рутины через дорогие алиасы/модели.
- **429 без такого текста / на коротких сериях запросов** ⇒ скорее
  всего это **rate limit** (120 запросов/мин на Payed), а не кредиты.
  Особенно вероятно при: параллельной делегации Hermes
  (`delegation.max_concurrent_children`), быстрых цепочках tool-call'ов,
  пакетной обработке (транскрибация видео пачкой, конвертация много
  документов подряд). Реакция: не увеличивать параллелизм бездумно,
  добавить паузы/бэкофф на стороне скриптов, где это наш собственный код
  (не Hermes).
- **400** ⇒ опечатка в имени модели/алиаса, либо `store: true` на
  `/responses`, либо параметр, который Hermes передал, а wormsoft не
  поддерживает.
- **500** ⇒ не наша сторона, повторить позже.
- **401/403 на `/models`** ⇒ протух/неверный ключ — проверить `~/.hermes/.env`.
- Embeddings/память в Hermes может использовать только
  `qwen/qwen3-embedding:8b` — другой модели для этого на этой подписке нет.
- В логах фиксировать фактическую модель из ответа, а не только
  запрошенный алиас — при `wormsoft/*` это может быть любая модель из
  цепочки.
