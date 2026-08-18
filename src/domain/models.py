"""Доменные модели сервиса.

Один файл вместо структуры `entities/value_objects/dtos` по агрегатам, как
в `soniks-backend`: на четырёх сущностях та структура даёт только
навигационные издержки (architecture.md).

Правило 1 сюда не распространяется — оно про `domain/od` и `domain/waterfall`,
но лишних зависимостей здесь всё равно нет.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from domain.od.elements import Elements


@dataclass(frozen=True)
class TleLines:
    tle0: str
    tle1: str
    tle2: str


@dataclass(frozen=True)
class CatalogObject:
    """Объект активного каталога сети вместе с разобранными элементами.

    Элементы разбираются один раз при сборке кеша, а не на каждый скрининг:
    кандидатов около трёх тысяч, и `Satrec.twoline2rv` по ним на каждое
    наблюдение был бы чистой потерей.

    Строки TLE хранятся рядом с элементами, потому что подтверждение
    идентификации кладёт затравкой в сессию именно **их** — ту строку,
    по которой считался RMS, а не свежую из каталога (правило 10).
    """

    norad_id: int
    name: str
    intdes: str  # международное обозначение `YYNNNPPP` из `tle1[9:17]`
    tle: TleLines
    elements: Elements

    @property
    def launch(self) -> str:
        """`YYNNN` — общая часть обозначения у всех объектов одного запуска.

        Отдельного эндпоинта для этого нет: в монолите нет ни `/api/launches/`,
        ни поля с обозначением на спутнике, а фильтр `?launch__id=` принимает
        первичный ключ БД. Обозначение же лежит в самой строке TLE
        (integration.md).
        """
        return self.intdes[:5]


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
    и списку от них нужно только количество наблюдений.

    `rms_khz` — от последнего прогона фита, любого статуса: до фита у сессии
    нет числа, которое описывало бы её целиком.
    """

    uuid: UUID
    name: str
    norad_id: int | None
    status: str
    n_observations: int
    rms_khz: float | None = None


@dataclass(frozen=True)
class FitRun:
    """Прогон фита целиком: без него опубликованное TLE невоспроизводимо.

    `status == "failed"` — прогон, где `least_squares` не сошёлся или исчерпал
    `max_nfev`. Элементы и невязки в нём всё равно есть: без них не видно,
    что пошло не так (algorithms.md §4.4).
    """

    uuid: UUID
    session_uuid: UUID
    created_at: datetime
    author_sub: str
    config: dict[str, Any]
    elements_in: dict[str, Any]
    elements_out: dict[str, Any]
    tle: TleLines
    epoch_mjd: float
    rms_khz: float
    rms_pre_khz: float
    n_points: int
    per_observation: list[dict[str, Any]]
    residuals: dict[str, Any]
    prior_dominated: list[str]
    status: str


@dataclass(frozen=True)
class Publication:
    """Строка админ-вида «опубликованные за 7 дней» (decisions/007).

    Джойн прогона и сессии: в каталоге СОНИКС публикация фита неотличима
    от ручной строки, поэтому провенанс — какой спутник, какой прогон,
    с каким RMS и кто — есть только здесь.
    """

    fit_run_uuid: UUID
    session_uuid: UUID
    session_name: str
    norad_id: int | None
    published_at: datetime
    published_mode: str
    published_tle_id: int | None
    author_sub: str
    rms_khz: float
    n_points: int


@dataclass(frozen=True)
class Identification:
    """Задание идентификации: одно наблюдение и ранжированные кандидаты.

    Снимок ответа API, калибровка и точки лежат здесь по тому же правилу 10,
    что и у наблюдения сессии: без замороженного TLE наблюдения RMS кандидата
    невоспроизводим. Побочная выгода — подтверждение переносит готовые точки
    в созданную сессию, без второго скачивания PNG и второго извлечения.
    """

    uuid: UUID
    created_at: datetime
    observation_id: int
    stage: str  # screening / confirmed / rejected
    candidates: list[dict[str, Any]]
    meta: dict[str, Any]
    calibration: dict | None = None
    points: dict | None = None
    diagnostics: dict | None = None
    confirmed_norad_id: int | None = None
    confirmed_by_sub: str | None = None
    session_uuid: UUID | None = None

    @property
    def track(self) -> ObservationTrack:
        """То же наблюдение в виде, который понимают `build_segments`
        и `model_curve`. Сессии у задания нет, а наблюдение — есть,
        и второй сборки сегментов заводить незачем (правило 8)."""
        return ObservationTrack(
            uuid=self.uuid,
            observation_id=self.observation_id,
            meta=self.meta,
            extraction_status="ok",
            calibration=self.calibration,
            points=self.points,
            diagnostics=self.diagnostics,
        )


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
