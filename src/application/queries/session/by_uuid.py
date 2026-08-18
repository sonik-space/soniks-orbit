"""Сессия целиком и трек одного наблюдения (api.md)."""

from __future__ import annotations

from uuid import UUID

from application.dtos.common import TleSchema
from application.dtos.session import (
    ExtractionStatusResponse,
    PointsResponse,
    SessionObservationResponse,
    SessionResponse,
    TrackResponse,
)
from application.interfaces.repositories import FitRunRepository, SessionRepository
from application.services.fitting import (
    calibration_schema,
    carrier_khz_for,
    curve_inputs,
    latest_fit_response,
    model_curve,
)
from core.configs.fit import FitSettings
from domain.exceptions import NotFoundError
from domain.models import ObservationTrack
from domain.od.elements import Elements


class GetSessionQuery:
    def __init__(self, repo: SessionRepository, fit_repo: FitRunRepository) -> None:
        self._repo = repo
        self._fit_repo = fit_repo

    async def __call__(self, session_uuid: UUID) -> SessionResponse:
        session = await self._repo.get(session_uuid)
        if session is None:
            raise NotFoundError(f"сессия {session_uuid} не найдена")

        latest = await self._fit_repo.latest(session_uuid)
        return SessionResponse(
            uuid=session.uuid,
            name=session.name,
            norad_id=session.norad_id,
            status=session.status,
            seed_tle=TleSchema(
                tle0=session.seed.tle0, tle1=session.seed.tle1, tle2=session.seed.tle2
            ),
            observations=[_observation(t) for t in session.observations],
            latest_fit=None if latest is None else latest_fit_response(latest),
        )


class GetTrackQuery:
    def __init__(
        self,
        repo: SessionRepository,
        fit_repo: FitRunRepository,
        settings: FitSettings,
    ) -> None:
        self._repo = repo
        self._fit_repo = fit_repo
        self._settings = settings

    async def __call__(
        self,
        session_uuid: UUID,
        observation_id: int,
        fit_uuid: UUID | None = None,
    ) -> TrackResponse:
        track = await self._repo.get_observation(session_uuid, observation_id)
        if track is None:
            raise NotFoundError(
                f"наблюдения {observation_id} нет в сессии {session_uuid}"
            )

        return TrackResponse(
            calibration=calibration_schema(track.calibration),
            waterfall_url=track.waterfall_url,
            points=PointsResponse(**(track.points or {})),
            extraction=ExtractionStatusResponse(
                status=track.extraction_status, error=track.extraction_error
            ),
            model=await self._model(session_uuid, track, fit_uuid),
        )

    async def _model(
        self, session_uuid: UUID, track: ObservationTrack, fit_uuid: UUID | None
    ):
        """Модельная кривая прогона поверх этого водопада.

        Считается на чтение, а не хранится: элементы и несущая уже лежат
        в прогоне, а сетка — это одна векторная прогонка SGP4, микросекунды.
        Так кривая не может разойтись с `elements_out`.

        Прогон — последний либо названный явно (`?fit=`): шаг 5 гайда сверяет
        наблюдение с конкретным опубликованным TLE, а не с тем, что оказалось
        последним к моменту запроса.
        """
        calibration = curve_inputs(track)
        if calibration is None:
            return None

        if fit_uuid is None:
            run = await self._fit_repo.latest(session_uuid)
        else:
            run = await self._fit_repo.get(fit_uuid)
            if run is None or run.session_uuid != session_uuid:
                raise NotFoundError(f"прогона {fit_uuid} нет в сессии {session_uuid}")
        if run is None:
            return None

        carrier_khz = carrier_khz_for(run, track)
        if carrier_khz is None:
            return None

        return model_curve(
            Elements.from_tle(run.tle.tle1, run.tle.tle2),
            carrier_khz,
            calibration,
            self._settings.MODEL_CURVE_POINTS,
        )


def _observation(track: ObservationTrack) -> SessionObservationResponse:
    meta, diag = track.meta, track.diagnostics or {}
    return SessionObservationResponse(
        observation_id=track.observation_id,
        start=meta.get("start"),
        end=meta.get("end"),
        station_name=meta.get("station_name"),
        ground_station=meta.get("ground_station"),
        waterfall_url=track.waterfall_url,
        max_altitude=meta.get("max_altitude"),
        extraction_status=track.extraction_status,
        extraction_error=track.extraction_error,
        n_points=track.n_points,
        rms_khz=diag.get("rms_khz"),
        carrier_hz=diag.get("carrier_hz"),
        convention_margin=diag.get("margin"),
        observation_frequency_hz=meta.get("observation_frequency"),
    )
