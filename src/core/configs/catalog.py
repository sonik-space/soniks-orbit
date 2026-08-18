from pathlib import Path

from pydantic import BaseModel


class CatalogSettings(BaseModel):
    """Кеш активного каталога для идентификации.

    Каталог **не таблица** (data-model.md): справочники сети сервис
    не дублирует. В отличие от кеша водопадов, где файлы неизменяемы и хватает
    проверки существования, каталог меняется — TLE в сети обновляется каждые
    4 часа, — поэтому у кеша есть срок годности.

    Час выбран так, чтобы обращения к единственному троттлируемому эндпоинту
    сети (`/api/latesttles/`, 60/мин на IP) шли на два порядка реже лимита.
    """

    CACHE_DIR: Path = Path("/var/cache/soniks-orbit/catalog")
    TTL_IN_SECONDS: float = 3600.0
    TIMEOUT_IN_SECONDS: float = 120.0
