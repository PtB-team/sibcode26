# API · общий контракт бэка и фронта

Источник правды для обеих сторон. Бэк реализует, фронт пишет против него (сначала в мок-режиме). Контекст — в [README.md](README.md), смысл полей риска и сигналов — в [BACKEND.md](BACKEND.md), разделы 4–5.

---

## 6. API

Базовый URL: `/api/v1`. Формат JSON, время в ISO 8601 с таймзоной. Документация OpenAPI генерируется автоматически: `/docs` и `/openapi.json`.

### 6.1 Сущности

```
Object (объект залога)
 ├── 1 Loan (кредит: дата выдачи, DPD, транши)      ← АБС / синтетика
 ├── * Checkpoint (стадия к дате по договору)
 ├── * Flight (облёт) 1 ── * Image (снимок) 1 ── * Detection
 │          ├── 1 Result (вывод агента готовности)
 │          └── * Review (правки человека)
 ├── * RiskAssessment (оценка риска; последняя — текущая)
 └── * Alert (тревога) 1 ── * Action (мера: рекомендована / подтверждена / выполнена)
```

Есть два разных «светофора», их нельзя путать:
- `risk_level` (`green / yellow / orange / red`) — **риск клиента**, главный показатель интерфейса;
- `data_status` (`ok / review / reshoot / processing / no_data`) — **состояние данных**: можно ли верить последнему облёту.

### 6.2 Эндпоинты

**Объекты**

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/objects` | создать объект |
| `GET` | `/objects` | список; фильтры `risk_level`, `stage`, `data_status`, `q` (поиск по адресу, кадастру, кредиту), `sort` (по умолчанию `-risk`), `page`, `page_size` |
| `GET` | `/objects/{object_id}` | карточка: объект + кредит + график + текущий риск + последний облёт |
| `GET` | `/objects/{object_id}/history` | план и факт для графика прогресса |
| `PUT` | `/objects/{object_id}/loan` | обновить данные кредита (DPD, транши); на хакатоне — ручной ввод синтетики |

**Риск и тревоги**

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/objects/{object_id}/risk` | текущая оценка риска (раздел 4.7) |
| `GET` | `/objects/{object_id}/risk/history` | как менялся риск по датам |
| `POST` | `/risk/recalculate` | пересчитать риск по всем объектам (то же делает ежедневный cron) |
| `GET` | `/alerts` | лента тревог; фильтры `risk_level`, `state` (`open / in_progress / closed`), `page` |
| `POST` | `/alerts/{alert_id}/actions` | подтвердить, отклонить или закрыть меру, записать результат |
| `GET` | `/objects/{object_id}/actions` | журнал мер по объекту |

**Облёты**

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/objects/{object_id}/flights` | загрузить снимки (multipart), ответ `202` со статусом `queued` |
| `GET` | `/objects/{object_id}/flights` | все облёты объекта |
| `GET` | `/flights/{flight_id}` | статус обработки и результат |
| `GET` | `/flights/{flight_id}/images` | снимки с детекциями |
| `GET` | `/images/{image_id}/file` | оригинал |
| `GET` | `/images/{image_id}/thumb` | превью, по длинной стороне 512 px |

**Человек в контуре**

| Метод | Путь | Описание |
|---|---|---|
| `POST` | `/flights/{flight_id}/review` | принять или исправить результат |
| `POST` | `/flights/{flight_id}/reshoot` | вручную отправить на пересъёмку |

**Служебные**

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/meta` | версии модели и правил, классы, стадии, уровни риска, сигналы, меры, цвета |
| `GET` | `/config/stages`, `/config/risk` | веса этапов, пороги отставания и уровней риска (P1) |
| `PUT` | `/config/stages`, `/config/risk` | изменить их без релиза (P1) |
| `GET` | `/health` | состояние сервиса |

### 6.3 Контракты

#### `POST /objects`

Запрос:
```json
{
  "cadastral": "24:50:0700123:45",
  "loan_id": "IZH-2026-0412",
  "address": "д. Минино, ул. Лесная 12",
  "parcel_geojson": {"type": "Polygon", "coordinates": [[[92.870, 56.011], [92.872, 56.011], [92.872, 56.013], [92.870, 56.013], [92.870, 56.011]]]},
  "loan": {
    "issued_at": "2026-04-01",
    "amount": 6000000,
    "dpd": 0,
    "tranches": [
      {"n": 1, "amount": 2000000, "paid_at": "2026-04-05"},
      {"n": 2, "amount": 2500000, "condition_stage": "walls", "paid_at": null}
    ]
  },
  "checkpoints": [
    {"stage": "foundation", "due": "2026-06-30"},
    {"stage": "walls",      "due": "2026-09-30"},
    {"stage": "roof",       "due": "2026-11-30"},
    {"stage": "done",       "due": "2027-06-30"}
  ],
  "project": {
    "floors": 2,
    "footprint_m2": 96,
    "wall_material": "aerated_concrete",
    "roof_type": "gable",
    "source": "Проект ИЖС №17-2026, лист 3"
  }
}
```
`checkpoints` и `project` — то, что «должно быть» по проектной документации. Из `project` в сравнении участвует `wall_material` (раздел 5). Этажность и площадь пока только хранятся и показываются в карточке.
Ответ `201`: объект целиком (как в карточке). Границы участка `parcel_geojson` нужны для проверки, что сняли именно этот участок (раздел 4.4).

#### `GET /objects`

```json
{
  "items": [
    {
      "id": "obj_17",
      "cadastral": "24:50:0700123:45",
      "loan_id": "IZH-2026-0412",
      "address": "д. Минино, ул. Лесная 12",
      "last_flight_id": "fl_88",
      "last_flight_at": "2026-10-28T11:40:00+07:00",
      "stage": "none",
      "stage_label": "Нет работ",
      "readiness_pct": 0,
      "plan_pct": 15,
      "lag_days": 37,
      "dpd": 0,
      "risk_level": "orange",
      "top_signal": {"code": "CHECKPOINT_MISSED", "label": "Контрольная точка сорвана"},
      "recommended_action": {"code": "CALL_CLIENT", "label": "Связаться с клиентом"},
      "next_checkpoint": {"stage": "walls", "due": "2026-09-30"},
      "data_status": "ok",
      "open_alert_id": "al_9"
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

Сортировка по умолчанию: `red` → `orange` → `yellow` → `green`, внутри уровня — по `lag_days` по убыванию.

`data_status` — состояние данных последнего облёта:

| `data_status` | Когда |
|---|---|
| `ok` | результат есть, уверенность высокая или принят человеком |
| `review` | нужна проверка: средняя уверенность, ещё нет решения человека |
| `reshoot` | нужна пересъёмка |
| `processing` | облёт обрабатывается |
| `no_data` | облётов ещё не было |

#### `GET /objects/{object_id}`

```json
{
  "id": "obj_17",
  "cadastral": "24:50:0700123:45",
  "loan_id": "IZH-2026-0412",
  "address": "д. Минино, ул. Лесная 12",
  "parcel_geojson": { "...": "..." },
  "loan": { "...": "как в POST /objects" },
  "checkpoints": [
    {"stage": "foundation", "due": "2026-06-30", "state": "missed"},
    {"stage": "walls",      "due": "2026-09-30", "state": "upcoming"}
  ],
  "risk": { "...": "оценка риска, раздел 4.7" },
  "data_status": "ok",
  "last_flight": { "...": "объект как в GET /flights/{id}" },
  "material": {
    "project": "aerated_concrete",
    "observed": "timber",
    "confidence": 0.86,
    "match": "mismatch",
    "fixed_at_flight_id": "fl_88",
    "reviewed": false
  },
  "next_flight_planned": "2026-07-21"
}
```

`checkpoints[].state`: `upcoming` (срок не наступил), `met` (стадия подтверждена облётом), `missed` (срок прошёл, стадии нет), `unverified` (срок прошёл, облёта после него нет).

#### `GET /objects/{object_id}/history`

```json
{
  "plan": [
    {"date": "2026-04-01", "pct": 0},
    {"date": "2026-06-30", "pct": 15},
    {"date": "2026-09-30", "pct": 45},
    {"date": "2026-11-30", "pct": 65},
    {"date": "2027-06-30", "pct": 100}
  ],
  "fact": [
    {"flight_id": "fl_51", "flown_at": "2026-07-07T10:00:00+07:00", "stage": "none", "readiness_pct": 0, "reviewed": true, "risk_level": "orange"}
  ],
  "actions": [
    {"date": "2026-07-08", "code": "CALL_CLIENT", "label": "Звонок клиенту", "outcome": "Подрядчик сорвал сроки, клиент ищет нового"}
  ]
}
```
Фронт рисует на одном графике плановую линию, точки факта и отметки мер. Если человек исправил результат, в `fact` показываются **исправленные** значения, а `reviewed: true`.

#### `GET /alerts`

```json
{
  "items": [
    {
      "id": "al_9",
      "object_id": "obj_17",
      "address": "д. Минино, ул. Лесная 12",
      "created_at": "2026-07-07T12:00:00+07:00",
      "risk_level": "orange",
      "signals": [{"code": "CHECKPOINT_MISSED", "label": "Контрольная точка сорвана", "text": "По договору фундамент к 30.06.2026, облёт 07.07.2026: работ нет"}],
      "recommended_action": {"code": "CALL_CLIENT", "label": "Связаться с клиентом, узнать причину, обсудить реструктуризацию", "requires_confirmation": true},
      "state": "open",
      "assignee": null
    }
  ],
  "total": 7
}
```

Тревога создаётся, когда уровень риска объекта **растёт**, а не при каждом пересчёте. Пока тревога открыта, повторный такой же сигнал её не дублирует.

#### `POST /alerts/{alert_id}/actions`

```json
{
  "decision": "confirm",
  "action_code": "CALL_CLIENT",
  "outcome": "Подрядчик сорвал сроки, клиент ищет нового. Договорились о повторном облёте через месяц",
  "close_alert": false
}
```
`decision`: `confirm` (мера принята), `reject` (тревога ложная, укажите причину в `outcome`), `done` (мера выполнена, результат в `outcome`). Отклонённые тревоги — материал для подстройки порогов.

#### `POST /objects/{object_id}/flights`

`multipart/form-data`:

| Поле | Тип | Обязательное | Описание |
|---|---|---|---|
| `files` | файл[] | да | JPG/PNG, до 30 МБ каждый, 1–20 файлов |
| `views` | строка | нет | JSON-массив той же длины, что `files`: `["N","E","S","W","top_low","top_high"]`; `null` — определить из EXIF |
| `flown_at` | строка | нет | дата облёта; по умолчанию берётся из EXIF |

Ответ `202`:
```json
{"flight_id": "fl_88", "status": "queued"}
```

#### `GET /flights/{flight_id}`

```json
{
  "flight_id": "fl_88",
  "object_id": "obj_17",
  "status": "done",
  "flown_at": "2026-10-28T11:40:00+07:00",
  "uploaded_at": "2026-10-28T15:02:11+07:00",
  "images_count": 5,
  "result": { "...": "выход агента готовности, см. 3.6" },
  "material_result": { "...": "выход агента материала, см. 5.6; null, если стен не видно" },
  "review": null,
  "error": null
}
```

`status`: `queued` → `processing` → `done` | `failed`. При `failed` поле `error` содержит объект ошибки (см. 6.4), а `result` равен `null`.

**Фронт опрашивает этот эндпоинт раз в 2 секунды**, пока статус не станет `done` или `failed`.

#### `GET /flights/{flight_id}/images`

```json
[
  {
    "id": "img_301",
    "view": "N",
    "view_source": "exif",
    "width": 5472,
    "height": 3648,
    "url": "/api/v1/images/img_301/file",
    "thumb_url": "/api/v1/images/img_301/thumb",
    "sha256": "9f2c…",
    "gps": [56.0120, 92.8710],
    "taken_at": "2026-10-28T11:41:12+07:00",
    "quality_ok": true,
    "detections": [
      {
        "class": "walls_full",
        "label": "Стены выведены",
        "conf": 0.93,
        "bbox": [0.075, 0.063, 0.345, 0.332]
      }
    ]
  }
]
```

**`bbox` = `[x1, y1, x2, y2]`, нормализованные от 0 до 1** относительно ширины и высоты снимка. Одинаково подходят и для превью, и для оригинала.

#### `POST /flights/{flight_id}/review`

Принять:
```json
{"action": "accept", "comment": null}
```
Исправить:
```json
{
  "action": "correct",
  "stage": "walls",
  "readiness_pct": 40,
  "comment": "Стропила не установлены, на снимке N штабель досок"
}
```

Ответ `201`:
```json
{
  "id": "rev_12",
  "flight_id": "fl_88",
  "action": "correct",
  "stage": "walls",
  "readiness_pct": 40,
  "comment": "…",
  "author": "ivanov",
  "created_at": "2026-10-28T16:10:00+07:00"
}
```

Результат модели **не перезаписывается**: правка хранится отдельно. Это и журнал аудита, и разметка для дообучения. В интерфейсе показывается последняя правка, если она есть.

#### `GET /meta`

```json
{
  "model_version": "yolo26m-det@v1",
  "material_model_version": "yolo26m-cls@v1",
  "rules_version": "stages@v1",
  "mock": false,
  "views": [
    {"id": "top_low", "label": "Сверху: дом"},
    {"id": "top_high", "label": "Сверху: участок"},
    {"id": "N", "label": "Север"},
    {"id": "E", "label": "Восток"},
    {"id": "S", "label": "Юг"},
    {"id": "W", "label": "Запад"}
  ],
  "stages": [
    {"id": "none",       "label": "Нет работ",    "order": 0},
    {"id": "foundation", "label": "Фундамент",    "order": 1},
    {"id": "walls",      "label": "Стены",        "order": 2},
    {"id": "roof",       "label": "Кровля",       "order": 3},
    {"id": "openings",   "label": "Окна и двери", "order": 4},
    {"id": "facade",     "label": "Фасад",        "order": 5},
    {"id": "done",       "label": "Готов",        "order": 6}
  ],
  "classes": [
    {"id": "walls_full", "label": "Стены выведены", "color": "#2E7D32"}
  ],
  "materials": [
    {"id": "brick",            "label": "Кирпич",               "group": "stone"},
    {"id": "aerated_concrete", "label": "Газобетон / пеноблок", "group": "blocks"},
    {"id": "ceramic_block",    "label": "Керамический блок",    "group": "blocks"},
    {"id": "timber",           "label": "Брус / бревно",        "group": "wood"},
    {"id": "frame",            "label": "Каркас",               "group": "wood"},
    {"id": "sip",              "label": "СИП-панели",           "group": "wood"},
    {"id": "monolith",         "label": "Монолит",              "group": "concrete"},
    {"id": "hidden",           "label": "Скрыт отделкой",       "group": null},
    {"id": "unclear",          "label": "Не определить",        "group": null}
  ],
  "risk_levels": [
    {"id": "green",  "label": "По плану",           "color": "#2E7D32", "order": 0},
    {"id": "yellow", "label": "Наблюдать",          "color": "#F9A825", "order": 1},
    {"id": "orange", "label": "Связаться с клиентом", "color": "#EF6C00", "order": 2},
    {"id": "red",    "label": "Срочно",             "color": "#C62828", "order": 3}
  ],
  "signals": [
    {"id": "CHECKPOINT_MISSED", "label": "Контрольная точка сорвана", "severity": "high"}
  ],
  "actions": [
    {"id": "SCHEDULE_FLIGHT", "label": "Повторный облёт",      "requires_confirmation": false},
    {"id": "REMIND_CLIENT",   "label": "Напоминание клиенту",  "requires_confirmation": false},
    {"id": "CALL_CLIENT",     "label": "Связаться с клиентом", "requires_confirmation": true},
    {"id": "HOLD_TRANCHE",    "label": "Приостановить транш",  "requires_confirmation": true},
    {"id": "OFFER_RESTRUCTURING", "label": "Предложить реструктуризацию / каникулы", "requires_confirmation": true},
    {"id": "MANUAL_INSPECTION",   "label": "Ручная проверка, выезд", "requires_confirmation": true},
    {"id": "SOFT_COLLECTION",     "label": "Передать в soft collection", "requires_confirmation": true}
  ]
}
```

Фронт **не хардкодит** названия классов, материалов, стадий, уровней риска, сигналов, мер и цвета: всё берётся из `/meta`.

### 6.4 Ошибки

Любая ошибка возвращается в одном формате:
```json
{"error": {"code": "NOT_ENOUGH_VIEWS", "message": "Нужны оба снимка сверху и минимум 3 фасада", "details": {}}}
```

| HTTP | `code` | Когда |
|---|---|---|
| 400 | `VALIDATION_ERROR` | неверные поля запроса |
| 400 | `VIEWS_MISMATCH` | длина `views` не совпадает с числом файлов |
| 413 | `FILE_TOO_LARGE` | файл больше 30 МБ |
| 415 | `UNSUPPORTED_FORMAT` | не JPG/PNG |
| 404 | `NOT_FOUND` | нет объекта, облёта или снимка |
| 409 | `FLIGHT_NOT_READY` | ревью до окончания обработки |
| 422 | `NOT_ENOUGH_VIEWS` | обработка невозможна (в `error` облёта) |
| 500 | `INFERENCE_FAILED` | ошибка модели (в `error` облёта) |

`code` стабильный, `message` на русском: фронт может показывать его пользователю как есть.

