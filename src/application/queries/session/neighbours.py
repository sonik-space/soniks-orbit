"""Кривые соседей по запуску поверх водопада наблюдения.

Упражнение 2 гайда, клавиша `p` в `rfplot`. Раздел показывает точки человека
и модель своего объекта, а водопад при этом полон чужих следов, и отличить
их было нечем. Наложение кривых каталога отвечает на оба вопроса разом:
какая линия чья и какая из них — помеха.

Второй реализации снятия доплера здесь нет: кривая считается тем же
`model_curve`, что и модельная кривая фита (правила 8 и 9). Разница
только в несущей — своей у соседа мы не знаем, поэтому берётся частота
наблюдения, и кривая выходит **сырой**, то есть ровно такой, какой след
чужого объекта и лежит на водопаде (algorithms.md §2).
"""

from __future__ import annotations

from uuid import UUID

from application.dtos.session import NeighbourCurveResponse, NeighboursResponse
from application.interfaces.catalog import Catalog
from application.interfaces.repositories import SessionRepository
from application.services.fitting import curve_inputs, model_curve
from application.services.identification import launch_of
from core.configs.fit import FitSettings
from domain.exceptions import NotFoundError


class GetNeighbourCurvesQuery:
    def __init__(
        self,
        repo: SessionRepository,
        catalog: Catalog,
        settings: FitSettings,
    ) -> None:
        self._repo = repo
        self._catalog = catalog
        self._settings = settings

    async def __call__(
        self, session_uuid: UUID, observation_id: int
    ) -> NeighboursResponse:
        track = await self._repo.get_observation(session_uuid, observation_id)
        if track is None:
            raise NotFoundError(
                f"наблюдения {observation_id} нет в сессии {session_uuid}"
            )

        launch = launch_of(track.meta)
        calibration = curve_inputs(track)
        frequency_hz = track.meta.get("observation_frequency")
        if not launch or calibration is None or frequency_hz is None:
            return NeighboursResponse(launch=launch, curves=[])

        carrier_khz = float(frequency_hz) / 1000.0
        curves = []
        for obj in await self._catalog.objects():
            if obj.launch != launch:
                continue
            curve = model_curve(
                obj.elements,
                carrier_khz,
                calibration,
                self._settings.MODEL_CURVE_POINTS,
            )
            # `None` — SGP4 вернул код ошибки: объект сходит с орбиты.
            # Пропускаем молча: это контекст, а не результат измерения.
            if curve is not None:
                curves.append(
                    NeighbourCurveResponse(
                        norad_id=obj.norad_id,
                        name=obj.name,
                        mjd=curve.mjd,
                        f_offset_hz=curve.f_offset_hz,
                    )
                )

        return NeighboursResponse(launch=launch, curves=curves)
