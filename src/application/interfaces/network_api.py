"""Контракт к сети СОНИКС в терминах предметной области, а не эндпоинтов.

Сегодня за ним стоит боевой Django (`infrastructure/network_api/django.py`),
после переезда — v2. Переезд это одна новая реализация протокола
(integration.md), поэтому ничего специфичного для текущего API сюда
не просачивается.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from domain.models import TleLines


class NetworkApi(Protocol):
    async def get_observation(self, observation_id: int) -> dict[str, Any]:
        """Ответ по наблюдению **целиком, как есть**.

        Возвращается сырой словарь, а не разобранная модель, потому что он
        целиком замораживается в `od_session_observations.meta` (правило 10):
        TLE в каталоге обновляется каждые 4 часа, и без снимка пересчёт
        по новому TLE изменил бы смысл уже посчитанных `f_abs_hz`.
        Разбор полей — дело того, кто их читает.
        """
        ...

    def iter_observations(self, **params: Any) -> AsyncIterator[dict[str, Any]]:
        """Список наблюдений для подбора, постранично."""
        ...

    async def get_transmitter(self, uuid: str) -> dict[str, Any] | None:
        """Запись передатчика по uuid: нужны `baud` и `downlink_low`."""
        ...

    async def publish_tle(
        self, *, norad_id: int, lines: TleLines, url: str, access_token: str
    ) -> int:
        """Запись TLE в каталог сети. Возвращает идентификатор записи.

        Публикация идёт **от имени человека**, а не сервиса: права проверяет
        сеть, своей модели прав сервис не держит (integration.md). Отсюда
        `access_token` — тот же токен, с которым пришёл запрос.

        `url` — ссылка на прогон фита. В каталоге источник записи неотличим
        от ручной, и эта ссылка — единственный провенанс на той стороне.

        Отказ по правам поднимает `ForbiddenError`: вызывающий превращает его
        в предложение (decisions/007).
        """
        ...
