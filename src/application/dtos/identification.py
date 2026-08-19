"""Формы заданий идентификации (api.md).

Единицы (правило 2): частоты наружу — в герцах, RMS — в килогерцах, как
у диагностики извлечения и у прогонов фита.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from application.dtos.common import TleSchema
from application.dtos.session import (
    CalibrationResponse,
    ModelCurveResponse,
    PointsResponse,
)


class CreateIdentificationRequest(BaseModel):
    """Запуск перебора по каталогу для размеченного наблюдения сессии.

    Сессия обязательна: перебирать можно только то, что человек уже разметил,
    а разметка живёт в сессии. Автоматического запуска нет — почасовой сканер
    снят вместе с автоизвлечением (decisions/015): признаком «здесь есть
    сигнал» служила именно оно.
    """

    session_uuid: UUID
    observation_id: int


class CandidateResponse(BaseModel):
    """Кандидат каталога с оценкой.

    Поля `stage` у кандидата нет: элементы не двигаются ни у одного из них,
    и стадия у всех была бы одна и та же. Полный фит кандидатов измеренно
    роняет отрыв со ×177 до ×1.06 и в идентификации не участвует — он
    начинается после подтверждения, в созданной сессии.

    `same_launch` показывается отдельной пометкой: перебор идёт сначала
    по объектам запуска, и внутри запуска отрыв правильного объекта на порядок
    выше (замер: ×177 против ×18.9 на 1527888).

    Строки TLE отдаются наружу затем же, зачем хранятся: подтверждение кладёт
    затравкой в сессию именно ту строку, по которой считался RMS.
    """

    norad_id: int
    name: str
    intdes: str
    rms_khz: float
    carrier_hz: float
    same_launch: bool
    tle: TleSchema


class IdentificationResponse(BaseModel):
    """Задание целиком.

    `margin` — во сколько раз лучший кандидат лучше следующего. Величина
    порядка единицы означает, что кандидаты неразличимы, то есть перебор
    ничего не решил, — ровно та же форма диагностики, что `convention_margin`
    у выбора оси частот. UI обязан подавать такое задание как «не определено»,
    а не как список кандидатов.
    """

    uuid: UUID
    created_at: datetime
    observation_id: int
    stage: str
    margin: float | None
    candidates: list[CandidateResponse]
    confirmed_norad_id: int | None
    confirmed_by_sub: str | None
    session_uuid: UUID | None


class IdentificationSummaryResponse(BaseModel):
    """Строка списка. Кандидаты урезаны до верхушки: полный перебор — это
    тысячи строк на задание, а списку нужно решить, куда заходить."""

    uuid: UUID
    created_at: datetime
    observation_id: int
    stage: str
    margin: float | None
    n_candidates: int
    best: CandidateResponse | None
    confirmed_norad_id: int | None
    session_uuid: UUID | None


class ConfirmIdentificationRequest(BaseModel):
    norad_id: int


class ConfirmIdentificationResponse(BaseModel):
    """Идентификация перетекает в уточнение: подтверждение создаёт сессию
    с этим объектом как затравкой (decisions/006)."""

    session_uuid: UUID


class IdentificationTrackResponse(BaseModel):
    """То же, что `GET .../track` у наблюдения сессии, но для задания.

    Форма повторена намеренно: панель водопада на фронте одна и та же,
    а сессии у задания ещё нет. `model` — кривая **лучшего кандидата**:
    именно она отвечает на вопрос «а похоже ли», ради которого водопад
    в этом разделе и показывается.
    """

    calibration: CalibrationResponse | None
    waterfall_url: str | None
    points: PointsResponse | None
    model: ModelCurveResponse | None
    norad_id: int | None = Field(default=None, description="объект лучшего кандидата")
