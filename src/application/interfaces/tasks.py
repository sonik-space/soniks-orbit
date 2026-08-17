"""Постановка извлечения в очередь.

Интерфейс нужен затем, чтобы `application/` не знал про taskiq (правило 8),
и чтобы в тестах очередь подменялась списком.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class ExtractionQueue(Protocol):
    async def enqueue(self, session_uuid: UUID, observation_id: int) -> None: ...
