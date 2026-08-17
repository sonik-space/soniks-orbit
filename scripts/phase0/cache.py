"""Дисковый кеш корпуса для стендов фаз 0 и 1.

Сеть и декодирование PNG живут в `infrastructure/`, здесь — только
синхронная обёртка над ними и кеш JSON-ответов, чтобы прогон по корпусу
из 23 наблюдений работал офлайн.

Снимок наблюдения кешируется по той же причине, по которой он замораживается
в `od_session_observations.meta` (правило 10): TLE в каталоге обновляется
каждые 4 часа, и без снимка RMS перестал бы воспроизводиться.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import numpy as np

from domain.waterfall.metadata import WaterfallMeta
from infrastructure.images.loader import CachedWaterfallImages, decode
from infrastructure.network_api.django import DjangoNetworkApi

CACHE = Path(__file__).parent / "cache"


def _run(coro):
    async def wrapped():
        async with httpx.AsyncClient(follow_redirects=True) as client:
            return await coro(client)

    return asyncio.run(wrapped())


def get_observation(observation_id: int, *, refresh: bool = False) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"obs_{observation_id}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))

    obs = _run(lambda c: DjangoNetworkApi(c).get_observation(observation_id))
    path.write_text(json.dumps(obs, ensure_ascii=False, indent=1), encoding="utf-8")
    return obs


def load_waterfall(obs: dict) -> tuple[np.ndarray, WaterfallMeta]:
    url = obs.get("waterfall")
    if not url:
        raise ValueError(f"у наблюдения {obs['id']} нет водопада")

    path = CACHE / f"wf_{obs['id']}.png"
    if not path.exists():
        _run(lambda c: CachedWaterfallImages(c, CACHE).fetch(obs["id"], url))
    return decode(path)


def get_transmitter(uuid: str) -> dict | None:
    """Передатчик по uuid с кешем на диске: `scan_observations.py` перебирает
    сотни наблюдений, а справочник списком не листается."""
    if not uuid:
        return None

    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "transmitters.json"
    disk = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if uuid in disk:
        return disk[uuid]

    disk[uuid] = _run(lambda c: DjangoNetworkApi(c).get_transmitter(uuid))
    path.write_text(json.dumps(disk, ensure_ascii=False), encoding="utf-8")
    return disk[uuid]


def iter_observations(pages: int = 40, **params):
    """Список наблюдений из боевого API. Не кешируется: это разведка, а не корпус."""

    async def collect(client):
        api = DjangoNetworkApi(client)
        return [obs async for obs in api.iter_observations(pages=pages, **params)]

    return _run(collect)


def peek_wf_dat(url: str, nbytes: int = 16384) -> dict | None:
    from infrastructure.images.loader import peek_wf_dat as _peek

    return _run(lambda c: _peek(c, url, nbytes))
