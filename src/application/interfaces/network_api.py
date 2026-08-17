"""Контракт к сети СОНИКС в терминах предметной области, а не эндпоинтов.

Сегодня за ним стоит боевой Django (`infrastructure/network_api/django.py`),
после переезда — v2. Переезд это одна новая реализация протокола
(integration.md), поэтому ничего специфичного для текущего API сюда
не просачивается.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol


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
