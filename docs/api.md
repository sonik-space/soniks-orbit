# HTTP API

FastAPI, префикс `/api/v1`. Все маршруты требуют Keycloak JWT.
Схема OpenAPI отдаётся на `/openapi.json` — из неё генерируется клиент фронтенда,
см. [frontend.md](frontend.md).

Один маршрут — один файл, как в `soniks-backend/src/presentation/api/v2/routers/`.

Частоты в API — **герцы**. Время — ISO 8601 UTC. Килогерцы появляются только
в полях с суффиксом `_khz` (RMS, невязки), потому что так их показывает `rffit`
и так их привык читать оператор.

---

## Сессии

### `POST /api/v1/sessions`

```json
{ "name": "LOBACHEVSKY уточнение",
  "norad_id": 98423,
  "observation_ids": [1037258, 1039405],
  "seed": { "tle0": "...", "tle1": "...", "tle2": "..." } }
```

`seed` необязателен: по умолчанию берётся TLE первого наблюдения.
Извлечение треков ставится в очередь сразу. → `201`

### `GET /api/v1/sessions?limit&cursor`

```json
{ "items": [ { "uuid": "...", "name": "...", "norad_id": 98423,
               "status": "fitted", "rms_khz": 0.42, "n_obs": 5 } ],
  "next": "..." }
```

### `GET /api/v1/sessions/{uuid}`

```json
{ "uuid": "...", "name": "...", "norad_id": 98423, "status": "fitted",
  "seed_tle": { "tle0": "...", "tle1": "...", "tle2": "..." },
  "observations": [
    { "observation_id": 1039405,
      "start": "2026-01-05T09:20:00Z", "end": "2026-01-05T09:28:00Z",
      "station_name": "Сампо-400 [R1NAV]", "ground_station": 13,
      "waterfall_url": "https://storage.yandexcloud.net/...",
      "max_altitude": 74.2,
      "extraction_status": "ok", "n_points": 384,
      "rms_khz": 0.44, "carrier_hz": 435975120.5 } ],
  "latest_fit": { "fit_run_id": "...", "rms_khz": 0.42,
                  "elements_out": { }, "tle": { } } }
```

### `DELETE /api/v1/sessions/{uuid}`

---

## Наблюдения в сессии

### `POST /api/v1/sessions/{uuid}/observations`

`{ "observation_ids": [1035076] }` → `202`, извлечение в очереди.

### `DELETE /api/v1/sessions/{uuid}/observations/{observation_id}`

### `GET /api/v1/sessions/{uuid}/observations/{observation_id}/track`

```json
{ "calibration": {
    "img_w": 841, "img_h": 1676,
    "plot_left": 81, "plot_top": 15, "plot_w": 600, "plot_h": 1546,
    "t_min": "2026-08-16T10:32:52.930Z", "t_max": "2026-08-16T10:39:09.100Z",
    "f_min_hz": -28800.0, "f_max_hz": 28743.75,
    "center_freq_hz": 435973500.0, "samp_rate": 57600, "bin_hz": 56.25 },
  "waterfall_url": "https://storage.yandexcloud.net/...",
  "points": {
    "mjd": [], "f_abs_hz": [], "f_offset_hz": [],
    "snr": [], "weight": [], "enabled": [], "source": [] },
  "extraction": { "status": "ok", "error": null } }
```

`calibration` — рамка осей, найденная сервисом, плюс параметры сетки.
Всё, что нужно фронту, чтобы обрезать картинку по рамке и линейно отображать
экран в данные. **Своей геометрии фронт не вычисляет и картинку не анализирует.**

### `PUT /api/v1/sessions/{uuid}/observations/{observation_id}/track`

Полная замена набора точек.

```json
{ "points": { "mjd": [], "f_offset_hz": [], "enabled": [], "source": [], "weight": [] } }
```

`f_abs_hz` **не принимается от клиента** — сервер вычисляет его сам, снимая
доплер-коррекцию по замороженному TLE наблюдения (правило 9 из
[ai-development-rules.md](ai-development-rules.md)). Ручная точка приходит с
`source: "manual"` и `f_offset_hz`.

→ `200` с пересчитанным блоком точек.

### `POST /api/v1/sessions/{uuid}/observations/{observation_id}/reextract`

```json
{ "snr_threshold": 4.0, "bin_seconds": 1.0, "peak_width_tolerance": [0.3, 4.0] }
```

Перезапуск автоизвлечения с другими параметрами. → `202`.
Ручные точки при этом сохраняются, автоматические заменяются.

---

## Фит

### `POST /api/v1/sessions/{uuid}/fits`

**Синхронный**, обычно менее секунды.

```json
{ "prior_sigmas": { "inclination_deg": 0.05, "raan_deg": 0.5,
                    "eccentricity": 0.001, "argp_deg": 20.0,
                    "mean_anomaly_deg": 20.0, "argp_plus_m_deg": 5.0,
                    "mean_motion_rev_day": 0.005, "bstar": 1e-4 },
  "f_scale": 0.5,
  "observation_ids": [1037258, 1039405] }
```

Все поля необязательны; умолчания — из `core/configs/fit.py`.

```json
{ "fit_run_id": "...", "status": "ok",
  "rms_khz": 0.42, "rms_pre_khz": 3.87, "n_points": 1240,
  "elements_in":  { "inclination_deg": 97.41, "...": 0 },
  "elements_out": { "inclination_deg": 97.4103, "...": 0 },
  "prior_dominated": ["eccentricity", "bstar"],
  "tle": { "tle0": "LOBACHEVSKY", "tle1": "1 98423U...", "tle2": "2 98423..." },
  "per_observation": [ { "observation_id": 1039405, "rms_khz": 0.44,
                         "carrier_hz": 435975120.5, "n": 384 } ],
  "residuals": { "1039405": [0.12, -0.31, ...] } }
```

`prior_dominated` перечисляет элементы, которые данные не сдвинули — UI должен
показать их иначе, чем определённые, иначе оператор примет затравку за результат.

`residuals` индекс-в-индекс соответствует `points` того же наблюдения.

### `GET /api/v1/sessions/{uuid}/fits` — история прогонов
### `GET /api/v1/fits/{fit_run_id}` — тот же формат, что у `POST`

---

## Публикация

### `POST /api/v1/fits/{fit_run_id}/reepoch`

```json
{ "epoch_iso": "2026-01-05T09:23:57Z" }
```
или `{ "epoch_yyddd": "26005.391632037" }`, или
`{ "epoch": "latest_observation" }`.

→ `{ "tle": { "tle0": "...", "tle1": "...", "tle2": "..." } }`

### `POST /api/v1/fits/{fit_run_id}/publish`

```json
{ "mode": "publish", "reepoch_to": "latest_observation" }
```

`mode`: `publish` — записать в каталог СОНИКС с источником `Fitted`;
`propose` — отправить на модерацию.

Если вызывающий не владеет спутником, `mode` принудительно становится `propose`.

**Порог качества проверяется на сервере до обращения к Django:**

| Условие | Значение |
|---|---|
| RMS | ≤ 1.0 кГц |
| Точек | ≥ 100 |
| Наблюдений | ≥ 2 |
| Расхождение положения с затравкой на эпохе | ≤ 50 км |

→ `200 { "published_tle_id": 12345 }` · `403` нет прав ·
`409` не пройден порог, в теле — какое именно условие.

Ослабление порогов — только вместе с правкой
[decisions/007-publishing.md](decisions/007-publishing.md).

---

## Идентификация

### `GET /api/v1/identifications?status=pending&limit&cursor`
### `GET /api/v1/identifications/{uuid}`

```json
{ "uuid": "...", "observation_id": 1041233, "stage": "fitted",
  "candidates": [ { "norad_id": 63174, "name": "OBJECT L",
                    "intdes": "2026-015L", "rms_khz": 0.38,
                    "carrier_hz": 435975300.0, "stage": "fitted" },
                  { "norad_id": 63175, "rms_khz": 4.71, "stage": "screening" } ] }
```

### `POST /api/v1/identifications/{uuid}/confirm`

`{ "norad_id": 63174 }` → `{ "session_uuid": "..." }` — создаётся сессия
с этим объектом как затравкой.

### `POST /api/v1/identifications/{uuid}/reject`

---

## Ошибки

Формат — как в `soniks-backend`. Значимые коды:

| Код | Когда |
|---|---|
| `422` | у водопада нет `satnogs:wf-dat`; не найдена рамка осей или colorbar |
| `409` | не пройден порог качества при публикации |
| `403` | нет прав на публикацию для этого спутника |
| `400` | меньше 20 включённых точек или меньше 2 наблюдений для фита |

Отдельно про `422` из-за отсутствия `satnogs:wf-dat`: это **ожидаемое** состояние
для наблюдений до июля 2026 и для станций на клиентах старше 2.2.x.
UI должен объяснять причину, а не показывать ошибку.
