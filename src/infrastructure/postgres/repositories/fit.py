from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from application.interfaces.repositories import FitRunRepository
from domain.models import FitRun, TleLines
from infrastructure.postgres.models.orbit import OdFitRunORM


class SQLAlchemyFitRunRepository(FitRunRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        session_uuid: UUID,
        author_sub: str,
        config: dict[str, Any],
        elements_in: dict[str, Any],
        elements_out: dict[str, Any],
        tle: TleLines,
        epoch_mjd: float,
        rms_khz: float,
        rms_pre_khz: float,
        n_points: int,
        per_observation: list[dict[str, Any]],
        residuals: dict[str, Any],
        prior_dominated: list[str],
        status: str,
    ) -> FitRun:
        orm = OdFitRunORM(
            session_uuid=session_uuid,
            author_sub=author_sub,
            config=config,
            elements_in=elements_in,
            elements_out=elements_out,
            tle0=tle.tle0,
            tle1=tle.tle1,
            tle2=tle.tle2,
            epoch_mjd=epoch_mjd,
            rms_khz=rms_khz,
            rms_pre_khz=rms_pre_khz,
            n_points=n_points,
            per_observation=per_observation,
            residuals=residuals,
            prior_dominated=prior_dominated,
            status=status,
        )
        self._session.add(orm)
        # Нужны uuid и created_at: прогон уходит в ответ тем же вызовом.
        await self._session.flush()
        await self._session.refresh(orm)
        return _to_run(orm)

    async def get(self, fit_run_id: UUID) -> FitRun | None:
        orm = await self._session.get(OdFitRunORM, fit_run_id)
        return _to_run(orm) if orm else None

    async def list_for_session(self, session_uuid: UUID) -> list[FitRun]:
        rows = (
            await self._session.execute(
                select(OdFitRunORM)
                .where(OdFitRunORM.session_uuid == session_uuid)
                .order_by(OdFitRunORM.created_at.desc())
            )
        ).scalars()
        return [_to_run(row) for row in rows]

    async def latest(self, session_uuid: UUID) -> FitRun | None:
        orm = (
            await self._session.execute(
                select(OdFitRunORM)
                .where(OdFitRunORM.session_uuid == session_uuid)
                .order_by(OdFitRunORM.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return _to_run(orm) if orm else None


def _to_run(orm: OdFitRunORM) -> FitRun:
    return FitRun(
        uuid=orm.uuid,
        session_uuid=orm.session_uuid,
        created_at=orm.created_at,
        author_sub=orm.author_sub,
        config=orm.config,
        elements_in=orm.elements_in,
        elements_out=orm.elements_out,
        tle=TleLines(orm.tle0, orm.tle1, orm.tle2),
        epoch_mjd=orm.epoch_mjd,
        rms_khz=orm.rms_khz,
        rms_pre_khz=orm.rms_pre_khz,
        n_points=orm.n_points,
        per_observation=orm.per_observation,
        residuals=orm.residuals,
        prior_dominated=orm.prior_dominated,
        status=orm.status,
    )
