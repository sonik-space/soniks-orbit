"""Клиент к боевому Django СОНИКС (`sonik.space`).

Перенесён из `scripts/phase0/sonik_api.py` — рабочего клиента фазы 0,
`requests` заменён на `httpx`. Всё, что специфично для текущего API, живёт
только здесь: переезд на v2 — это ещё одна реализация того же протокола
(integration.md).

Чтение публичное и авторизации не требует.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from application.interfaces.network_api import NetworkApi

DEFAULT_BASE_URL = "https://sonik.space"
DEFAULT_TIMEOUT = 60.0


class DjangoNetworkApi(NetworkApi):
    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._client = client
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._transmitters: dict[str, dict[str, Any] | None] = {}

    async def get_observation(self, observation_id: int) -> dict[str, Any]:
        """`GET /api/observations/{id}/` — всё нужное одним запросом.

        Отсюда берётся `tle`, а не выскребается регуляркой со страницы
        наблюдения, как делали оба старых инструмента (правило 4).
        """
        r = await self._client.get(
            f"{self._base}/api/observations/{observation_id}/", timeout=self._timeout
        )
        r.raise_for_status()
        return r.json()

    async def iter_observations(
        self, pages: int = 40, **params: Any
    ) -> AsyncIterator[dict[str, Any]]:
        """Постранично по `GET /api/observations/`. Курсор — в заголовке `Link`.

        Полезные фильтры (`network/api/filters.py::ObservationViewFilter`):
        `end` — не позже указанного ISO-времени, `status=good`,
        `waterfall_status=1` — размеченные человеком как «есть сигнал».
        Без `end` первые страницы забиты наблюдениями, которые ещё идут
        и водопада пока не имеют.
        """
        url = f"{self._base}/api/observations/"
        first = True
        for _ in range(pages):
            r = await self._client.get(
                url, params=params if first else None, timeout=self._timeout
            )
            r.raise_for_status()
            first = False
            for item in r.json():
                yield item

            url = _next_page(r.headers.get("Link", ""))
            if url is None:
                return

    async def get_transmitter(self, uuid: str) -> dict[str, Any] | None:
        """Запись передатчика по одному uuid, с кешем в памяти.

        Нужна ради полей `baud` и `downlink_low`: в ответе наблюдения лежит
        только uuid. Запрашивается по одному, а не списком: `GET /api/transmitters/`
        отдаёт ровно 100 записей и не листается (ни `page`, ни `limit`,
        ни заголовок `Link` не работают), так что полный справочник
        оттуда не собрать.
        """
        if not uuid:
            return None
        if uuid in self._transmitters:
            return self._transmitters[uuid]

        r = await self._client.get(
            f"{self._base}/api/transmitters/",
            params={"uuid": uuid},
            timeout=self._timeout,
        )
        r.raise_for_status()
        items = r.json()
        self._transmitters[uuid] = items[0] if items else None
        return self._transmitters[uuid]


def _next_page(link_header: str) -> str | None:
    """Ссылка `rel="next"` из заголовка `Link`, приведённая к https.

    Django отдаёт её по http, а редирект на https теряет параметры запроса.

    Разбирается именно та часть заголовка, у которой `rel="next"`, а не первая
    попавшаяся: в заголовке рядом лежат `prev` и `first`, и на странице,
    где `prev` идёт первым, обход пошёл бы назад и зациклился.
    """
    for part in link_header.split(","):
        if 'rel="next"' in part and "<" in part and ">" in part:
            url = part[part.index("<") + 1 : part.index(">")]
            return url.replace("http://", "https://", 1)
    return None
