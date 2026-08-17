"""Контракт загрузки водопада.

Скачивание и декодирование PNG — это инфраструктура, а не алгоритм
(правило 1), поэтому сервис извлечения получает уже готовый массив
и разобранные метаданные.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from domain.waterfall.metadata import WaterfallMeta


class WaterfallImages(Protocol):
    async def load(
        self, observation_id: int, url: str
    ) -> tuple[np.ndarray, WaterfallMeta]:
        """Массив RGB области картинки целиком и калибровка из чанков PNG.

        Файлы неизменяемы, поэтому реализация обязана кешировать их на диске
        по `observation_id` (decisions/009).

        Поднимает `CalibrationError`, если в PNG нет `satnogs:wf-dat`:
        наблюдение непригодно, полоса невосстановима.
        """
        ...
