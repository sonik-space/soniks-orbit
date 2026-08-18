"""Нетривиальные места инфраструктуры: курсор `Link`, кеш PNG и кеш каталога.

Сети не требуют: httpx подменяется `MockTransport`. Асинхронность гоняется
через `asyncio.run`, чтобы не тащить `pytest-asyncio` ради двух тестов
(правило 5: без фикстур и фреймворков сверх `pytest`).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from infrastructure.catalog.cache import CachedCatalog
from infrastructure.images.loader import CachedWaterfallImages, png_text_chunks
from infrastructure.network_api.django import DjangoNetworkApi, _next_page


def test_next_page_picks_the_link_marked_next() -> None:
    """Разбирается часть с `rel="next"`, а не первая попавшаяся.

    На странице, где `prev` идёт первым, наивный поиск `<...>` увёл бы обход
    назад, и он бы зациклился.
    """
    header = (
        '<http://sonik.space/api/observations/?page=1>; rel="prev", '
        '<http://sonik.space/api/observations/?page=3>; rel="next"'
    )
    assert _next_page(header) == "https://sonik.space/api/observations/?page=3"


def test_next_page_upgrades_to_https() -> None:
    """Django отдаёт ссылку по http, а редирект на https теряет параметры."""
    assert _next_page('<http://sonik.space/api/x/?a=1>; rel="next"').startswith(
        "https://"
    )


def test_next_page_is_none_on_the_last_page() -> None:
    assert _next_page('<http://sonik.space/api/x/>; rel="prev"') is None
    assert _next_page("") is None


def test_iter_observations_follows_the_cursor() -> None:
    pages = {
        "1": ([{"id": 1}, {"id": 2}], '<http://x/?page=2>; rel="next"'),
        "2": ([{"id": 3}], ""),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body, link = pages[request.url.params.get("page", "1")]
        return httpx.Response(200, json=body, headers={"Link": link} if link else {})

    async def collect() -> list[dict]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            api = DjangoNetworkApi(client)
            return [obs async for obs in api.iter_observations()]

    assert [o["id"] for o in asyncio.run(collect())] == [1, 2, 3]


def test_waterfall_is_downloaded_once(tmp_path) -> None:
    """Файлы неизменяемы, кеш обязателен (decisions/009): второе обращение
    к тому же наблюдению в сеть не идёт."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=b"\x89PNG\r\n\x1a\nfake")

    async def fetch_twice() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            images = CachedWaterfallImages(client, tmp_path)
            await images.fetch(1527888, "https://storage/wf.png")
            await images.fetch(1527888, "https://storage/wf.png")

    asyncio.run(fetch_twice())
    assert calls == 1
    assert (tmp_path / "wf_1527888.png").exists()


def test_png_text_chunks_reads_metadata_from_the_head() -> None:
    """Range-запрос первых килобайт: чанки лежат до `IDAT`, поэтому весь
    водопад ради метаданных качать не нужно."""
    waterfalls = Path(__file__).resolve().parents[1] / "golden" / "waterfalls"
    head = (waterfalls / "wf_1527888.png").read_bytes()[:16384]
    chunks = png_text_chunks(head)
    assert json.loads(chunks["satnogs:wf-dat"])["samp_rate"] == "57600"


def test_png_text_chunks_ignores_what_is_not_a_png() -> None:
    assert png_text_chunks(b"not a png at all") == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))


class _FakeCatalogApi:
    """Только тот метод протокола, который зовёт кеш (правило 5: фейк
    реализует вызываемое, а не весь интерфейс)."""

    def __init__(self) -> None:
        self.calls = 0

    async def list_catalog(self) -> list[dict]:
        self.calls += 1
        return [
            {
                "satellite": {"norad_cat_id": 64880, "name": "Geoscan-1"},
                "latest": {
                    "tle0": "0 Geoscan-1",
                    "tle1": "1 64880U 25155E   26228.44000000  .00000000  00000-0"
                    "  00000-0 0  9990",
                    "tle2": "2 64880  97.4000 300.0000 0006000 100.0000 260.0000"
                    " 15.20000000 10000",
                },
            }
        ]


def test_catalog_is_fetched_once_while_fresh(tmp_path) -> None:
    """Каталог, в отличие от водопада, **изменяем**: TLE в сети обновляется
    каждые 4 часа. Поэтому у кеша есть срок годности, и он же держит
    обращения к единственному троттлируемому эндпоинту сети
    (`/api/latesttles/`, 60/мин на IP) на два порядка ниже лимита."""
    api = _FakeCatalogApi()

    async def read_twice() -> list:
        catalog = CachedCatalog(api, tmp_path, ttl_seconds=3600.0)
        await catalog.objects()
        return await catalog.objects()

    objects = asyncio.run(read_twice())

    assert api.calls == 1
    assert [o.norad_id for o in objects] == [64880]
    assert objects[0].launch == "25155"
    assert (tmp_path / "latest_tles.json").exists()


def test_stale_catalog_is_refetched(tmp_path) -> None:
    """Протухший кеш обязан идти в сеть. Проверка отдельная потому, что
    отвалившийся срок годности выглядит как исправный кеш: объекты те же,
    просто вчерашние, и перебор молча ранжирует по устаревшим элементам."""
    api = _FakeCatalogApi()

    async def read_twice() -> None:
        catalog = CachedCatalog(api, tmp_path, ttl_seconds=-1.0)
        await catalog.objects()
        await catalog.objects()

    asyncio.run(read_twice())
    assert api.calls == 2
