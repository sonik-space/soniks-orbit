"""Повторное извлечение трека с другими параметрами."""

from __future__ import annotations

from uuid import UUID

from application.dtos.session import ReextractRequest
from application.interfaces.repositories import SessionRepository
from application.interfaces.tasks import ExtractionQueue
from domain.exceptions import NotFoundError


class ReextractInteractor:
    def __init__(self, repo: SessionRepository, queue: ExtractionQueue) -> None:
        self._repo = repo
        self._queue = queue

    async def __call__(
        self, session_uuid: UUID, observation_id: int, request: ReextractRequest
    ) -> None:
        """Ставит задачу заново. В БД ничего не пишет: статус переведёт сам
        воркер, а ручные точки переживут повтор — их сохраняет `run_extraction`.
        """
        if await self._repo.get_observation(session_uuid, observation_id) is None:
            raise NotFoundError(
                f"наблюдения {observation_id} нет в сессии {session_uuid}"
            )

        await self._queue.enqueue(
            session_uuid,
            observation_id,
            snr_threshold=request.snr_threshold,
            bin_seconds=request.bin_seconds,
        )
