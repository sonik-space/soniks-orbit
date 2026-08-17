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
    """Модельная кривая последнего фита на равномерной сетке времени.

    Заменяет `ikhnosoniks`: кривая идёт через весь проход, в том числе там,
    где точек нет. Считает её сервер — фронт доплер не снимает (правило 9).
    """

    mjd: list[float]
    f_offset_hz: list[float]


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


class ReextractRequest(BaseModel):
    """Параметры повторного извлечения. Умолчания — из `core/configs/waterfall.py`,
    те же, при которых получен эталон 0.0250 кГц на 1527888."""

    snr_threshold: float | None = Field(default=None, gt=0.0)
    bin_seconds: float | None = Field(default=None, gt=0.0)
