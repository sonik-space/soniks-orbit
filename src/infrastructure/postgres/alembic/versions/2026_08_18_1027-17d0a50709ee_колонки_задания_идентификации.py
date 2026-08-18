"""колонки задания идентификации

Задание замораживает снимок наблюдения, калибровку, точки и диагностику
извлечения по тому же правилу 10, что и наблюдение сессии: без замороженного
TLE наблюдения RMS кандидата невоспроизводим. Подтверждение переносит эти же
блоки в созданную сессию, поэтому второго скачивания водопада и второго
извлечения не происходит.

`meta` заводится `NOT NULL` без умолчания: таблица создана миграцией
`8ad9a9fb2b40` в фазе 2 и до фазы 6 не писалась ни разу, задания без снимка
не бывает, а умолчание `{}` означало бы задание без наблюдения.

Уникальность по `observation_id` — не украшение: у задач стоит
`retry_on_error=True`, а сканер перебирает окно с перекрытием.

Revision ID: 17d0a50709ee
Revises: 8ad9a9fb2b40
Create Date: 2026-08-18 10:27:09.764912

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "17d0a50709ee"
down_revision: str | Sequence[str] | None = "8ad9a9fb2b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "od_identifications",
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.add_column(
        "od_identifications",
        sa.Column(
            "calibration", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "od_identifications",
        sa.Column("points", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "od_identifications",
        sa.Column(
            "diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "od_identifications", sa.Column("session_uuid", sa.Uuid(), nullable=True)
    )
    op.create_index(
        op.f("ix_od_identifications_stage"),
        "od_identifications",
        ["stage"],
        unique=False,
    )
    op.create_unique_constraint(
        op.f("uq_od_identifications_observation_id"),
        "od_identifications",
        ["observation_id"],
    )
    op.create_foreign_key(
        op.f("fk_od_identifications_session_uuid_od_sessions"),
        "od_identifications",
        "od_sessions",
        ["session_uuid"],
        ["uuid"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_od_identifications_session_uuid_od_sessions"),
        "od_identifications",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("uq_od_identifications_observation_id"),
        "od_identifications",
        type_="unique",
    )
    op.drop_index(op.f("ix_od_identifications_stage"), table_name="od_identifications")
    op.drop_column("od_identifications", "session_uuid")
    op.drop_column("od_identifications", "diagnostics")
    op.drop_column("od_identifications", "points")
    op.drop_column("od_identifications", "calibration")
    op.drop_column("od_identifications", "meta")
