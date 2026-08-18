import pydantic
from dishka import Provider

from core.configs import Settings
from core.configs.app import AppSettings
from core.configs.auth import AuthSettings
from core.configs.catalog import CatalogSettings
from core.configs.database import PostgresSettings, SQLEngineSettings
from core.configs.fit import FitSettings
from core.configs.logging import LoggingSettings
from core.configs.network_api import NetworkApiSettings
from core.configs.waterfall import WaterfallSettings
from core.containers.application import application_provider
from core.containers.infrastructure import (
    auth_provider,
    db_provider,
    gateway_provider,
    logger_provider,
    network_provider,
    settings_provider,
)

# Провайдера `domain` нет: ядро — чистые функции без состояния (правило 1),
# внедрять там нечего.


def get_providers() -> tuple[Provider, ...]:
    return (
        settings_provider(),
        db_provider(),
        logger_provider(),
        network_provider(),
        gateway_provider(),
        auth_provider(),
        application_provider(),
    )


def dishka_context(
    settings: Settings,
) -> dict[type[pydantic.BaseModel], pydantic.BaseModel]:
    return {
        AppSettings: settings.app,
        PostgresSettings: settings.postgres,
        SQLEngineSettings: settings.sql_engine,
        AuthSettings: settings.auth,
        LoggingSettings: settings.logging,
        NetworkApiSettings: settings.network_api,
        WaterfallSettings: settings.waterfall,
        CatalogSettings: settings.catalog,
        FitSettings: settings.fit,
    }
