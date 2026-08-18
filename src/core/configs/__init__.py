from pydantic_settings import BaseSettings, SettingsConfigDict

from core.configs.app import AppSettings
from core.configs.auth import AuthSettings
from core.configs.broker import AioPikaBrokerSettings, RabbitSettings
from core.configs.catalog import CatalogSettings
from core.configs.cors import CORSSettings
from core.configs.database import AlembicSettings, PostgresSettings, SQLEngineSettings
from core.configs.fit import FitSettings
from core.configs.logging import LoggingSettings
from core.configs.network_api import NetworkApiSettings
from core.configs.waterfall import WaterfallSettings


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        env_nested_delimiter="__",
        extra="ignore",
    )
    app: AppSettings = AppSettings()
    auth: AuthSettings = AuthSettings()
    postgres: PostgresSettings = PostgresSettings()
    sql_engine: SQLEngineSettings = SQLEngineSettings()
    alembic: AlembicSettings = AlembicSettings()
    rabbit: RabbitSettings = RabbitSettings()
    aio_pika_broker: AioPikaBrokerSettings = AioPikaBrokerSettings()
    logging: LoggingSettings = LoggingSettings()
    cors: CORSSettings = CORSSettings()
    network_api: NetworkApiSettings = NetworkApiSettings()
    waterfall: WaterfallSettings = WaterfallSettings()
    catalog: CatalogSettings = CatalogSettings()
    fit: FitSettings = FitSettings()


settings = Settings()

__all__ = [
    "AioPikaBrokerSettings",
    "AlembicSettings",
    "AppSettings",
    "AuthSettings",
    "CORSSettings",
    "CatalogSettings",
    "FitSettings",
    "LoggingSettings",
    "NetworkApiSettings",
    "PostgresSettings",
    "RabbitSettings",
    "SQLEngineSettings",
    "Settings",
    "WaterfallSettings",
    "settings",
]
