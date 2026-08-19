"""Постановка задания идентификации по размеченному наблюдению сессии.

Автомата больше нет: почасовой сканер отбирал наблюдения по тому, нашло ли
там что-нибудь автоизвлечение, а его сняли (decisions/015). Перебор запускает
человек — по тому наблюдению, которое сам и разметил.
"""

from __future__ import annotations

from application.dtos.identification import CreateIdentificationRequest
from application.interfaces.tasks import IdentificationQueue


class CreateIdentificationInteractor:
    def __init__(self, queue: IdentificationQueue) -> None:
        self._queue = queue

    async def __call__(self, request: CreateIdentificationRequest) -> None:
        await self._queue.enqueue(request.session_uuid, request.observation_id)
