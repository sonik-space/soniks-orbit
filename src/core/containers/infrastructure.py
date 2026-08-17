"""Провайдеры dishka для инфраструктуры."""

import logging
import sys
from collections.abc import AsyncIterator
from logging import Logger

import httpx
from dishka import Provider, Scope
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.requests import Request

from application.interfaces.image_fetcher import WaterfallImages
from application.interfaces.network_api import NetworkApi
from application.interfaces.repositories import SessionRepository
from application.interfaces.tasks import ExtractionQueue
from application.interfaces.transaction import Transaction
from core.configs import settings
from core.configs.auth import AuthSettings
from core.configs.database import PostgresSettings, SQLEngineSettings
from core.configs.logging import LoggingSettings
from core.configs.network_api import NetworkApiSettings
from core.configs.waterfall import WaterfallSettings
from infrastructure.auth.keycloak import CurrentUser, MockCurrentUser, PyJWKClientCache
from infrastructure.images.loader import CachedWaterfallImages
from infrastructure.network_api.django import DjangoNetworkApi
from infrastructure.postgres.database import get_engine, get_session, get_sessionmaker
from infrastructure.postgres.repositories.session import SQLAlchemySessionRepository
from infrastructure.postgres.transaction import SQLAlchemyTransaction
from infrastructure.tasks.queue import TaskiqExtractionQueue


def get_logger(logging_settings: LoggingSettings) -> Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(logging_settings.BASE_FORMAT, logging_settings.DATE_FORMAT)
    )
    logger = logging.getLogger(logging_settings.APP_NAME)
    logger.setLevel(logging_settings.APP_LEVEL)
    if not logger.handlers:
        logger.addHandler(handler)
    return logger


async def get_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Один клиент на приложение: пул соединений к боевому API и к S3."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        yield client


def get_network_api(
    client: httpx.AsyncClient, api_settings: NetworkApiSettings
) -> NetworkApi:
    return DjangoNetworkApi(
        client, api_settings.BASE_URL, api_settings.TIMEOUT_IN_SECONDS
    )


def get_waterfall_images(
    client: httpx.AsyncClient, waterfall_settings: WaterfallSettings
) -> WaterfallImages:
    return CachedWaterfallImages(
        client, waterfall_settings.CACHE_DIR, waterfall_settings.TIMEOUT_IN_SECONDS
    )


def db_provider() -> Provider:
    provider = Provider()
    provider.provide(get_engine, provides=AsyncEngine, scope=Scope.APP)
    provider.provide(
        get_sessionmaker, provides=async_sessionmaker[AsyncSession], scope=Scope.APP
    )
    provider.provide(get_session, provides=AsyncSession, scope=Scope.REQUEST)
    return provider


def logger_provider() -> Provider:
    provider = Provider()
    provider.provide(get_logger, provides=Logger, scope=Scope.APP)
    return provider


def gateway_provider() -> Provider:
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(SQLAlchemyTransaction, provides=Transaction)
    provider.provide(SQLAlchemySessionRepository, provides=SessionRepository)
    provider.provide(TaskiqExtractionQueue, provides=ExtractionQueue)
    return provider


def network_provider() -> Provider:
    provider = Provider(scope=Scope.APP)
    provider.provide(get_http_client, provides=httpx.AsyncClient)
    provider.provide(get_network_api, provides=NetworkApi)
    provider.provide(get_waterfall_images, provides=WaterfallImages)
    return provider


def auth_provider() -> Provider:
    provider = Provider(scope=Scope.REQUEST)
    provider.from_context(Request)
    provider.provide(PyJWKClientCache, scope=Scope.APP)
    provider.provide(CurrentUser)

    if settings.app.DISABLE_AUTH:
        # `AppSettings` не даёт включить это вне local и unittest.
        provider.provide(MockCurrentUser, provides=CurrentUser)

    return provider


def settings_provider() -> Provider:
    """Настройки как зависимости: конфигурация читается один раз, а не
    импортируется `settings` по месту использования."""
    provider = Provider(scope=Scope.APP)
    provider.from_context(PostgresSettings)
    provider.from_context(SQLEngineSettings)
    provider.from_context(AuthSettings)
    provider.from_context(LoggingSettings)
    provider.from_context(NetworkApiSettings)
    provider.from_context(WaterfallSettings)
    return provider
