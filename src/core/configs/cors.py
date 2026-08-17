from pydantic import BaseModel


class CORSSettings(BaseModel):
    """Фронт живёт в `soniks-frontend` на другом домене (dev2), сервис —
    на своём, поэтому CORS нужен с самого начала (frontend.md)."""

    ALLOW_ORIGINS: list[str] = ["*"]
    ALLOW_CREDENTIALS: bool = True
    ALLOW_METHODS: list[str] = ["*"]
    ALLOW_HEADERS: list[str] = ["*"]
