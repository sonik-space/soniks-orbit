"""Четыре таблицы сервиса (data-model.md).

Сервис **не дублирует** справочники СОНИКС — спутники, станции, транспондеры
берутся из сети по требованию. Здесь только то, чего в СОНИКС нет: рабочие
сессии, размеченные точки, прогоны фита и задания идентификации.

Все четыре заводятся одной миграцией, хотя фазе 2 нужны первые две:
`od_fit_runs` и `od_identifications` описаны в data-model.md полностью,
и дробить схему по фазам значило бы переписывать её трижды.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.postgres.models.base import BaseORM
from infrastructure.postgres.models.mixins import TimestampMixin, UUIDMixin


class OdSessionORM(UUIDMixin, TimestampMixin, BaseORM):
    """Рабочая сессия: один спутник и набор наблюдений, по которым идёт уточнение."""

    __tablename__ = "od_sessions"

    name: Mapped[str]
    norad_id: Mapped[int | None]  # null, пока объект не идентифицирован
    owner_sub: Mapped[str]  # `sub` из Keycloak JWT

    seed_tle0: Mapped[str]
    seed_tle1: Mapped[str]
    seed_tle2: Mapped[str]
    seed_source: Mapped[str]  # observation / manual / identification

    status: Mapped[str] = mapped_column(
        default="draft"
    )  # draft/fitted/published/archived


class OdSessionObservationORM(UUIDMixin, TimestampMixin, BaseORM):
    __tablename__ = "od_session_observations"
    __table_args__ = (UniqueConstraint("session_uuid", "observation_id"),)

    session_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("od_sessions.uuid", ondelete="CASCADE")
    )
    observation_id: Mapped[int]

    # Замороженный ответ Django API целиком, включая TLE, по которому снималась
    # доплер-коррекция (правило 10). TLE в каталоге обновляется каждые 4 часа;
    # без снимка пересчёт по новому TLE изменил бы смысл уже посчитанных
    # `f_abs_hz`, и опубликованное TLE стало бы невоспроизводимым.
    meta: Mapped[dict] = mapped_column(JSONB)

    calibration: Mapped[dict | None] = mapped_column(JSONB)

    extraction_status: Mapped[str] = mapped_column(default="pending")
    extraction_error: Mapped[str | None]

    # Диагностика извлечения: RMS относительно TLE наблюдения, несущая,
    # выигравшая конвенция оси и запас до следующей. Фита здесь нет,
    # профилируется только несущая, поэтому число целиком характеризует
    # качество извлечения — и запас порядка единицы означает ненадёжный трек.
    diagnostics: Mapped[dict | None] = mapped_column(JSONB)

    # ponytail: точки лежат блоком в JSONB, а не таблицей od_track_points.
    #           Потолок: SQL по отдельным точкам невозможен.
    #           Они всегда читаются и пишутся целиком, отдельная таблица дала бы
    #           сотни тысяч строк без единого сценария независимого запроса.
    #           Разносить, если понадобится поточечная аналитика.
    points: Mapped[dict | None] = mapped_column(JSONB)


class OdFitRunORM(UUIDMixin, TimestampMixin, BaseORM):
    """Прогон фита целиком: без него опубликованное TLE невоспроизводимо."""

    __tablename__ = "od_fit_runs"

    session_uuid: Mapped[UUID] = mapped_column(
        ForeignKey("od_sessions.uuid", ondelete="CASCADE")
    )
    author_sub: Mapped[str]

    # Приорные σ, f_scale, участвовавшие наблюдения, число точек.
    config: Mapped[dict] = mapped_column(JSONB)
    elements_in: Mapped[dict] = mapped_column(JSONB)
    elements_out: Mapped[dict] = mapped_column(JSONB)

    tle0: Mapped[str]
    tle1: Mapped[str]
    tle2: Mapped[str]
    epoch_mjd: Mapped[float]

    rms_khz: Mapped[float]
    rms_pre_khz: Mapped[float]
    n_points: Mapped[int]

    per_observation: Mapped[dict] = mapped_column(JSONB)
    residuals: Mapped[dict] = mapped_column(JSONB)  # индексы совпадают с `points`
    prior_dominated: Mapped[dict] = mapped_column(JSONB)

    status: Mapped[str] = mapped_column(default="ok")

    published_at: Mapped[datetime | None]
    published_mode: Mapped[str | None]  # publish / propose
    published_tle_id: Mapped[int | None]  # id, вернувшийся из Django


class OdIdentificationORM(UUIDMixin, TimestampMixin, BaseORM):
    """Задание идентификации: одно наблюдение и ранжированные кандидаты.

    Уникальность по `observation_id` не украшение: у задач стоит
    `retry_on_error=True`, а сканер перебирает окно с перекрытием, поэтому
    без неё повтор задачи завёл бы второе задание на то же наблюдение.
    """

    __tablename__ = "od_identifications"
    __table_args__ = (UniqueConstraint("observation_id"),)

    observation_id: Mapped[int]
    stage: Mapped[str] = mapped_column(default="screening", index=True)

    # ponytail: кандидаты лежат блоком в JSONB, а не таблицей od_candidates.
    #           Потолок: SQL по отдельному кандидату невозможен.
    #           Они всегда пишутся и читаются целиком, а список ограничен
    #           объёмом каталога и живёт до подтверждения.
    #           Разносить, если понадобится аналитика по кандидатам.
    candidates: Mapped[dict] = mapped_column(JSONB)
    confirmed_norad_id: Mapped[int | None]
    confirmed_by_sub: Mapped[str | None]

    # Тот же замороженный снимок и та же форма точек, что у наблюдения сессии
    # (правило 10). Сессии у задания нет: она появляется только при
    # подтверждении и получает эти же точки, без повторного извлечения.
    meta: Mapped[dict] = mapped_column(JSONB)
    calibration: Mapped[dict | None] = mapped_column(JSONB)
    points: Mapped[dict | None] = mapped_column(JSONB)
    diagnostics: Mapped[dict | None] = mapped_column(JSONB)

    session_uuid: Mapped[UUID | None] = mapped_column(
        ForeignKey("od_sessions.uuid", ondelete="SET NULL")
    )
