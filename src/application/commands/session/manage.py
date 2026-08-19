"""Состав сессии: добавить наблюдение, убрать наблюдение, удалить сессию.

Три эндпоинта, обещанные `api.md` с фазы 2 и не написанные до фазы 7. Первый
из них — шаг 2 гайда: «когда наблюдений накопилось несколько, за два-три дня,
объединяем их». В `rffit` это `cat obs1.dat obs2.dat > all.dat`, то есть
набор точек собирается **до** запуска инструмента. У нас сессия живёт дольше
одного захода, и дописывать в неё надо на месте.

Один модуль на три сценария, а не три модуля: у всех троих ровно один
репозиторий, одна транзакция и по десятку строк.
"""

from __future__ import annotations

from logging import Logger
from uuid import UUID

from application.dtos.session import AddObservationsRequest
from application.interfaces.network_api import NetworkApi
from application.interfaces.repositories import SessionRepository
from application.interfaces.tasks import CalibrationQueue
from application.interfaces.transaction import Transaction
from domain.exceptions import ConflictError, NotFoundError
from domain.models import OdSession


class AddObservationsInteractor:
    def __init__(
        self,
        repo: SessionRepository,
        network_api: NetworkApi,
        queue: CalibrationQueue,
        transaction: Transaction,
        logger: Logger,
    ) -> None:
        self._repo = repo
        self._network_api = network_api
        self._queue = queue
        self._transaction = transaction
        self._logger = logger

    async def __call__(
        self, session_uuid: UUID, request: AddObservationsRequest
    ) -> OdSession:
        session = await self._repo.get(session_uuid)
        if session is None:
            raise NotFoundError(f"сессия {session_uuid} не найдена")

        # Снимок ответа API замораживается целиком, как при создании сессии
        # (правило 10): наблюдение, дописанное позже, ничем не отличается
        # от пришедшего сразу.
        snapshots = [
            (oid, await self._network_api.get_observation(oid))
            for oid in dict.fromkeys(request.observation_ids)
        ]
        added = await self._repo.add_observations(session_uuid, snapshots)
        await self._transaction.commit()

        for track in added:
            await self._queue.enqueue(session_uuid, track.observation_id)

        self._logger.info(
            "В сессию %s добавлено наблюдений: %d из %d запрошенных",
            session_uuid,
            len(added),
            len(snapshots),
        )
        session = await self._repo.get(session_uuid)
        assert session is not None, "сессия исчезла между записью и чтением"
        return session


class RemoveObservationInteractor:
    def __init__(self, repo: SessionRepository, transaction: Transaction) -> None:
        self._repo = repo
        self._transaction = transaction

    async def __call__(self, session_uuid: UUID, observation_id: int) -> None:
        session = await self._repo.get(session_uuid)
        if session is None:
            raise NotFoundError(f"сессия {session_uuid} не найдена")

        # Последнее наблюдение убрать нельзя: сессия без наблюдений — это
        # не черновик, а мусор, у которого нет ни затравки по данным,
        # ни возможности что-либо посчитать.
        if len(session.observations) <= 1:
            raise ConflictError(
                "в сессии останется ноль наблюдений: удалите сессию целиком"
            )

        if not await self._repo.remove_observation(session_uuid, observation_id):
            raise NotFoundError(
                f"наблюдения {observation_id} в сессии {session_uuid} нет"
            )
        await self._transaction.commit()


class DeleteSessionInteractor:
    def __init__(
        self, repo: SessionRepository, transaction: Transaction, logger: Logger
    ) -> None:
        self._repo = repo
        self._transaction = transaction
        self._logger = logger

    async def __call__(self, session_uuid: UUID) -> None:
        """Опубликованная сессия не удаляется.

        Строки TLE уже в каталоге и уже ведут наведение сети, а `Tle.url`
        в монолите указывает сюда — это **единственный** признак происхождения
        на стороне Django (integration.md). Удалить сессию значит оставить
        в боевом каталоге запись со ссылкой в никуда.
        """
        session = await self._repo.get(session_uuid)
        if session is None:
            raise NotFoundError(f"сессия {session_uuid} не найдена")
        if session.status == "published":
            raise ConflictError(
                "сессия опубликована: на неё ссылается запись в каталоге СОНИКС"
            )

        await self._repo.delete(session_uuid)
        await self._transaction.commit()
        self._logger.info("Удалена сессия %s", session_uuid)
