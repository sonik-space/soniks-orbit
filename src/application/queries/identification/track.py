"""Водопад задания идентификации: калибровка, точки и кривая лучшего кандидата.

Форма ответа та же, что у `GET /sessions/.../track`: панель водопада на фронте
одна и та же, а сессии у задания ещё нет.

Модельная кривая считается **сервером** по элементам лучшего кандидата
и его несущей — фронт эфемерид не вычисляет (правило 9). Она и отвечает
на вопрос «а похоже ли», ради которого водопад в этом разделе показывается.
"""

from __future__ import annotations

from uuid import UUID

from application.dtos.identification import IdentificationTrackResponse
from application.dtos.session import ModelCurveResponse, PointsResponse
from application.interfaces.repositories import IdentificationRepository
from application.services.fitting import calibration_schema, curve_inputs, model_curve
from core.configs.fit import FitSettings
from domain.exceptions import NotFoundError
from domain.models import Identification
from domain.od.elements import Elements


class GetIdentificationTrackQuery:
    def __init__(self, repo: IdentificationRepository, settings: FitSettings) -> None:
        self._repo = repo
        self._settings = settings

    async def __call__(self, identification_uuid: UUID) -> IdentificationTrackResponse:
        identification = await self._repo.get(identification_uuid)
        if identification is None:
            raise NotFoundError(f"задания {identification_uuid} нет")

        best = identification.candidates[0] if identification.candidates else None
        return IdentificationTrackResponse(
            calibration=calibration_schema(identification.calibration),
            waterfall_url=identification.meta.get("waterfall"),
            points=(
                PointsResponse(**identification.points)
                if identification.points
                else None
            ),
            model=self._model(identification, best),
            norad_id=best["norad_id"] if best else None,
        )

    def _model(
        self, identification: Identification, best: dict | None
    ) -> ModelCurveResponse | None:
        """Кривая лучшего кандидата.

        `None`, пока перебора не было или пока нет калибровки: без неё сетку
        времени водопада не построить. Считается на чтение по сохранённым
        в задании строкам, поэтому разойтись с показанным RMS не может.
        """
        if best is None:
            return None
        calibration = curve_inputs(identification.track)
        if calibration is None:
            return None

        return model_curve(
            Elements.from_tle(best["tle1"], best["tle2"]),
            best["carrier_hz"] / 1000.0,
            calibration,
            self._settings.MODEL_CURVE_POINTS,
        )
