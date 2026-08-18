"""Перенос эпохи прогона фита. Заменяет `sattools/propagate`.

Здесь только оркестрация: сам перенос — `domain/od/reepoch.py`, выбор
момента и сборка строк — `services/publishing.py`. В алгоритм лезть не надо,
он написан и покрыт тестами (algorithms.md §5).

Ничего не сохраняется: это предпросмотр. Записывает в каталог `publish.py`.
"""

from __future__ import annotations

from uuid import UUID

from application.dtos.common import TleSchema
from application.dtos.publish import EpochRequest, ReepochResponse
from application.interfaces.repositories import FitRunRepository, SessionRepository
from application.services.fitting import iso_from_mjd
from application.services.publishing import reepoch_run
from domain.exceptions import NotFoundError


class ReepochInteractor:
    def __init__(self, repo: SessionRepository, fit_repo: FitRunRepository) -> None:
        self._repo = repo
        self._fit_repo = fit_repo

    async def __call__(
        self, fit_run_id: UUID, request: EpochRequest
    ) -> ReepochResponse:
        run = await self._fit_repo.get(fit_run_id)
        if run is None:
            raise NotFoundError(f"прогон фита {fit_run_id} не найден")

        session = await self._repo.get(run.session_uuid)
        if session is None:
            raise NotFoundError(f"сессия {run.session_uuid} не найдена")

        epoch_mjd, lines = reepoch_run(run, session, request)
        return ReepochResponse(
            epoch=iso_from_mjd(epoch_mjd),
            tle=TleSchema(tle0=lines.tle0, tle1=lines.tle1, tle2=lines.tle2),
        )
