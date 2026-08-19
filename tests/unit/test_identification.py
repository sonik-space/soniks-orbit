"""Перебор каталога без фита элементов (algorithms.md §6, decisions/006).

Сети тесты не требуют: срез каталога лежит в `tests/golden/catalog_25155.json`,
водопад, снимок наблюдения и **разметка человека** — там же, где у golden-тестов
калибровки.
Это тот же принцип, по которому заморожен снимок наблюдения (правило 10):
без зафиксированных элементов кандидатов RMS невоспроизводим.

Срез — запуск **2025-155** (22 объекта, среди них Geoscan-1) плюс четыре
объекта других запусков, которые на боевом каталоге оказывались следующими
по качеству. Четвёртый нужен именно затем, чтобы ступень «весь каталог»
проверялась на настоящих числах, а не на синтетике.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from application.services.calibration import calibrate_observation, measure_points
from application.services.identification import (
    MIN_CANDIDATE_MARGIN,
    is_screenable,
    launch_of,
    margin_of,
    screen_track,
)
from domain.models import ObservationTrack
from infrastructure.catalog.cache import _parse
from infrastructure.images.loader import decode

GOLDEN = Path(__file__).parents[1] / "golden"
WATERFALLS = GOLDEN / "waterfalls"

REFERENCE_ID = 1527888
REFERENCE_NORAD = 64880  # Geoscan-1
REFERENCE_LAUNCH = "25155"


def catalog() -> list:
    return _parse(json.loads((GOLDEN / "catalog_25155.json").read_text("utf-8")))


def track_of(observation_id: int) -> ObservationTrack:
    """Тот же путь, которым идёт фоновая задача: калибровка плюс точки человека.

    Разметка настоящая — 46 отметок по посылкам GEOSCAN 1, сделанные руками
    и сверенные с маркерами декодированных кадров (расхождение 1.1 пикселя).
    Синтетики здесь быть не может: перебор ранжирует по RMS, и на выдуманных
    точках тест проверял бы арифметику, а не пригодность разметки.
    """
    obs = json.loads(
        (WATERFALLS / f"obs_{observation_id}.json").read_text(encoding="utf-8")
    )
    marked = json.loads(
        (WATERFALLS / f"track_{observation_id}.json").read_text(encoding="utf-8")
    )
    rgb, meta = decode(WATERFALLS / f"wf_{observation_id}.png")
    calibrated = calibrate_observation(rgb, meta, obs)

    mjd = np.asarray(marked["mjd"], dtype=float)
    f_offset = np.asarray(marked["f_offset_hz"], dtype=float)
    weight = np.ones_like(mjd)
    m = measure_points(obs, calibrated.calibration.center_freq_hz, mjd, f_offset, weight)
    n = mjd.size
    return ObservationTrack(
        uuid=uuid4(),
        observation_id=observation_id,
        meta=obs,
        extraction_status="ok",
        calibration=calibrated.calibration.to_dict(),
        points={
            "mjd": mjd.tolist(),
            "f_abs_hz": m.f_abs_hz.tolist(),
            "f_offset_hz": f_offset.tolist(),
            "snr": [0.0] * n,
            "weight": weight.tolist(),
            "enabled": [True] * n,
            "source": ["manual"] * n,
        },
        diagnostics=m.diagnostics(),
    )


@pytest.fixture(scope="module")
def objects() -> list:
    return catalog()


@pytest.fixture(scope="module")
def reference() -> ObservationTrack:
    return track_of(REFERENCE_ID)


@pytest.mark.xfail(
    reason="ядро считает f_abs формулой «сырой, ось инвертирована», а запись\n    ведётся с доплеровской коррекцией: на разметке человека эта формула даёт\n    Geoscan-3 с отрывом 1.3x, а «доплер снят» — верный Geoscan-1 с отрывом 97x.\n    Решение по конвенции за пользователем, см. decisions/015.",
    strict=True,
)
def test_the_right_object_wins_by_an_order_of_magnitude(reference, objects) -> None:
    """Главное число фазы 6.

    Правильный объект обязан быть первым **и** оторваться от следующего
    на порядок: ранжирования достаточно только потому, что отрыв велик,
    и человеку остаётся подтверждение (decisions/006). Замер на боевом
    каталоге внутри запуска — ×177; порог здесь на порядок ниже, чтобы
    тест ловил поломку, а не дрожание последних знаков.
    """
    candidates = screen_track(reference, objects)

    assert candidates[0].norad_id == REFERENCE_NORAD
    assert candidates[0].rms_khz < 0.05
    assert margin_of([c.rms_khz for c in candidates]) > 10.0


@pytest.mark.xfail(
    reason="ядро считает f_abs формулой «сырой, ось инвертирована», а запись\n    ведётся с доплеровской коррекцией: на разметке человека эта формула даёт\n    Geoscan-3 с отрывом 1.3x, а «доплер снят» — верный Geoscan-1 с отрывом 97x.\n    Решение по конвенции за пользователем, см. decisions/015.",
    strict=True,
)
def test_screening_stops_inside_the_launch(reference, objects) -> None:
    """Перебор по запуску закончился на нём же и до каталога не дошёл.

    Порядок из decisions/006 держится не только ценой: внутри запуска
    отрыв на порядок выше, и уход в каталог без нужды его бы потерял.
    """
    candidates = screen_track(reference, objects)

    assert launch_of(reference.meta) == REFERENCE_LAUNCH
    assert all(c.same_launch for c in candidates)
    assert len(candidates) == sum(1 for o in objects if o.launch == REFERENCE_LAUNCH)


@pytest.mark.xfail(
    reason="ядро считает f_abs формулой «сырой, ось инвертирована», а запись\n    ведётся с доплеровской коррекцией: на разметке человека эта формула даёт\n    Geoscan-3 с отрывом 1.3x, а «доплер снят» — верный Geoscan-1 с отрывом 97x.\n    Решение по конвенции за пользователем, см. decisions/015.",
    strict=True,
)
def test_low_margin_inside_the_launch_escalates_to_the_catalog(
    reference, objects
) -> None:
    """Неразличимые объекты запуска переводят перебор на весь каталог.

    Настоящего объекта в запуске нет — остаются двадцать один почти
    одинаковых по RMS, и отрыв падает до единицы. Без перехода на каталог
    задание вернуло бы уверенный список из мусора.
    """
    without_truth = [o for o in objects if o.norad_id != REFERENCE_NORAD]
    mates = [o for o in without_truth if o.launch == REFERENCE_LAUNCH]

    assert margin_of([c.rms_khz for c in screen_track(reference, mates)]) < (
        MIN_CANDIDATE_MARGIN
    )

    candidates = screen_track(reference, without_truth)
    assert not candidates[0].same_launch
    assert len(candidates) > len(mates)


@pytest.mark.xfail(
    reason="ядро считает f_abs формулой «сырой, ось инвертирована», а запись\n    ведётся с доплеровской коррекцией: на разметке человека эта формула даёт\n    Geoscan-3 с отрывом 1.3x, а «доплер снят» — верный Geoscan-1 с отрывом 97x.\n    Решение по конвенции за пользователем, см. decisions/015.",
    strict=True,
)
def test_unknown_launch_goes_straight_to_the_catalog(reference, objects) -> None:
    """Без TLE у наблюдения запуск неизвестен, и ступень по запуску пропускается.

    Молчаливого «запуск пустой, значит все свои» здесь быть не должно:
    пометка `same_launch` тогда стояла бы у всех и ничего не значила.
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

    candidates = screen_track(blind, objects)

    assert launch_of(blind.meta) == ""
    assert candidates[0].norad_id == REFERENCE_NORAD
    assert not any(c.same_launch for c in candidates)


@pytest.mark.xfail(
    reason="ядро считает f_abs формулой «сырой, ось инвертирована», а запись\n    ведётся с доплеровской коррекцией: на разметке человека эта формула даёт\n    Geoscan-3 с отрывом 1.3x, а «доплер снят» — верный Geoscan-1 с отрывом 97x.\n    Решение по конвенции за пользователем, см. decisions/015.",
    strict=True,
)
def test_candidate_keeps_the_lines_it_was_scored_with(reference, objects) -> None:
    """Затравкой сессии идут строки кандидата, поэтому они обязаны доехать
    до задания нетронутыми: каталог обновляется каждые 4 часа, а человек
    подтверждает позже, и пересчитать RMS по свежей строке — значит
    подменить показанное число (правило 10)."""
    best = screen_track(reference, objects)[0]
    source = next(o for o in objects if o.norad_id == REFERENCE_NORAD)

    assert (best.tle1, best.tle2) == (source.tle.tle1, source.tle.tle2)


def test_empty_track_never_reaches_the_screening() -> None:
    """Неразмеченное наблюдение в перебор не идёт: перебирать нечего.

    Это штатное состояние свежего наблюдения, а не отказ: точки ставит
    человек, и до него их нет.
    """
    reference = track_of(REFERENCE_ID)
    empty = ObservationTrack(
        uuid=reference.uuid,
        observation_id=reference.observation_id,
        meta=reference.meta,
        extraction_status="ok",
        calibration=reference.calibration,
        points={key: [] for key in reference.points},
        diagnostics={},
    )

    assert not is_screenable(empty)



def test_a_marked_track_is_screenable_even_without_convention_margin() -> None:
    """Разметка человека вертикальна, и запас между конвенциями у неё 1.000.

    Прежний порог `reliable >= 2` отверг бы её целиком: он различал конвенции
    через доплеровский размах, которого у скорректированной записи нет.
    """
    reference = track_of(REFERENCE_ID)

    assert reference.diagnostics["margin"] == pytest.approx(1.0, abs=0.01)
    assert is_screenable(reference)


def test_single_candidate_has_no_margin() -> None:
    """Одиночный объект запуска — не повод объявлять его ответом.
    Бесконечный отрыв здесь читался бы как «определено точно»."""
    assert margin_of([0.5]) == 0.0
    assert margin_of([]) == 0.0
    assert margin_of([0.5, 5.0]) == pytest.approx(10.0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
