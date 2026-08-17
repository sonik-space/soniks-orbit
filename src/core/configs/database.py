from pydantic import BaseModel


class PostgresSettings(BaseModel):
    DB: str = "soniks_orbit"
    USER: str = "admin"
    PASSWORD: str = "soniks"
    HOST: str = "orbit-postgres"
    PORT: int = 5432

    @property
    def url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.USER}:{self.PASSWORD}"
            f"@{self.HOST}:{self.PORT}/{self.DB}"
        )


class SQLEngineSettings(BaseModel):
    ECHO: bool = False
    ECHO_POOL: bool = False
    POOL_SIZE: int = 10
    MAX_OVERFLOW: int = 20


class AlembicSettings(BaseModel):
    NAMING_CONVENTION: dict[str, str] = {
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
    }
