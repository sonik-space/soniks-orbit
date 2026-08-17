from sqlalchemy.ext.asyncio import AsyncSession

from application.interfaces.transaction import Transaction


class SQLAlchemyTransaction(Transaction):
    """Без карты `UNIQUE_CONSTRAINT_MAP` из `soniks-backend`: там десятки
    ограничений на справочниках, здесь одно — `(session_uuid, observation_id)`,
    и оно обрабатывается там, где возникает."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def flush(self) -> None:
        await self._session.flush()
