"""Доменные модели сервиса.

Один файл вместо структуры `entities/value_objects/dtos` по агрегатам, как
в `soniks-backend`: на четырёх сущностях та структура даёт только
навигационные издержки (architecture.md).

Правило 1 сюда не распространяется — оно про `domain/od` и `domain/waterfall`,
но лишних зависимостей здесь всё равно нет.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class TleLines:
    tle0: str
    tle1: str
    tle2: str


@dataclass(frozen=True)
class ObservationTrack:
    """Наблюдение в составе сессии вместе с замороженным снимком ответа API."""

    uuid: UUID
    observation_id: int
    meta: dict[str, Any]
    extraction_status: str
    extraction_error: str | None = None
    calibration: dict | None = None
    points: dict | None = None
    diagnostics: dict | None = None

    @property
    def n_points(self) -> int:
        return len(self.points["mjd"]) if self.points else 0

    @property
    def waterfall_url(self) -> str | None:
        return self.meta.get("waterfall")


@dataclass(frozen=True)
class SessionSummary:
    """Строка списка сессий. Точки не читаются: они лежат блоком в JSONB,
    и списку от них нужно только количество наблюдений."""

    uuid: UUID
    name: str
    norad_id: int | None
    status: str
    n_observations: int


@dataclass(frozen=True)
class OdSession:
    uuid: UUID
    name: str
    norad_id: int | None
    owner_sub: str
    seed: TleLines
    seed_source: str
    status: str
    observations: list[ObservationTrack] = field(default_factory=list)
