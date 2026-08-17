"""Миксины взяты из `soniks-backend/src/infrastructure/postgres/models/mixins.py`
(data-model.md), чтобы схема совпадала при втягивании сервиса в v2."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        server_default=func.now(),
        server_onupdate=func.now(),
    )


class UUIDMixin:
    uuid: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
