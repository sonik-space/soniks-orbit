"""Создание сессии уточнения."""

from __future__ import annotations

from logging import Logger

from application.dtos.session import CreateSessionRequest
from application.interfaces.network_api import NetworkApi
from application.interfaces.repositories import SessionRepository
from application.interfaces.tasks import ExtractionQueue
from application.interfaces.transaction import Transaction
from domain.exceptions import BadRequestError
from domain.models import OdSession


class CreateSessionInteractor:
    def __init__(
        self,
        repo: SessionRepository,
        network_api: NetworkApi,
        queue: ExtractionQueue,
        transaction: Transaction,
        logger: Logger,
    ) -> None:
        self._repo = repo
        self._network_api = network_api
        self._queue = queue
        self._transaction = transaction
        self._logger = logger

    async def __call__(
        self, request: CreateSessionRequest, owner_sub: str
    ) -> OdSession:
        snapshots = [
            (oid, await self._network_api.get_observation(oid))
            for oid in dict.fromkeys(request.observation_ids)
        ]

        seed, seed_source = self._seed(request, snapshots)
        session = await self._repo.create(
            name=request.name,
            norad_id=request.norad_id or _norad_of(snapshots),
            owner_sub=owner_sub,
            seed=seed,
            seed_source=seed_source,
            observations=snapshots,
        )
        await self._transaction.commit()

        # Извлечение ставится в очередь сразу: скачивание PNG плюс поиск
        # по ~1 млн пикселей — это секунды (architecture.md).
        for track in session.observations:
            await self._queue.enqueue(session.uuid, track.observation_id)

        self._logger.info(
            "Создана сессия %s, наблюдений %d", session.uuid, len(session.observations)
        )
        return session

    @staticmethod
    def _seed(
        request: CreateSessionRequest, snapshots: list[tuple[int, dict]]
    ) -> tuple[tuple[str, str, str], str]:
        """Затравка: явная из запроса либо TLE первого наблюдения.

        TLE берётся из `obs["tle"]` в JSON API — **не** выскребается регуляркой
        со страницы наблюдения, как делали оба старых инструмента (правило 4).
        """
        if request.seed is not None:
            return (request.seed.tle0, request.seed.tle1, request.seed.tle2), "manual"

        tle = snapshots[0][1].get("tle") or {}
        if not tle.get("tle1") or not tle.get("tle2"):
            raise BadRequestError(
                f"у наблюдения {snapshots[0][0]} нет TLE, затравку нужно передать явно"
            )
        return (tle.get("tle0", ""), tle["tle1"], tle["tle2"]), "observation"


def _norad_of(snapshots: list[tuple[int, dict]]) -> int | None:
    return snapshots[0][1].get("norad_cat_id")
