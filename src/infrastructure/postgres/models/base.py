from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from core.configs import settings


class BaseORM(DeclarativeBase):
    __abstract__ = True

    metadata = MetaData(naming_convention=settings.alembic.NAMING_CONVENTION)
