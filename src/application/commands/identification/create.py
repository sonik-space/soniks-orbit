"""Ручная постановка задания идентификации по одному наблюдению.

Кнопка не заменяет автомат: вариант «только по кнопке, без автомата»
отвергнут в decisions/006. Основной путь — почасовой сканер, а этот вызов
ставит ровно ту же задачу в ту же очередь.
"""

from __future__ import annotations

from application.dtos.identification import CreateIdentificationRequest
from application.interfaces.tasks import IdentificationQueue


class CreateIdentificationInteractor:
    def __init__(self, queue: IdentificationQueue) -> None:
        self._queue = queue

    async def __call__(self, request: CreateIdentificationRequest) -> None:
        await self._queue.enqueue(request.observation_id)
