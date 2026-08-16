# Модель данных

Postgres, SQLAlchemy 2 (async). Миксины `UUIDMixin` / `TimestampMixin` берутся
из `soniks-backend/src/infrastructure/postgres/models/mixins.py`.

Сервис **не дублирует** справочники СОНИКС (спутники, станции, транспондеры).
Он хранит только то, чего в СОНИКС нет: рабочие сессии, размеченные точки,
прогоны фита и задания идентификации.

---

## Таблицы

### `od_sessions`

Рабочая сессия — один спутник и набор наблюдений, по которым идёт уточнение.

| Поле | Тип | Смысл |
|---|---|---|
| `uuid` | UUID PK | |
| `name` | str | человекочитаемое имя |
| `norad_id` | int, null | номер объекта; null, пока не идентифицирован |
| `owner_sub` | str | `sub` из Keycloak JWT |
| `seed_tle0/1/2` | str | затравка |
| `seed_source` | str | `observation` / `manual` / `identification` |
| `status` | str | `draft` / `fitted` / `published` / `archived` |

### `od_session_observations`

| Поле | Тип | Смысл |
|---|---|---|
| `uuid` | UUID PK | |
| `session_uuid` | FK → `od_sessions`, CASCADE | |
| `observation_id` | int | id наблюдения в боевом СОНИКС |
| `meta` | JSONB | **замороженный** ответ Django API |
| `calibration` | JSONB, null | рамка осей, `f_min/f_max`, `t0`, `row_dt`, `nchan` |
| `extraction_status` | str | `pending` / `running` / `ok` / `failed` |
| `extraction_error` | str, null | |
| `points` | JSONB, null | точки трека, см. ниже |

Уникальный индекс `(session_uuid, observation_id)`.

### `od_fit_runs`

| Поле | Тип | Смысл |
|---|---|---|
| `uuid` | UUID PK | |
| `session_uuid` | FK → `od_sessions`, CASCADE | |
| `author_sub` | str | кто запустил |
| `config` | JSONB | приорные σ, `f_scale`, участвовавшие наблюдения, число точек |
| `elements_in` / `elements_out` | JSONB | элементы до и после |
| `tle0/1/2` | str | результат |
| `epoch_mjd` | float | |
| `rms_khz` / `rms_pre_khz` | float | после и до фита |
| `n_points` | int | |
| `per_observation` | JSONB | `{obs_id: {rms_khz, carrier_hz, n}}` |
| `residuals` | JSONB | `{obs_id: [невязка_кГц, ...]}`, индексы совпадают с `points` |
| `prior_dominated` | JSONB | какие элементы удержаны приором |
| `status` | str | `ok` / `failed` |
| `published_at` | datetime, null | |
| `published_mode` | str, null | `publish` / `propose` |
| `published_tle_id` | int, null | id, вернувшийся из Django |

### `od_identifications`

| Поле | Тип | Смысл |
|---|---|---|
| `uuid` | UUID PK | |
| `observation_id` | int | |
| `stage` | str | `screening` / `fitted` / `confirmed` / `rejected` |
| `candidates` | JSONB | `[{norad_id, name, intdes, rms_khz, carrier_hz, stage}]` |
| `confirmed_norad_id` | int, null | |
| `confirmed_by_sub` | str, null | |

---

## Точки трека: колонки-массивы в JSONB

```json
{
  "mjd":         [60658.816300, ...],
  "f_abs_hz":    [435432630.26, ...],
  "f_offset_hz": [-1250.4, ...],
  "snr":         [12.3, ...],
  "weight":      [1.0, ...],
  "enabled":     [true, ...],
  "source":      ["auto", "manual", ...]
}
```

Все массивы одной длины, индекс — идентификатор точки. Пара
`(observation_id, index)` используется как ключ выделения во всём UI.

Поля:

- `f_abs_hz` — абсолютная принятая частота, доплер снят. Идёт в фит.
- `f_offset_hz` — смещение от центра, как на водопаде. Нужно, чтобы рисовать
  точки без пересчёта эфемерид.
- `weight` — вес по SNR при извлечении, участвует в профилировании несущей.
- `enabled` — снятые человеком точки не удаляются, а гасятся: удаление
  необратимо, а гашение позволяет вернуть.
- `source` — `auto` или `manual`. Ручные точки приходят с фронта только
  как `f_offset_hz`, `f_abs_hz` заполняет сервер (правило 9).

```python
# ponytail: точки лежат блоком в JSONB, а не таблицей od_track_points.
#           Потолок: SQL по отдельным точкам невозможен.
#           Они всегда читаются и пишутся целиком, отдельная таблица дала бы
#           сотни тысяч строк без единого сценария независимого запроса.
#           Разносить, если понадобится поточечная аналитика.
```

Правка трека — один `UPDATE` целого блока, поэтому она атомарна.
Фит читает всё одним запросом, без джойнов.

---

## Проверяемость публикации

Опубликованное TLE должно быть воспроизводимо через месяцы. Для этого:

**`od_session_observations.meta` замораживает ответ API на момент извлечения**,
включая TLE, по которому снималась доплер-коррекция. TLE в каталоге обновляется
каждые 4 часа; без заморозки пересчёт по новому TLE изменил бы смысл уже
посчитанных `f_abs_hz`, и результат перестал бы сходиться.

**`od_fit_runs` фиксирует всё остальное:** элементы на входе и выходе, приорные σ,
`f_scale`, список участвовавших наблюдений, число точек, RMS до и после,
поточечные невязки и несущую каждого прохода.

Вместе этого достаточно, чтобы через произвольное время повторить прогон
и получить те же цифры.

---

## Что не хранится

- Копии наблюдений, спутников, станций — берутся из СОНИКС по требованию.
- PNG водопадов — кешируются на диске по `observation_id` (они неизменяемы),
  но не в БД.
- Каталог для идентификации — кеш в `infrastructure/catalog/`, не таблица.
