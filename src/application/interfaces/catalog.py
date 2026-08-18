"""Контракт активного каталога сети для идентификации.

Каталог **не таблица** (data-model.md, «Что не хранится»): справочники СОНИКС
сервис не дублирует, а держит кешем. Отдельный интерфейс нужен затем же, зачем
`WaterfallImages`, — чтобы перебор кандидатов не знал ни про HTTP, ни про диск.
"""

from __future__ import annotations

from typing import Protocol

from domain.models import CatalogObject


class Catalog(Protocol):
    async def objects(self) -> list[CatalogObject]:
        """Весь активный каталог с последними элементами каждого объекта.

        Объекты запуска — это фильтр по `CatalogObject.launch` над тем же
        списком, а не второй запрос: обозначение запуска лежит в строке TLE.
        """
        ...
