from pathlib import Path

from pydantic import BaseModel


class WaterfallSettings(BaseModel):
    """Кеш водопадов и умолчания извлечения.

    Кеш обязателен: файлы неизменяемы, а нагрузка на S3 иначе избыточна
    (decisions/009). Умолчания извлечения — те же, при которых получен
    эталон 0.0250 кГц на 1527888.
    """

    CACHE_DIR: Path = Path("/var/cache/soniks-orbit/waterfalls")
    TIMEOUT_IN_SECONDS: float = 60.0

    SNR_THRESHOLD: float = 4.0
    BIN_SECONDS: float = 1.0
