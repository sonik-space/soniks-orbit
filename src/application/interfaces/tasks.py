"""Постановка извлечения в очередь.

Интерфейс нужен затем, чтобы `application/` не знал про taskiq (правило 8),
и чтобы в тестах очередь подменялась списком.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class ExtractionQueue(Protocol):
    async def enqueue(
        self,
        session_uuid: UUID,
        observation_id: int,
        *,
        snr_threshold: float | None = None,
        bin_seconds: float | None = None,
    ) -> None:
        """`None` означает «взять умолчание из настроек» — те же, при которых
        получен эталон 0.0250 кГц на 1527888."""
        ...
