"""Прогон фита по идентификатору (api.md)."""

from __future__ import annotations

from uuid import UUID

from application.dtos.fit import FitRunResponse
from application.interfaces.repositories import FitRunRepository
from application.services.fitting import fit_run_response
from domain.exceptions import NotFoundError


class GetFitRunQuery:
    def __init__(self, fit_repo: FitRunRepository) -> None:
        self._fit_repo = fit_repo

    async def __call__(self, fit_run_id: UUID) -> FitRunResponse:
        run = await self._fit_repo.get(fit_run_id)
        if run is None:
            raise NotFoundError(f"прогон фита {fit_run_id} не найден")
        return fit_run_response(run)
