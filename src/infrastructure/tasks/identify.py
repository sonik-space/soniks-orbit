"""Фоновый перебор каталога по размеченному наблюдению сессии.

Перебирать можно только то, что человек уже разметил: автоизвлечения больше
нет, и признака «здесь есть сигнал» без человека тоже нет (decisions/015).
Поэтому задача не трогает картинку вовсе — трек с точками, калибровкой
и диагностикой уже лежит в сессии, и перебор идёт по нему.

Сам перебор живёт в `application/services/identification.py`, второй его копии
здесь нет (правило 8): задача только достаёт трек и складывает результат.
"""

from logging import getLogger
from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject

from application.interfaces.catalog import Catalog
from application.interfaces.repositories import (
    IdentificationRepository,
    SessionRepository,
)
from application.interfaces.transaction import Transaction
from application.services.identification import is_screenable, screen_track
from core.configs import settings
from domain.models import Identification
from infrastructure.tasks.broker import broker

logger = getLogger(settings.logging.TASKIQ_NAME)


@broker.task(task_name="Identify observation", retry_on_error=True)
@inject(patch_module=True)
async def identify_task(
    session_uuid: str,
    observation_id: int,
    sessions: FromDishka[SessionRepository],
    catalog: FromDishka[Catalog],
    repo: FromDishka[IdentificationRepository],
    transaction: FromDishka[Transaction],
) -> None:
    track = await sessions.get_observation(UUID(session_uuid), observation_id)
    if track is None:
        logger.warning(
            "Наблюдения %s нет в сессии %s — задача устарела",
            observation_id,
            session_uuid,
        )
        return

    if not is_screenable(track):
        logger.info(
            "Наблюдение %s в перебор не идёт: точек %d, запас конвенции %s",
            observation_id,
            track.n_points,
            (track.diagnostics or {}).get("margin"),
        )
        return

    objects = await catalog.objects()
    candidates = screen_track(track, objects)

    identification = await repo.upsert(
        observation_id=observation_id,
        stage="screening",
        candidates=[c.to_dict() for c in candidates],
        meta=track.meta,
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
        best.get("norad_id"),
        best.get("name"),
        best.get("rms_khz", 0.0),
        len(identification.candidates),
    )
