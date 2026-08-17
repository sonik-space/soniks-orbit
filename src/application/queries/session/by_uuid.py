"""Сессия целиком и трек одного наблюдения (api.md)."""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from application.dtos.common import TleSchema
from application.dtos.session import (
    CalibrationResponse,
    ExtractionStatusResponse,
    PointsResponse,
    SessionObservationResponse,
    SessionResponse,
    TrackResponse,
)
from application.interfaces.repositories import FitRunRepository, SessionRepository
from application.services.fitting import (
    curve_inputs,
    latest_fit_response,
    model_curve,
)
from core.configs.fit import FitSettings
from domain.exceptions import NotFoundError
from domain.models import ObservationTrack
from domain.od.elements import Elements

MJD_UNIX_EPOCH = 40587.0


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

    async def __call__(self, session_uuid: UUID, observation_id: int) -> TrackResponse:
        track = await self._repo.get_observation(session_uuid, observation_id)
        if track is None:
            raise NotFoundError(
                f"наблюдения {observation_id} нет в сессии {session_uuid}"
            )

        return TrackResponse(
            calibration=_calibration(track.calibration),
            waterfall_url=track.waterfall_url,
            points=PointsResponse(**(track.points or {})),
            extraction=ExtractionStatusResponse(
                status=track.extraction_status, error=track.extraction_error
            ),
            model=await self._model(session_uuid, track),
        )

    async def _model(self, session_uuid: UUID, track: ObservationTrack):
        """Модельная кривая последнего прогона поверх этого водопада.

        Считается на чтение, а не хранится: элементы и несущая уже лежат
        в прогоне, а сетка — это одна векторная прогонка SGP4, микросекунды.
        Так кривая не может разойтись с `elements_out`.
        """
        calibration = curve_inputs(track)
        if calibration is None:
            return None

        run = await self._fit_repo.latest(session_uuid)
        if run is None:
            return None

        carrier_hz = next(
            (
                block["carrier_hz"]
                for block in run.per_observation
                if block["observation_id"] == track.observation_id
            ),
            None,
        )
        if carrier_hz is None:
            return None

        return model_curve(
            Elements.from_tle(run.tle.tle1, run.tle.tle2),
            carrier_hz / 1000.0,
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


def _calibration(raw: dict | None) -> CalibrationResponse | None:
    """Границы оси времени отдаются в ISO: MJD — внутренний формат ядра,
    наружу время идёт как ISO 8601 UTC (правило 2)."""
    if not raw:
        return None

    t_min = raw["t_bottom_mjd"]
    t_max = t_min + (raw["plot_h"] - 1) * raw["sec_per_px"] / 86400.0
    return CalibrationResponse(
        img_w=raw["img_w"],
        img_h=raw["img_h"],
        plot_left=raw["plot_left"],
        plot_top=raw["plot_top"],
        plot_w=raw["plot_w"],
        plot_h=raw["plot_h"],
        t_min=_iso(t_min),
        t_max=_iso(t_max),
        f_min_hz=raw["f_min_hz"],
        f_max_hz=raw["f_max_hz"],
        center_freq_hz=raw["center_freq_hz"],
        samp_rate=raw["samp_rate_hz"],
        nchan=raw["nchan"],
        bin_hz=raw["bin_hz"],
    )


def _iso(mjd: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(
        (mjd - MJD_UNIX_EPOCH) * 86400.0, tz=dt.UTC
    )
