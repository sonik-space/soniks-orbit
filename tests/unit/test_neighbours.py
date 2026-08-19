"""Кривые соседей по запуску поверх водопада (упражнение 2 гайда, клавиша `p`).

Каталог — тот же закоммиченный срез запуска 2025-155, что и у идентификации,
и наблюдение то же: без замороженных элементов кривые невоспроизводимы
(правило 10). Асинхронность гоняется `asyncio.run`, чтобы не тащить
`pytest-asyncio` (правило 5).
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from test_identification import (
    REFERENCE_ID,
    REFERENCE_LAUNCH,
    REFERENCE_NORAD,
    catalog,
    track_of,
)

from application.queries.session.neighbours import GetNeighbourCurvesQuery
from core.configs.fit import FitSettings
from domain.exceptions import NotFoundError
from domain.models import CatalogObject, ObservationTrack


class FakeRepo:
    def __init__(self, *tracks: ObservationTrack) -> None:
        self._tracks = {t.observation_id: t for t in tracks}

    async def get_observation(self, _session_uuid: UUID, observation_id: int):
        return self._tracks.get(observation_id)


class FakeCatalog:
    def __init__(self, objects: list[CatalogObject]) -> None:
        self._objects = objects

    async def objects(self) -> list[CatalogObject]:
        return self._objects


def _ask(track: ObservationTrack, objects: list[CatalogObject]):
    query = GetNeighbourCurvesQuery(
        FakeRepo(track), FakeCatalog(objects), FitSettings()
    )
    return asyncio.run(query(uuid4(), track.observation_id))


@pytest.fixture(scope="module")
def reference() -> ObservationTrack:
    return track_of(REFERENCE_ID)


@pytest.fixture(scope="module")
def objects() -> list[CatalogObject]:
    return catalog()


def test_curves_cover_the_whole_launch(reference, objects) -> None:
    """Соседи — весь запуск, и кривая у каждого на сетке водопада.

    Именно весь: смысл наложения в том, чтобы найти линию, которой на экране
    не ждали, а урезанный список её как раз и спрячет.
    """
    response = _ask(reference, objects)

    mates = [o for o in objects if o.launch == REFERENCE_LAUNCH]
    assert response.launch == REFERENCE_LAUNCH
    assert len(response.curves) == len(mates)
    assert {c.norad_id for c in response.curves} == {o.norad_id for o in mates}

    points = FitSettings().MODEL_CURVE_POINTS
    for curve in response.curves:
        assert len(curve.mjd) == len(curve.f_offset_hz) == points


def test_neighbour_curve_is_raw_doppler(reference, objects) -> None:
    """Кривая пролетающего соседа обязана иметь доплеровский размах.

    Станция чужой объект не ведёт, поэтому его след на водопаде — широкая
    S-кривая (algorithms.md §2), и именно по размаху человек отличает помеху
    от своего сигнала: разметка человека лежит в пределах сотен герц.

    Размах требуется от объекта, который в это окно действительно проходит
    над станцией, а не от каждого. Соседи по запуску разъезжаются по трассе,
    и у далёкого в шестиминутном окне лучевая скорость почти постоянна —
    его кривая законно выходит пологой.
    """
    response = _ask(reference, objects)
    swings = {c.norad_id: max(c.f_offset_hz) - min(c.f_offset_hz) for c in response.curves}

    assert swings[REFERENCE_NORAD] > 10_000.0, (
        "объект, ради которого планировалось наблюдение, вышел без размаха — "
        "значит кривая не сырая"
    )

    marked = reference.points["f_offset_hz"]
    assert max(marked) - min(marked) < swings[REFERENCE_NORAD] / 10.0


def test_unknown_launch_returns_an_empty_list(reference, objects) -> None:
    """Наблюдение без TLE: запуска нет, соседей нет — и это не ошибка.

    Пустой список тут значит «не по чему строить», а не «в запуске никого».
    """
    blind = ObservationTrack(
        uuid=reference.uuid,
        observation_id=reference.observation_id,
        meta={**reference.meta, "tle": None},
        extraction_status="ok",
        calibration=reference.calibration,
        points=reference.points,
        diagnostics=reference.diagnostics,
    )

    response = _ask(blind, objects)
    assert response.launch == ""
    assert response.curves == []


def test_missing_observation_is_a_not_found(reference, objects) -> None:
    query = GetNeighbourCurvesQuery(FakeRepo(), FakeCatalog(objects), FitSettings())
    with pytest.raises(NotFoundError):
        asyncio.run(query(uuid4(), REFERENCE_ID))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
