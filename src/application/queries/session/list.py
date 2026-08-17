"""Список сессий вызывающего (api.md)."""

from __future__ import annotations

from application.dtos.session import SessionSummaryResponse
from application.interfaces.repositories import SessionRepository


class ListSessionsQuery:
    def __init__(self, repo: SessionRepository) -> None:
        self._repo = repo

    async def __call__(
        self, owner_sub: str, limit: int
    ) -> list[SessionSummaryResponse]:
        return [
            SessionSummaryResponse(
                uuid=s.uuid,
                name=s.name,
                norad_id=s.norad_id,
                status=s.status,
                n_observations=s.n_observations,
            )
            for s in await self._repo.list_for_owner(owner_sub, limit)
        ]
