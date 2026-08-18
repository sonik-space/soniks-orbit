"""Список заданий идентификации (api.md)."""

from __future__ import annotations

from application.dtos.identification import IdentificationSummaryResponse
from application.interfaces.repositories import IdentificationRepository
from application.services.identification import identification_summary


class ListIdentificationsQuery:
    def __init__(self, repo: IdentificationRepository) -> None:
        self._repo = repo

    async def __call__(
        self, stage: str | None, limit: int
    ) -> list[IdentificationSummaryResponse]:
        return [
            identification_summary(item)
            for item in await self._repo.list(stage=stage, limit=limit)
        ]
