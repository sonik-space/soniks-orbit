from pathlib import Path

from pydantic import BaseModel


class WaterfallSettings(BaseModel):
    """Кеш водопадов.

    Кеш обязателен: файлы неизменяемы, а нагрузка на S3 иначе избыточна
    (decisions/009).
    """

    CACHE_DIR: Path = Path("/var/cache/soniks-orbit/waterfalls")
    TIMEOUT_IN_SECONDS: float = 60.0
