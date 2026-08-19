# Архитектура

## Где сервис находится

Отдельный сервис, написанный на стеке **soniks-v2** (FastAPI, Python 3.12,
SQLAlchemy async, taskiq), но развёрнутый самостоятельно.

```
          ┌───────────────────────────────┐
          │  soniks-frontend (Next.js)    │
          │  слайс /orbit — UI раздела    │
          └────────────┬──────────────────┘
                       │ HTTP, клиент сгенерирован из OpenAPI
                       ▼
          ┌───────────────────────────────┐        ┌──────────────┐
          │        soniks-orbit           │───────▶│  Keycloak    │
          │  FastAPI + Postgres + taskiq  │  JWT   └──────────────┘
          └────┬──────────────────────┬───┘
               │ читает наблюдения,   │ публикует TLE
               │ водопады, TLE,       │
               │ каталог              │
               ▼                      ▼
     ┌──────────────────────────────────────┐
     │  СОНИКС, боевой Django (sonik.space) │
     └──────────────────────────────────────┘
```

Ни клиент станции, ни модель наблюдения в сети не трогаются: сервис работает
с тем, что СОНИКС уже отдаёт публично. Проработанная альтернатива с выгрузкой
артефакта спектра со станции отложена, см.
[decisions/011](decisions/011-spectrum-artifact.md).

Почему не приложение в Django-монолите и не модуль внутри `soniks-backend` —
см. [decisions/005-placement.md](decisions/005-placement.md).

Сервис работает с **боевыми** данными, а не с репликой dev2, иначе посчитанное TLE
не дошло бы до планирования наблюдений реальной сети —
см. [decisions/009-prod-data.md](decisions/009-prod-data.md).

---

## Структура репозитория

```
soniks-orbit/
├── pyproject.toml            uv; fastapi, sqlalchemy[asyncio], asyncpg, alembic,
│                             dishka, taskiq[reload], taskiq-aio-pika, redis, httpx,
│                             pydantic-settings, pyjwt[crypto], uvicorn,
│                             prometheus-client, numpy, scipy, sgp4, pillow
├── docs/
├── docker_compose/
├── scripts/
│   └── phase0/               одноразовые скрипты снятия риска
├── src/
│   ├── main.py  app.py
│   ├── core/
│   │   ├── configs/          app, database, auth, taskiq, broker, cache,
│   │   │                     logging, network_api, fit, waterfall
│   │   └── containers/       dishka: domain, application, infrastructure
│   │
│   ├── domain/               ← ЧИСТОЕ, без фреймворков (правило 1)
│   │   ├── od/
│   │   │   ├── constants.py    C_KM_S, XKMPER, FLAT
│   │   │   ├── geometry.py     gmst, dgmst, obspos_xyz, range_rate
│   │   │   ├── doppler.py      fac = 1 − v/c, снятие коррекции
│   │   │   ├── elements.py     Elements, обёртка углов, приоры, масштабирование
│   │   │   ├── fit.py          вектор невязок, fit(), FitResult
│   │   │   ├── reepoch.py      classel, rv2el
│   │   │   └── tle.py          разбор и сборка строк, контрольная сумма, alpha-5
│   │   ├── waterfall/
│   │   │   ├── metadata.py     разбор satnogs:wf-dat / wf-signal
│   │   │   └── axes.py         детекция рамки осей и делений оси времени
│   │   ├── models.py           доменные модели
│   │   └── exceptions.py
│   │
│   ├── application/
│   │   ├── interfaces/       network_api, image_fetcher, repositories,
│   │   │                     transaction, tasks
│   │   ├── dtos/
│   │   ├── commands/         session/*, fit/*, identification/*
│   │   ├── queries/
│   │   └── services/         calibration.py, fitting.py, identification.py
│   │
│   ├── infrastructure/
│   │   ├── network_api/      httpx-клиент к боевому Django
│   │   ├── images/           PIL: bytes → (ndarray, dict метаданных), кеш PNG
│   │   ├── catalog/          кеш активного каталога для идентификации
│   │   ├── postgres/         database, transaction, models, repositories, alembic
│   │   ├── tasks/            broker, extract_track, identify
│   │   └── auth/             валидация Keycloak JWT
│   │
│   └── presentation/api/v1/routers/{session,fit,identification}/
└── tests/{unit,regression,golden}/
```

Файлы `src/app.py`, `core/configs/*`, `core/containers/*`,
`infrastructure/postgres/{database,transaction}.py`, `infrastructure/tasks/broker.py`
и валидация JWT берутся из `soniks-backend` почти дословно — они уже generic
и не содержат ничего специфичного для наблюдений.

---

## Слои

```
presentation  →  application  →  domain
                      ↑
              infrastructure реализует
              application/interfaces
```

**`domain/`** — алгоритмы. Без фреймворков, без ввода-вывода, без состояния.
Принимает массивы и словари, возвращает массивы и датаклассы.
Это единственная часть, которая переживёт переезд на v2 без единой правки.

**`application/`** — оркестрация. Знает про `domain` и про **интерфейсы**
инфраструктуры, но не про их реализации.

**`infrastructure/`** — всё грязное: HTTP, PIL, SQL, брокер, JWT.

**`presentation/`** — разбор запроса, вызов, сборка ответа. Логики нет.
Один маршрут — один файл, как в `soniks-backend/src/presentation/api/v2/routers/`.

### Единственное место сшивки

`application/services/calibration.py` — единственное место, где цепочка
«скачать PNG → декодировать → откалибровать → извлечь гребень → снять доплер»
собирается воедино. Если эта последовательность появилась ещё где-то,
это ошибка, а не оптимизация.

### Отличие от soniks-backend

В `soniks-backend` доменный слой разложен как
`domain/{entities,value_objects,exceptions}/<агрегат>/{dtos,enums,models,types}.py`.
Здесь это схлопнуто в один `domain/models.py` и один `domain/exceptions.py`:
на четырёх сущностях такая структура даёт только навигационные издержки.

Разделение сохранено только между `od` и `waterfall` — это два независимых
алгоритма с разными зависимостями и разными тестами.

---

## Синхронное и асинхронное

| Операция | Режим | Почему |
|---|---|---|
| Извлечение трека | **асинхронно** (taskiq) | скачивание PNG плюс поиск по ~1 млн пикселей — секунды |
| Фит | **синхронно** | 5 наблюдений × 500 точек считаются за миллисекунды |
| Идентификация | **асинхронно** (taskiq) | перебор каталога |
| Публикация | синхронно | один HTTP-вызов в Django |

Синхронный фит — сознательное упрощение: не нужны job id, опрос состояния,
вебсокеты и индикаторы прогресса в UI. Асинхронных поверхностей две, а не три.

Если фит когда-нибудь перестанет укладываться в секунду (например, при
идентификации по всему каталогу с полным фитом каждого кандидата) — это уже
другая операция, и она изначально асинхронная.

---

## Состояние и переносимость

Сервис держит своё состояние в собственном Postgres (сессии, точки, прогоны фита,
задания идентификации). Данные СОНИКС он не дублирует, а замораживает снимком
на момент извлечения — см. [data-model.md](data-model.md).

Всё, что специфично для текущего Django, изолировано в
`infrastructure/network_api/` и за интерфейсом `application/interfaces/network_api.py`.
Переезд на v2 — это одна новая реализация этого интерфейса.
Подробности в [integration.md](integration.md).
