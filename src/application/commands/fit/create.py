"""Прогон фита.

**Синхронный** — 5 наблюдений по 500 точек считаются за миллисекунды, и job id,
опрос состояния и индикаторы прогресса не нужны: асинхронных поверхностей
в сервисе две, а не три (architecture.md).

Здесь заменяется цикл `z→s→f→m→f→r→ctrl+h` из гайда целиком. Шага `m` нет:
несущая своя на каждое наблюдение и решается аналитически (decisions/003).
"""

from __future__ import annotations

from uuid import UUID

from application.dtos.fit import RunFitRequest
from application.interfaces.repositories import FitRunRepository, SessionRepository
from application.interfaces.transaction import Transaction
from application.services.fitting import (
    build_segments,
    dominated_names,
    elements_to_dict,
    prior_sigmas,
    scatter_residuals,
    sigmas_to_dict,
    to_tle,
)
from core.configs.fit import FitSettings
from domain.exceptions import BadRequestError, NotFoundError
from domain.models import FitRun
from domain.od.elements import Elements
from domain.od.fit import fit


class RunFitInteractor:
    def __init__(
        self,
        repo: SessionRepository,
        fit_repo: FitRunRepository,
        transaction: Transaction,
        settings: FitSettings,
    ) -> None:
        self._repo = repo
        self._fit_repo = fit_repo
        self._transaction = transaction
        self._settings = settings

    async def __call__(
        self, session_uuid: UUID, request: RunFitRequest, author_sub: str
    ) -> FitRun:
        session = await self._repo.get(session_uuid)
        if session is None:
            raise NotFoundError(f"сессия {session_uuid} не найдена")

        wanted = request.observation_ids
        tracks = [
            track
            for track in session.observations
            if wanted is None or track.observation_id in wanted
        ]
        segments, used = build_segments(tracks)

        # Защита из algorithms.md §4.4: из одного прохода наблюдаемы примерно
        # две величины, и фит по нему даёт правдоподобный RMS при бессмысленных
        # элементах.
        n_points = sum(len(indices) for indices in used.values())
        if len(segments) < self._settings.MIN_OBSERVATIONS:
            raise BadRequestError(
                f"наблюдений с точками {len(segments)}, "
                f"нужно хотя бы {self._settings.MIN_OBSERVATIONS}"
            )
        if n_points < self._settings.MIN_ENABLED_POINTS:
            raise BadRequestError(
                f"включённых точек {n_points}, "
                f"нужно хотя бы {self._settings.MIN_ENABLED_POINTS}"
            )

        sigmas, sigma_argp_plus_m = prior_sigmas(
            request.prior_sigmas, self._settings, priors_off=request.priors_off
        )
        f_scale = self._settings.F_SCALE if request.f_scale is None else request.f_scale
        free = request.free or "1111111"

        seed = Elements.from_tle(session.seed.tle1, session.seed.tle2)
        result = fit(
            seed,
            segments,
            free=free,
            prior_sigmas=sigmas,
            sigma_argp_plus_m=sigma_argp_plus_m,
            f_scale=f_scale,
            max_nfev=self._settings.MAX_NFEV,
        )

        # `res.success == False` или исчерпание max_nfev — это прогон
        # со статусом `failed`, но с последними элементами и невязками:
        # иначе в UI не видно, что пошло не так (algorithms.md §4.4).
        status = "ok" if result.success else "failed"

        run = await self._fit_repo.create(
            session_uuid=session_uuid,
            author_sub=author_sub,
            config={
                "prior_sigmas": sigmas_to_dict(sigmas, sigma_argp_plus_m),
                "priors_off": request.priors_off,
                # Без маски прогон невоспроизводим и, что важнее, неотличим
                # от полного фита в истории (decisions/013).
                "free": free,
                "f_scale": f_scale,
                "max_nfev": self._settings.MAX_NFEV,
                "observation_ids": sorted(used),
                "n_points": n_points,
                "message": result.message,
                "nfev": result.nfev,
            },
            elements_in=elements_to_dict(seed),
            elements_out=elements_to_dict(result.elements),
            tle=to_tle(result.elements, session.seed),
            epoch_mjd=result.elements.epoch_mjd,
            rms_khz=result.rms_khz,
            rms_pre_khz=result.rms_pre_khz,
            n_points=n_points,
            per_observation=[
                {
                    "observation_id": int(segment.key),
                    "rms_khz": result.per_segment_rms_khz[segment.key],
                    # Ядро считает в кГц, API отдаёт герцы (правило 2).
                    "carrier_hz": result.carriers_khz[segment.key] * 1000.0,
                    "n": int(segment.mjd.size),
                }
                for segment in segments
            ],
            residuals={
                str(observation_id): columns
                for observation_id, columns in scatter_residuals(
                    result, segments, used, tracks
                ).items()
            },
            prior_dominated=dominated_names(result),
            status=status,
        )

        if status == "ok":
            await self._repo.set_status(session_uuid, "fitted")
        await self._transaction.commit()
        return run
