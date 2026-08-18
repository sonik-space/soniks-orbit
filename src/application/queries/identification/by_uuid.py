"""Задание идентификации целиком (api.md)."""

from __future__ import annotations

from uuid import UUID

from application.dtos.identification import IdentificationResponse
from application.interfaces.repositories import IdentificationRepository
from application.services.identification import identification_response
from domain.exceptions import NotFoundError


class GetIdentificationQuery:
    def __init__(self, repo: IdentificationRepository) -> None:
        self._repo = repo

    async def __call__(self, identification_uuid: UUID) -> IdentificationResponse:
        identification = await self._repo.get(identification_uuid)
        if identification is None:
            raise NotFoundError(f"задания {identification_uuid} нет")
        return identification_response(identification)
