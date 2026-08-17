"""Формы запросов и ответов фита (api.md).

Частоты — **герцы**. Время — ISO 8601 UTC. Килогерцы только в полях
с суффиксом `_khz`: так их показывает `rffit` и так их привык читать оператор.

Отдельный модуль, а не рост `dtos/session.py`: сценариев два, и общего
у них ровно то, что вынесено в `dtos/common.py`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from application.dtos.common import ElementsSchema, TleSchema


class PriorSigmasSchema(BaseModel):
    """Априорные σ (algorithms.md §4.3).

    Имена полей — человеческие, а не имена параметров ядра: `eccentricity`
    вместо `ecc`, `mean_motion_rev_day` вместо `rev_per_day`. Отображение
    на `PARAM_NAMES` живёт в одном месте — `services/fitting.py`.

    Все поля необязательны: незаданное берётся из `core/configs/fit.py`.
    """

    inclination_deg: float | None = Field(default=None, gt=0.0)
    raan_deg: float | None = Field(default=None, gt=0.0)
    eccentricity: float | None = Field(default=None, gt=0.0)
    argp_deg: float | None = Field(default=None, gt=0.0)
    mean_anomaly_deg: float | None = Field(default=None, gt=0.0)
    mean_motion_rev_day: float | None = Field(default=None, gt=0.0)
    bstar: float | None = Field(default=None, gt=0.0)
    # Реально определяемая комбинация: разрешает вырождение argp/M при e≈0.
    argp_plus_m_deg: float | None = Field(default=None, gt=0.0)


class RunFitRequest(BaseModel):
    """Запуск фита. Все поля необязательны.

    Галочек заморозки параметров здесь нет и не будет: все семь элементов
    всегда свободны, а слабо определённые удерживает приор (decisions/004).
    Флага режима совместимости здесь тоже нет — он живёт в ядре и нужен
    регрессионному тесту, а не оператору (decisions/003).
    """

    prior_sigmas: PriorSigmasSchema | None = None
    f_scale: float | None = Field(default=None, gt=0.0)
    # По умолчанию — все наблюдения сессии, у которых есть точки.
    observation_ids: list[int] | None = None


class PerObservationFitResponse(BaseModel):
    """Несущая своя на каждое наблюдение, и её разброс между проходами
    диагностичен: это погрешность опорного генератора станции плюс уход
    передатчика (decisions/003)."""

    observation_id: int
    rms_khz: float
    carrier_hz: float
    n: int


class ResidualsResponse(BaseModel):
    """Невязки одного наблюдения, **индекс-в-индекс** с его `points`.

    `residual_khz` равен `null` там, где точка выключена или не участвовала
    в прогоне: ноль читался бы как измеренная невязка. `mjd` идёт рядом,
    чтобы панель невязок не запрашивала треки всех наблюдений по отдельности —
    ось времени у неё общая на весь набор.
    """

    mjd: list[float]
    residual_khz: list[float | None]


class FitRunSummaryResponse(BaseModel):
    """Строка истории прогонов.

    Без `residuals` и `per_observation`: десять прогонов по 2500 точек — это
    мегабайты на каждый заход в раздел. Полное тело — из `GET /fits/{id}`.
    """

    fit_run_id: UUID
    created_at: datetime
    status: str
    rms_khz: float
    rms_pre_khz: float
    n_points: int
    elements_out: ElementsSchema
    prior_dominated: list[str]


class FitRunResponse(BaseModel):
    """Прогон целиком.

    `prior_dominated` перечисляет элементы, которые данные не сдвинули — UI
    обязан показать их иначе, чем определённые, иначе оператор примет затравку
    за результат (decisions/004).

    `status: "failed"` — прогон, где `least_squares` не сошёлся или исчерпал
    `max_nfev`. Элементы и невязки в нём всё равно есть: без них не видно,
    что пошло не так (algorithms.md §4.4).
    """

    fit_run_id: UUID
    created_at: datetime
    status: str
    rms_khz: float
    rms_pre_khz: float
    n_points: int
    elements_in: ElementsSchema
    elements_out: ElementsSchema
    prior_dominated: list[str]
    tle: TleSchema
    per_observation: list[PerObservationFitResponse]
    residuals: dict[int, ResidualsResponse]
    # Приорные σ, f_scale, участвовавшие наблюдения — без них прогон
    # невоспроизводим (правило 10).
    config: dict
