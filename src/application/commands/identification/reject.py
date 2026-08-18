"""Отклонение задания человеком.

Отклонённое задание повторный перебор не трогает: решение человека важнее
свежего прогона, иначе сканер возвращал бы в очередь то, что уже разобрали.
"""

from __future__ import annotations

from uuid import UUID

from application.interfaces.repositories import IdentificationRepository
from application.interfaces.transaction import Transaction
from domain.exceptions import ConflictError, NotFoundError


class RejectIdentificationInteractor:
    def __init__(
        self, repo: IdentificationRepository, transaction: Transaction
    ) -> None:
        self._repo = repo
        self._transaction = transaction

    async def __call__(self, identification_uuid: UUID, owner_sub: str) -> None:
        identification = await self._repo.get(identification_uuid)
        if identification is None:
            raise NotFoundError(f"задания {identification_uuid} нет")
        if identification.stage in ("confirmed", "rejected"):
            raise ConflictError(
                f"задание уже {identification.stage}, повторно решать нечего"
            )

        await self._repo.resolve(
            identification_uuid, stage="rejected", norad_id=None, by_sub=owner_sub
        )
        await self._transaction.commit()
