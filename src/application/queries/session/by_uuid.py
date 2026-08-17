"""Сессия целиком и трек одного наблюдения (api.md)."""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from application.dtos.session import (
    CalibrationResponse,
    ExtractionStatusResponse,
    PointsResponse,
    SessionObservationResponse,
    SessionResponse,
    TleSchema,
    TrackResponse,
)
from application.interfaces.repositories import SessionRepository
from domain.exceptions import NotFoundError
from domain.models import ObservationTrack

MJD_UNIX_EPOCH = 40587.0


class GetSessionQuery:
    def __init__(self, repo: SessionRepository) -> None:
        self._repo = repo

    async def __call__(self, session_uuid: UUID) -> SessionResponse:
        session = await self._repo.get(session_uuid)
        if session is None:
            raise NotFoundError(f"сессия {session_uuid} не найдена")

        return SessionResponse(
            uuid=session.uuid,
            name=session.name,
            norad_id=session.norad_id,
            status=session.status,
            seed_tle=TleSchema(
                tle0=session.seed.tle0, tle1=session.seed.tle1, tle2=session.seed.tle2
            ),
            observations=[_observation(t) for t in session.observations],
        )


class GetTrackQuery:
    def __init__(self, repo: SessionRepository) -> None:
        self._repo = repo

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
