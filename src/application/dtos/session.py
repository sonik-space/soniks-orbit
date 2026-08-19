"""Формы запросов и ответов (api.md).

Частоты — **герцы**. Время — ISO 8601 UTC. Килогерцы только в полях
с суффиксом `_khz`: так их показывает `rffit` и так их привык читать оператор.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from application.dtos.common import ElementsSchema, TleSchema


class CreateSessionRequest(BaseModel):
    name: str
    norad_id: int | None = None
    observation_ids: list[int] = Field(min_length=1)
    # Необязателен: по умолчанию берётся TLE первого наблюдения.
    seed: TleSchema | None = None


class AddObservationsRequest(BaseModel):
    """Дописать наблюдения в существующую сессию — шаг 2 гайда.

    Уже входящие в сессию не считаются ошибкой и просто пропускаются:
    повторный вызов с тем же списком обязан быть безвредным.
    """

    observation_ids: list[int] = Field(min_length=1)


class SeedElementsSchema(BaseModel):
    """Элементы затравки, заданные руками — меню `c` из `rffit.c:753-780`.

    Отдельно от `ElementsSchema`: та описывает результат и все поля в ней
    обязательны, а здесь оператор правит один элемент из семи и не должен
    переписывать остальные шесть. Незаданное берётся из текущей затравки.

    Частоты тут нет намеренно. В `rffit` пункт 12 меню задаёт `d.ffit`, потому
    что несущая там одна на весь набор и её иногда приходится ставить руками.
    У нас несущая своя на каждое наблюдение и решается в замкнутом виде
    (decisions/003) — задавать её нечем и незачем.
    """

    inclination_deg: float | None = Field(default=None, ge=0.0, le=180.0)
    raan_deg: float | None = None
    eccentricity: float | None = Field(default=None, ge=0.0, lt=1.0)
    argp_deg: float | None = None
    mean_anomaly_deg: float | None = None
    mean_motion_rev_day: float | None = Field(default=None, gt=0.0)
    bstar: float | None = None
    epoch: datetime | None = None
    satno: int | None = Field(default=None, ge=1)
    name: str | None = None
    intldes: str | None = Field(default=None, max_length=8)


class UpdateSeedRequest(BaseModel):
    """Замена затравки сессии. Ровно один из трёх способов.

    Затравка перестала быть неизменяемой (decisions/014). Порог публикации
    от этого **не** поехал: он судит расхождение по `elements_in` прогона,
    то есть по той затравке, из которой прогон фитили.
    """

    # Готовые строки: результат чужого фита, свежий Space-Track, что угодно.
    tle: TleSchema | None = None
    # Правка отдельных элементов поверх текущей затравки.
    elements: SeedElementsSchema | None = None
    # Грубый шаблон, когда затравки нет вовсе (клавиша `t` в `rffit`).
    template: Literal["leo", "gto", "gso", "heo"] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        given = [f for f in ("tle", "elements", "template") if getattr(self, f) is not None]
        if len(given) != 1:
            raise ValueError(
                "нужен ровно один из tle, elements, template; передано: "
                + (", ".join(given) or "ничего")
            )
        return self


class SessionObservationResponse(BaseModel):
    observation_id: int
    start: datetime | None = None
    end: datetime | None = None
    station_name: str | None = None
    ground_station: int | None = None
    waterfall_url: str | None = None
    max_altitude: float | None = None
    extraction_status: str
    extraction_error: str | None = None
    n_points: int
    rms_khz: float | None = None
    carrier_hz: float | None = None
    # Запас порядка единицы означает, что конвенции оси неразличимы,
    # то есть трек ненадёжен, и это показывается пользователю (algorithms.md §3).
    convention_margin: float | None = None
    # Частота наблюдения из ответа Django, рядом с `center_freq_hz` калибровки,
    # которая приходит из PNG-чанка. Расхождение — предупреждение в UI: иначе
    # несущая молча его поглотит. На проверенных наблюдениях расхождения нет
    # (открытый вопрос 4 закрыт), но проверка стоит одного поля.
    observation_frequency_hz: float | None = None


class LatestFitResponse(BaseModel):
    """Последний прогон фита сессии — любого статуса: у неуспешного тоже есть
    элементы, и молчать о нём хуже, чем показать со статусом."""

    fit_run_id: UUID
    status: str
    rms_khz: float
    elements_out: ElementsSchema
    tle: TleSchema


class SessionResponse(BaseModel):
    uuid: UUID
    name: str
    norad_id: int | None
    status: str
    seed_tle: TleSchema
    observations: list[SessionObservationResponse]
    # `None`, пока фит ни разу не гонялся.
    latest_fit: LatestFitResponse | None = None


class SessionSummaryResponse(BaseModel):
    """Строка списка. `rms_khz` — от последнего прогона фита любого статуса:
    до него у сессии нет числа, которое описывало бы её целиком."""

    uuid: UUID
    name: str
    norad_id: int | None
    status: str
    n_observations: int
    rms_khz: float | None = None


class CalibrationResponse(BaseModel):
    """Рамка осей и параметры сетки. Всё, что нужно фронту, чтобы обрезать
    картинку по рамке и линейно отображать экран в данные: своей геометрии
    фронт не вычисляет и картинку не анализирует (frontend.md)."""

    img_w: int
    img_h: int
    plot_left: int
    plot_top: int
    plot_w: int
    plot_h: int
    t_min: datetime
    t_max: datetime
    f_min_hz: float
    f_max_hz: float
    center_freq_hz: float
    samp_rate: int
    nchan: int
    bin_hz: float


class PointsResponse(BaseModel):
    """Колонки-массивы, индекс — идентификатор точки. Пара
    `(observation_id, index)` — ключ выделения во всех трёх панелях UI."""

    mjd: list[float] = []
    f_abs_hz: list[float] = []
    f_offset_hz: list[float] = []
    snr: list[float] = []
    weight: list[float] = []
    enabled: list[bool] = []
    source: list[str] = []


class ExtractionStatusResponse(BaseModel):
    status: str
    error: str | None = None


class ModelCurveResponse(BaseModel):
    """Модельная кривая фита на равномерной сетке времени.

    Заменяет `ikhnosoniks`: кривая идёт через весь проход, в том числе там,
    где точек нет. Считает её сервер — фронт доплер не снимает (правило 9).

    `az_deg`/`alt_deg` — та же сетка в горизонтальных координатах, панель
    неба рисуется прямо по ним. `t_ca` — момент наибольшего сближения,
    `t_epoch` — эпоха элементов: вертикальные метки `T_CA` и `T_EP` из `rffit`.
    """

    mjd: list[float]
    f_offset_hz: list[float]
    az_deg: list[float]
    alt_deg: list[float]
    # `null`, если на этой сетке спутник над горизонтом знак скорости не меняет:
    # наблюдение целиком до или целиком после сближения.
    t_ca: datetime | None
    t_epoch: datetime


class TrackResponse(BaseModel):
    calibration: CalibrationResponse | None
    waterfall_url: str | None
    points: PointsResponse
    extraction: ExtractionStatusResponse
    # Модельная кривая последнего прогона фита — замена `ikhnosoniks`.
    # Приходит сюда, а не в ответ фита: рисуется она поверх этого водопада,
    # и панель уже читает этот запрос. `None`, пока фита не было или пока
    # это наблюдение в нём не участвовало.
    model: ModelCurveResponse | None = None


class TrackPointsRequest(BaseModel):
    """Точки, приходящие от клиента при полной замене набора.

    `f_abs_hz` здесь **нет и не будет**: абсолютную частоту считает сервер
    (правило 9). Иначе появятся две реализации снятия доплер-коррекции —
    на Python и на `satellite.js`, — которые обязательно разойдутся,
    и расхождение проявится как необъяснимый вклад в невязки у точек,
    поставленных руками.

    `snr` необязателен и просто возвращается на место: клиент получил его
    в `GET .../track`, и молча обнулять измеренную величину нельзя.
    """

    mjd: list[float] = []
    f_offset_hz: list[float] = []
    enabled: list[bool] = []
    source: list[Literal["auto", "manual"]] = []
    weight: list[float] = []
    snr: list[float] | None = None

    @model_validator(mode="after")
    def columns_are_the_same_length(self) -> Self:
        columns = {
            "f_offset_hz": len(self.f_offset_hz),
            "enabled": len(self.enabled),
            "source": len(self.source),
            "weight": len(self.weight),
        }
        if self.snr is not None:
            columns["snr"] = len(self.snr)

        n = len(self.mjd)
        wrong = {name: size for name, size in columns.items() if size != n}
        if wrong:
            raise ValueError(
                f"колонки точек разной длины: mjd {n}, "
                + ", ".join(f"{name} {size}" for name, size in wrong.items())
            )
        return self


class UpdateTrackRequest(BaseModel):
    points: TrackPointsRequest
