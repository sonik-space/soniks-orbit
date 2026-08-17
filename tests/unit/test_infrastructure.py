"""Два нетривиальных места инфраструктуры: курсор в заголовке `Link` и кеш PNG.

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
