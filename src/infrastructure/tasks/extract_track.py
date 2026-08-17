"""Фоновое извлечение трека.

Асинхронно потому, что скачивание PNG плюс поиск по ~1 млн пикселей — это
секунды (architecture.md). Сама цепочка живёт в
`application/services/extraction.py`, здесь только доставание наблюдения
из БД и вызов.
"""

from logging import getLogger
from uuid import UUID

from dishka.integrations.taskiq import FromDishka, inject

from application.interfaces.image_fetcher import WaterfallImages
from application.interfaces.repositories import SessionRepository
from application.interfaces.transaction import Transaction
from application.services.extraction import run_extraction
from core.configs import settings
from core.configs.waterfall import WaterfallSettings
from infrastructure.tasks.broker import broker

logger = getLogger(settings.logging.TASKIQ_NAME)


@broker.task(task_name="Extract doppler track", retry_on_error=True)
@inject(patch_module=True)
async def extract_track_task(
    session_uuid: str,
    observation_id: int,
    repo: FromDishka[SessionRepository],
    images: FromDishka[WaterfallImages],
    transaction: FromDishka[Transaction],
    waterfall_settings: FromDishka[WaterfallSettings],
    snr_threshold: float | None = None,
    bin_seconds: float | None = None,
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

    await run_extraction(
        images=images,
        repo=repo,
        transaction=transaction,
        track=track,
        snr_threshold=(
            waterfall_settings.SNR_THRESHOLD if snr_threshold is None else snr_threshold
        ),
        bin_seconds=(
            waterfall_settings.BIN_SECONDS if bin_seconds is None else bin_seconds
        ),
    )
    logger.info("Извлечение по наблюдению %s завершено", observation_id)
