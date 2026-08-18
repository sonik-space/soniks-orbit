from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from application.interfaces.repositories import SessionRepository
from domain.models import ObservationTrack, OdSession, SessionSummary, TleLines
from infrastructure.postgres.models.orbit import (
    OdFitRunORM,
    OdSessionObservationORM,
    OdSessionORM,
)


class SQLAlchemySessionRepository(SessionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        name: str,
        norad_id: int | None,
        owner_sub: str,
        seed: tuple[str, str, str],
        seed_source: str,
        observations: list[tuple[int, dict[str, Any]]],
    ) -> OdSession:
        orm = OdSessionORM(
            name=name,
            norad_id=norad_id,
            owner_sub=owner_sub,
            seed_tle0=seed[0],
            seed_tle1=seed[1],
            seed_tle2=seed[2],
            seed_source=seed_source,
        )
        self._session.add(orm)
        await self._session.flush()  # нужен uuid сессии для внешнего ключа

        rows = [
            OdSessionObservationORM(
                session_uuid=orm.uuid, observation_id=oid, meta=meta
            )
            for oid, meta in observations
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return _to_session(orm, rows)

    async def get(self, session_uuid: UUID) -> OdSession | None:
        orm = await self._session.get(OdSessionORM, session_uuid)
        if orm is None:
            return None
        rows = (
            await self._session.execute(
                select(OdSessionObservationORM)
                .where(OdSessionObservationORM.session_uuid == session_uuid)
                .order_by(OdSessionObservationORM.observation_id)
            )
        ).scalars()
        return _to_session(orm, list(rows))

    async def list_for_owner(self, owner_sub: str, limit: int) -> list[SessionSummary]:
        n_observations = (
            select(func.count())
            .select_from(OdSessionObservationORM)
            .where(OdSessionObservationORM.session_uuid == OdSessionORM.uuid)
            .scalar_subquery()
        )
        # RMS последнего прогона любого статуса: до фита у сессии нет числа,
        # которое описывало бы её целиком (api.md).
        latest_rms = (
            select(OdFitRunORM.rms_khz)
            .where(OdFitRunORM.session_uuid == OdSessionORM.uuid)
            .order_by(OdFitRunORM.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        rows = await self._session.execute(
            select(
                OdSessionORM.uuid,
                OdSessionORM.name,
                OdSessionORM.norad_id,
                OdSessionORM.status,
                n_observations,
                latest_rms,
            )
            .where(OdSessionORM.owner_sub == owner_sub)
            .order_by(OdSessionORM.created_at.desc())
            .limit(limit)
        )
        return [SessionSummary(*row) for row in rows]

    async def get_observation(
        self, session_uuid: UUID, observation_id: int
    ) -> ObservationTrack | None:
        row = (
            await self._session.execute(
                select(OdSessionObservationORM).where(
                    OdSessionObservationORM.session_uuid == session_uuid,
                    OdSessionObservationORM.observation_id == observation_id,
                )
            )
        ).scalar_one_or_none()
        return _to_track(row) if row else None

    async def save_extraction(
        self,
        observation_uuid: UUID,
        *,
        status: str,
        error: str | None = None,
        calibration: dict | None = None,
        points: dict | None = None,
        diagnostics: dict | None = None,
    ) -> None:
        """Правка трека — один UPDATE целого блока, поэтому она атомарна."""
        row = await self._session.get(OdSessionObservationORM, observation_uuid)
        if row is None:
            return
        row.extraction_status = status
        row.extraction_error = error
        row.calibration = calibration
        row.points = points
        row.diagnostics = diagnostics

    async def save_points(
        self, observation_uuid: UUID, *, points: dict, diagnostics: dict
    ) -> None:
        row = await self._session.get(OdSessionObservationORM, observation_uuid)
        if row is None:
            return
        # Присваивается новый словарь, а не правится старый: JSONB без
        # `MutableDict` изменение на месте не заметит и молча не сохранит.
        row.points = points
        row.diagnostics = diagnostics

    async def set_status(self, session_uuid: UUID, status: str) -> None:
        row = await self._session.get(OdSessionORM, session_uuid)
        if row is not None:
            row.status = status

    async def delete(self, session_uuid: UUID) -> bool:
        """Наблюдения и прогоны уходят каскадом (`ondelete="CASCADE"` в схеме),
        задания идентификации — обнулением ссылки (`SET NULL`): задание пережило
        сессию, которую из него завели, и терять его нельзя."""
        row = await self._session.get(OdSessionORM, session_uuid)
        if row is None:
            return False
        await self._session.delete(row)
        return True

    async def add_observations(
        self, session_uuid: UUID, observations: list[tuple[int, dict[str, Any]]]
    ) -> list[ObservationTrack]:
        existing = set(
            (
                await self._session.execute(
                    select(OdSessionObservationORM.observation_id).where(
                        OdSessionObservationORM.session_uuid == session_uuid
                    )
                )
            ).scalars()
        )
        rows = [
            OdSessionObservationORM(
                session_uuid=session_uuid, observation_id=oid, meta=meta
            )
            for oid, meta in observations
            if oid not in existing
        ]
        if not rows:
            return []
        self._session.add_all(rows)
        await self._session.flush()
        return [_to_track(row) for row in rows]

    async def remove_observation(
        self, session_uuid: UUID, observation_id: int
    ) -> bool:
        row = (
            await self._session.execute(
                select(OdSessionObservationORM).where(
                    OdSessionObservationORM.session_uuid == session_uuid,
                    OdSessionObservationORM.observation_id == observation_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        await self._session.delete(row)
        return True

    async def set_seed(
        self, session_uuid: UUID, *, seed: TleLines, seed_source: str
    ) -> None:
        row = await self._session.get(OdSessionORM, session_uuid)
        if row is None:
            return
        row.seed_tle0 = seed.tle0
        row.seed_tle1 = seed.tle1
        row.seed_tle2 = seed.tle2
        row.seed_source = seed_source


def _to_track(orm: OdSessionObservationORM) -> ObservationTrack:
    return ObservationTrack(
        uuid=orm.uuid,
        observation_id=orm.observation_id,
        meta=orm.meta,
        extraction_status=orm.extraction_status,
        extraction_error=orm.extraction_error,
        calibration=orm.calibration,
        points=orm.points,
        diagnostics=orm.diagnostics,
    )


def _to_session(
    orm: OdSessionORM, observations: list[OdSessionObservationORM]
) -> OdSession:
    return OdSession(
        uuid=orm.uuid,
        name=orm.name,
        norad_id=orm.norad_id,
        owner_sub=orm.owner_sub,
        seed=TleLines(orm.seed_tle0, orm.seed_tle1, orm.seed_tle2),
        seed_source=orm.seed_source,
        status=orm.status,
        observations=[_to_track(o) for o in observations],
    )
