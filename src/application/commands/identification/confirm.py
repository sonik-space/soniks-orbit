"""Подтверждение кандидата человеком.

Идентификация перетекает в уточнение: подтверждение создаёт сессию с этим
объектом как затравкой (decisions/006).

Затравкой идут **сохранённые в задании** строки кандидата, а не свежие
из каталога. Каталог обновляется каждые 4 часа, человек подтверждает позже,
и затравкой обязана стать та строка, по которой считался показанный ему RMS,
иначе число невоспроизводимо (правило 10).

Наблюдение переезжает в сессию вместе с готовыми калибровкой и точками:
извлечение уже отработало на этапе перебора, и гонять его второй раз значило
бы второй раз скачивать водопад.
"""

from __future__ import annotations

from logging import Logger
from uuid import UUID

from application.dtos.identification import (
    ConfirmIdentificationRequest,
    ConfirmIdentificationResponse,
)
from application.interfaces.repositories import (
    IdentificationRepository,
    SessionRepository,
)
from application.interfaces.transaction import Transaction
from application.services.identification import best_candidate
from domain.exceptions import ConflictError, NotFoundError


class ConfirmIdentificationInteractor:
    def __init__(
        self,
        repo: IdentificationRepository,
        sessions: SessionRepository,
        transaction: Transaction,
        logger: Logger,
    ) -> None:
        self._repo = repo
        self._sessions = sessions
        self._transaction = transaction
        self._logger = logger

    async def __call__(
        self,
        identification_uuid: UUID,
        request: ConfirmIdentificationRequest,
        owner_sub: str,
    ) -> ConfirmIdentificationResponse:
        identification = await self._repo.get(identification_uuid)
        if identification is None:
            raise NotFoundError(f"задания {identification_uuid} нет")
        if identification.stage in ("confirmed", "rejected"):
            raise ConflictError(
                f"задание уже {identification.stage}, повторно решать нечего"
            )

        candidate = best_candidate(identification, request.norad_id)

        session = await self._sessions.create(
            name=f"{candidate['name'] or request.norad_id} по наблюдению "
            f"{identification.observation_id}",
            norad_id=request.norad_id,
            owner_sub=owner_sub,
            seed=(candidate["tle0"], candidate["tle1"], candidate["tle2"]),
            seed_source="identification",
            observations=[(identification.observation_id, identification.meta)],
        )
        # Извлечение в очередь **не ставится**: точки уже посчитаны при
        # переборе, и они переносятся как есть.
        await self._sessions.save_extraction(
            session.observations[0].uuid,
            status="ok",
            calibration=identification.calibration,
            points=identification.points,
            diagnostics=identification.diagnostics,
        )
        await self._repo.resolve(
            identification_uuid,
            stage="confirmed",
            norad_id=request.norad_id,
            by_sub=owner_sub,
            session_uuid=session.uuid,
        )
        await self._transaction.commit()

        self._logger.info(
            "Задание %s подтверждено объектом %s, создана сессия %s",
            identification_uuid,
            request.norad_id,
            session.uuid,
        )
        return ConfirmIdentificationResponse(session_uuid=session.uuid)
