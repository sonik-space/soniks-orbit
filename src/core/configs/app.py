from enum import StrEnum

from pydantic import BaseModel, model_validator


class Environment(StrEnum):
    DEV = "dev"
    PROD = "prod"
    LOCAL = "local"
    UNITTEST = "unittest"

    @property
    def is_local_environment(self) -> bool:
        return self in {Environment.LOCAL, Environment.UNITTEST}


class AppSettings(BaseModel):
    DEBUG: bool = False
    ENVIRONMENT: Environment = Environment.LOCAL
    APP_NAME: str = "soniks-orbit"

    DISABLE_AUTH: bool = False

    API_VERSION: str = "v1"

    # Адрес раздела для ссылки на прогон фита, которая уходит в каталог
    # вместе с опубликованным TLE. В каталоге источник записи неотличим
    # от ручной, и эта ссылка — единственный провенанс на той стороне.
    UI_BASE_URL: str = "https://dev2.sonik.space"

    @property
    def docs_url(self) -> str:
        return f"/api/{self.API_VERSION}/docs"

    @property
    def redoc_url(self) -> str:
        return f"/api/{self.API_VERSION}/redoc"

    @property
    def openapi_url(self) -> str:
        # Из этой схемы генерируется клиент фронтенда (frontend.md).
        return f"/api/{self.API_VERSION}/openapi.json"

    @model_validator(mode="after")
    def validate_disable_auth(self) -> "AppSettings":
        if self.DISABLE_AUTH and not self.ENVIRONMENT.is_local_environment:
            raise ValueError(
                f"DISABLE_AUTH=True недопустим в '{self.ENVIRONMENT}' окружении"
            )
        return self
