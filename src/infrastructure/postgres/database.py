from collections.abc import AsyncGenerator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.configs.database import PostgresSettings, SQLEngineSettings


async def get_engine(
    postgres_settings: PostgresSettings,
    sql_settings: SQLEngineSettings,
) -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(
        url=postgres_settings.url,
        echo=sql_settings.ECHO,
        echo_pool=sql_settings.ECHO_POOL,
        pool_size=sql_settings.POOL_SIZE,
        max_overflow=sql_settings.MAX_OVERFLOW,
    )
    yield engine
    await engine.dispose()


async def get_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


async def get_session(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with sessionmaker() as session:
        try:
            yield session
        except SQLAlchemyError:
            await session.rollback()
            raise
