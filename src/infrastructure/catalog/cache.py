"""Кеш активного каталога сети.

Каталог берётся одним запросом `GET /api/latesttles/` и живёт файлом на диске
плюс разобранным списком в памяти. Таблицы под него нет и не будет
(data-model.md, «Что не хранится»): это справочник сети, а не наши данные.

Отличие от кеша водопадов существенно и намеренно. Водопад неизменяем,
поэтому `CachedWaterfallImages` проверяет только существование файла.
Каталог изменяем — TLE в сети обновляется каждые 4 часа, — поэтому здесь
есть срок годности, и он же держит обращения к единственному троттлируемому
эндпоинту сети далеко от лимита 60/мин.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from application.interfaces.catalog import Catalog
from application.interfaces.network_api import NetworkApi
from domain.models import CatalogObject, TleLines
from domain.od.elements import Elements

CATALOG_FILE = "latest_tles.json"


class CachedCatalog(Catalog):
    def __init__(
        self,
        api: NetworkApi,
        cache_dir: Path,
        ttl_seconds: float,
    ) -> None:
        self._api = api
        self._path = cache_dir / CATALOG_FILE
        self._ttl = ttl_seconds
        self._parsed: list[CatalogObject] | None = None
        self._parsed_at = 0.0
        self._lock = asyncio.Lock()

    async def objects(self) -> list[CatalogObject]:
        # Разбор 2901 строки TLE стоит заметно дороже чтения файла, а перебор
        # идёт на каждое наблюдение, поэтому разобранный список держится
        # в памяти на всё приложение.
        if self._parsed is not None and self._fresh(self._parsed_at):
            return self._parsed

        async with self._lock:
            if self._parsed is not None and self._fresh(self._parsed_at):
                return self._parsed
            self._parsed = _parse(await self._raw())
            self._parsed_at = time.time()
            return self._parsed

    async def _raw(self) -> list[dict[str, Any]]:
        if self._path.exists() and self._fresh(self._path.stat().st_mtime):
            return json.loads(self._path.read_text(encoding="utf-8"))

        records = await self._api.list_catalog()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        return records

    def _fresh(self, stamp: float) -> bool:
        return time.time() - stamp < self._ttl


def _parse(records: list[dict[str, Any]]) -> list[CatalogObject]:
    """Записи `/api/latesttles/` в объекты каталога.

    Нечитаемая строка — не повод уронить перебор: в каталоге сети попадаются
    наборы, которые `Satrec.twoline2rv` не принимает, и их место просто
    среди тех кандидатов, которых нет. Замер: из 2901 записи не разобралась
    ни одна, но полагаться на это нельзя.
    """
    objects = []
    for record in records:
        satellite = record.get("satellite") or {}
        latest = record.get("latest") or {}
        norad_id = satellite.get("norad_cat_id")
        line1, line2 = latest.get("tle1"), latest.get("tle2")
        if norad_id is None or not line1 or not line2:
            continue
        elements = _elements_or_none(line1, line2)
        if elements is None:
            continue
        objects.append(
            CatalogObject(
                norad_id=int(norad_id),
                name=satellite.get("name") or "",
                # Международное обозначение стоит в строке 1 колонками 10-17.
                intdes=line1[9:17].strip(),
                tle=TleLines(latest.get("tle0") or "", line1, line2),
                elements=elements,
            )
        )
    return objects


def _elements_or_none(line1: str, line2: str) -> Elements | None:
    try:
        return Elements.from_tle(line1, line2)
    except Exception:  # noqa: BLE001 — чужие строки, причина отказа не наша
        return None
