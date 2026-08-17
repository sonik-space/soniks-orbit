"""Загрузка водопада: скачивание, дисковый кеш, PIL, разбор чанков PNG.

Единственное место с PIL (правило 1). Файлы неизменяемы, поэтому кеш
по `observation_id` безопасен и обязателен: без него нагрузка на S3
избыточна (decisions/009).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from application.interfaces.image_fetcher import WaterfallImages
from domain.waterfall.metadata import WF_DAT, WaterfallMeta

DEFAULT_TIMEOUT = 60.0


class CachedWaterfallImages(WaterfallImages):
    def __init__(
        self,
        client: httpx.AsyncClient,
        cache_dir: Path,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._client = client
        self._cache_dir = Path(cache_dir)
        self._timeout = timeout

    async def load(
        self, observation_id: int, url: str
    ) -> tuple[np.ndarray, WaterfallMeta]:
        return decode(await self.fetch(observation_id, url))

    async def fetch(self, observation_id: int, url: str) -> Path:
        """Путь к PNG в кеше, скачивая только при первом обращении."""
        path = self._cache_dir / f"wf_{observation_id}.png"
        if path.exists():
            return path

        r = await self._client.get(url, timeout=self._timeout)
        r.raise_for_status()
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        return path


def decode(path: Path) -> tuple[np.ndarray, WaterfallMeta]:
    """PNG → массив RGB и калибровка из текстовых чанков."""
    img = Image.open(path)
    return np.asarray(img.convert("RGB")), WaterfallMeta.from_png_text(img.info)


def png_text_chunks(blob: bytes) -> dict[str, str]:
    """Текстовые чанки PNG из начала файла, без полной загрузки картинки.

    `matplotlib.savefig(metadata=...)` пишет их до `IDAT`, поэтому первых
    килобайт достаточно, и весь водопад ради метаданных качать не нужно.
    """
    out: dict[str, str] = {}
    if not blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return out

    at = 8
    while at + 8 <= len(blob):
        length = int.from_bytes(blob[at : at + 4], "big")
        kind = blob[at + 4 : at + 8]
        if kind == b"IDAT":
            break
        data = blob[at + 8 : at + 8 + length]
        if len(data) < length:
            break  # чанк не поместился в скачанный кусок
        if kind in (b"tEXt", b"iTXt") and b"\x00" in data:
            key, _, value = data.partition(b"\x00")
            out[key.decode("latin-1")] = value.lstrip(b"\x00").decode(
                "utf-8", "replace"
            )
        at += 12 + length
    return out


async def peek_wf_dat(
    client: httpx.AsyncClient, url: str, nbytes: int = 16384
) -> dict | None:
    """`satnogs:wf-dat` по Range-запросу первых килобайт PNG.

    Нужен, чтобы отсеять непригодные наблюдения (станция на клиенте старше
    2.2.x) не скачивая картинку целиком.
    """
    r = await client.get(
        url, headers={"Range": f"bytes=0-{nbytes - 1}"}, timeout=DEFAULT_TIMEOUT
    )
    if r.status_code not in (200, 206):
        return None
    raw = png_text_chunks(r.content).get(WF_DAT)
    return json.loads(raw) if raw else None
