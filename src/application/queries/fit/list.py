"""История прогонов фита сессии (api.md).

Строки компактные: без `residuals` и `per_observation`. Десять прогонов
по 2500 точек — это мегабайты на каждый заход в раздел, а история нужна
для того, чтобы выбрать прогон, а не чтобы его разглядывать.
Полное тело — из `GET /fits/{id}`.
"""

from __future__ import annotations

from uuid import UUID

from application.dtos.fit import FitRunSummaryResponse
from application.interfaces.repositories import FitRunRepository
from application.services.fitting import fit_run_summary


class ListFitRunsQuery:
    def __init__(self, fit_repo: FitRunRepository) -> None:
        self._fit_repo = fit_repo

    async def __call__(self, session_uuid: UUID) -> list[FitRunSummaryResponse]:
        return [
            fit_run_summary(run)
            for run in await self._fit_repo.list_for_session(session_uuid)
        ]
