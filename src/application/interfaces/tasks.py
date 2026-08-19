"""Постановка фоновых задач в очередь.

Интерфейс нужен затем, чтобы `application/` не знал про taskiq (правило 8),
и чтобы в тестах очередь подменялась списком.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class CalibrationQueue(Protocol):
    async def enqueue(self, session_uuid: UUID, observation_id: int) -> None:
        """Разбор картинки одного наблюдения сессии: рамка, деления, оси.

        Точек задача не ставит — их ставит человек.
        """
        ...


class IdentificationQueue(Protocol):
    async def enqueue(self, session_uuid: UUID, observation_id: int) -> None:
        """Перебор по каталогу для одного размеченного наблюдения сессии.

        Сессия здесь обязательна: перебирать можно только то, что человек
        уже разметил, а разметка живёт в сессии (decisions/015).
        """
        ...
