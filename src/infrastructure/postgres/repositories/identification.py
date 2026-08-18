# `from __future__` обязателен: метод `list` затеняет встроенный тип
# внутри тела класса, и `list[int]` в аннотации ниже разобрался бы
# как индексация функции.
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from application.interfaces.repositories import IdentificationRepository
from domain.models import Identification
from infrastructure.postgres.models.orbit import OdIdentificationORM


class SQLAlchemyIdentificationRepository(IdentificationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        observation_id: int,
        stage: str,
        candidates: list[dict[str, Any]],
        meta: dict[str, Any],
        calibration: dict | None,
        points: dict | None,
        diagnostics: dict | None,
    ) -> Identification:
        """Заводит задание или переписывает результат перебора по тому же
        наблюдению.

        Именно upsert, а не `create`: у задач стоит `retry_on_error=True`,
        сканер перебирает окно с перекрытием, а каталог между прогонами
        обновляется. Повтор обязан **обновить** задание, а не завести второе
        и не упасть на уникальном индексе.

        Победитель предварителен: соседние объекты стоят близко, и перебор
        по новому наблюдению может назвать другого. Подтверждённое
        и отклонённое задание повтором не трогается — решение человека
        важнее свежего перебора.
        """
        orm = (
            await self._session.execute(
                select(OdIdentificationORM).where(
                    OdIdentificationORM.observation_id == observation_id
                )
            )
        ).scalar_one_or_none()

        if orm is None:
            orm = OdIdentificationORM(
                observation_id=observation_id,
                stage=stage,
                candidates=candidates,
                meta=meta,
                calibration=calibration,
                points=points,
                diagnostics=diagnostics,
            )
            self._session.add(orm)
            # Нужны uuid и created_at: задание уходит в ответ тем же вызовом.
            await self._session.flush()
            await self._session.refresh(orm)
        elif orm.stage == "screening":
            orm.stage = stage
            orm.candidates = candidates
            orm.meta = meta
            orm.calibration = calibration
            orm.points = points
            orm.diagnostics = diagnostics

        return _to_identification(orm)

    async def get(self, identification_uuid: UUID) -> Identification | None:
        orm = await self._session.get(OdIdentificationORM, identification_uuid)
        return _to_identification(orm) if orm else None

    async def list(self, *, stage: str | None, limit: int) -> list[Identification]:
        query = select(OdIdentificationORM).order_by(
            OdIdentificationORM.created_at.desc()
        )
        if stage is not None:
            query = query.where(OdIdentificationORM.stage == stage)
        rows = (await self._session.execute(query.limit(limit))).scalars()
        return [_to_identification(row) for row in rows]

    async def known_observation_ids(self, observation_ids: list[int]) -> set[int]:
        """Какие из наблюдений уже разбирались.

        Сканеру нужно именно это: гонять извлечение и перебор второй раз
        по тому же наблюдению незачем, а скачивание PNG — самая дорогая
        часть задачи.
        """
        if not observation_ids:
            return set()
        rows = (
            await self._session.execute(
                select(OdIdentificationORM.observation_id).where(
                    OdIdentificationORM.observation_id.in_(observation_ids)
                )
            )
        ).scalars()
        return set(rows)

    async def resolve(
        self,
        identification_uuid: UUID,
        *,
        stage: str,
        norad_id: int | None,
        by_sub: str,
        session_uuid: UUID | None = None,
    ) -> None:
        orm = await self._session.get(OdIdentificationORM, identification_uuid)
        if orm is None:
            return
        orm.stage = stage
        orm.confirmed_norad_id = norad_id
        orm.confirmed_by_sub = by_sub
        orm.session_uuid = session_uuid


def _to_identification(orm: OdIdentificationORM) -> Identification:
    return Identification(
        uuid=orm.uuid,
        created_at=orm.created_at,
        observation_id=orm.observation_id,
        stage=orm.stage,
        candidates=orm.candidates or [],
        meta=orm.meta,
        calibration=orm.calibration,
        points=orm.points,
        diagnostics=orm.diagnostics,
        confirmed_norad_id=orm.confirmed_norad_id,
        confirmed_by_sub=orm.confirmed_by_sub,
        session_uuid=orm.session_uuid,
    )
