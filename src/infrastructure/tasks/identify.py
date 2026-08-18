"""Фоновая идентификация одного наблюдения.

Извлечение здесь работает **без человека** (decisions/006), поэтому качество
автоизвлечения напрямую определяет качество идентификации, а наблюдения,
где извлечение ничего не нашло, в перебор просто не попадают. Это примерно
половина корпуса — замер фазы 1: покрытие 11 из 23.

Цепочка «PNG → калибровка → гребень → доплер» зовётся из
`application/services/extraction.py`, перебор — из
`application/services/identification.py`. Второй копии ни того, ни другого
здесь нет (правило 8): задача только достаёт наблюдение и складывает результат.
"""

from logging import getLogger
from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject

from application.interfaces.catalog import Catalog
from application.interfaces.image_fetcher import WaterfallImages
from application.interfaces.network_api import NetworkApi
from application.interfaces.repositories import IdentificationRepository
from application.interfaces.transaction import Transaction
from application.services.extraction import extract_track
from application.services.identification import is_screenable, screen_track
from core.configs import settings
from domain.models import Identification, ObservationTrack
from domain.waterfall import CalibrationError
from infrastructure.tasks.broker import broker

logger = getLogger(settings.logging.TASKIQ_NAME)

# Сессии у задания нет, а `ObservationTrack` заводился под наблюдение сессии.
# Здесь он нужен только как форма, которую понимают `build_segments`
# и `model_curve`, и его `uuid` никуда не пишется.
_PLACEHOLDER_UUID = UUID(int=0)


@broker.task(task_name="Identify observation", retry_on_error=True)
@inject(patch_module=True)
async def identify_task(
    observation_id: int,
    api: FromDishka[NetworkApi],
    images: FromDishka[WaterfallImages],
    catalog: FromDishka[Catalog],
    repo: FromDishka[IdentificationRepository],
    transaction: FromDishka[Transaction],
) -> None:
    meta = await api.get_observation(observation_id)
    url = meta.get("waterfall")
    if not url:
        logger.info(
            "У наблюдения %s нет водопада — идентифицировать нечего", observation_id
        )
        return

    try:
        rgb, wf_meta = await images.load(observation_id, url)
    except CalibrationError as error:
        # Наблюдение до июля 2026 или станция на клиенте старше 2.2.x:
        # полоса невосстановима. Это ожидаемое состояние, а не поломка,
        # и задания оно не порождает.
        logger.info("Наблюдение %s непригодно: %s", observation_id, error)
        return

    extraction = extract_track(rgb, wf_meta, meta)
    track = ObservationTrack(
        uuid=_PLACEHOLDER_UUID,
        observation_id=observation_id,
        meta=meta,
        extraction_status="ok",
        calibration=extraction.calibration.to_dict()
        if extraction.calibration
        else None,
        points=extraction.points.to_columns(),
        diagnostics=extraction.diagnostics(),
    )

    if not is_screenable(track):
        logger.info(
            "Наблюдение %s в перебор не идёт: точек %d, запас конвенции %s",
            observation_id,
            track.n_points,
            extraction.margin,
        )
        return

    objects = await catalog.objects()
    candidates = screen_track(track, objects)

    identification = await repo.upsert(
        observation_id=observation_id,
        stage="screening",
        candidates=[c.to_dict() for c in candidates],
        meta=meta,
        calibration=track.calibration,
        points=track.points,
        diagnostics=track.diagnostics,
    )
    await transaction.commit()
    _log_result(identification, observation_id)


def _log_result(identification: Identification, observation_id: int) -> None:
    best = identification.candidates[0] if identification.candidates else None
    if best is None:
        logger.info("По наблюдению %s кандидатов не нашлось", observation_id)
        return
    logger.info(
        "Наблюдение %s: лучший кандидат %s (%s), RMS %.4f кГц, кандидатов %d",
        observation_id,
        best["norad_id"],
        best["name"],
        best["rms_khz"],
        len(identification.candidates),
    )
