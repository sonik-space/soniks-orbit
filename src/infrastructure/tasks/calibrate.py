"""Фоновая калибровка водопада наблюдения.

Асинхронно потому, что скачивание PNG — это секунды (architecture.md).
Сама цепочка живёт в `application/services/calibration.py`, здесь только
доставание наблюдения из БД и вызов.

Точки задача не ставит: их ставит человек. Наблюдение приезжает в сессию
с осями и пустым треком.
"""

from logging import getLogger
from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject

from application.interfaces.image_fetcher import WaterfallImages
from application.interfaces.repositories import SessionRepository
from application.interfaces.transaction import Transaction
from application.services.calibration import run_calibration
from core.configs import settings
from infrastructure.tasks.broker import broker

logger = getLogger(settings.logging.TASKIQ_NAME)


@broker.task(task_name="Calibrate waterfall", retry_on_error=True)
@inject(patch_module=True)
async def calibrate_task(
    session_uuid: str,
    observation_id: int,
    repo: FromDishka[SessionRepository],
    images: FromDishka[WaterfallImages],
    transaction: FromDishka[Transaction],
) -> None:
    track = await repo.get_observation(UUID(session_uuid), observation_id)
    if track is None:
        logger.warning(
            "Наблюдения %s нет в сессии %s — задача устарела",
            observation_id,
            session_uuid,
        )
        return

    await repo.save_extraction(track.uuid, status="running")
    await transaction.commit()

    await run_calibration(
        images=images, repo=repo, transaction=transaction, track=track
    )
    logger.info("Калибровка наблюдения %s завершена", observation_id)
