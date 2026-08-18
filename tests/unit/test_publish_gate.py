"""Порог качества публикации (decisions/007, правило 11).

Единственное, что стоит между ошибкой оператора и наведением всей сети:
источник записи в каталоге — `Manual`, а он первый в `TLE_SOURCE_PRIORITY`,
то есть опубликованное TLE выигрывает даже у свежего Space-Track.

Проверяется, что **каждое** условие отсекает по отдельности, а не что
«в целом работает»: порог, у которого молча отвалилась одна проверка,
выглядит точно так же, как исправный.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from uuid import uuid4

import pytest

from application.commands.fit.publish import (
    MAX_RMS_KHZ,
    MAX_SEPARATION_KM,
    MIN_OBSERVATIONS,
    MIN_POINTS,
    check_quality,
)
from application.services.fitting import elements_to_dict
from domain.exceptions import ConflictError
from domain.models import FitRun, TleLines
from domain.od.elements import Elements
from domain.od.tle import to_lines

STRF = Path(__file__).resolve().parents[3] / "strf"


def _seed_lines() -> TleLines:
    """Настоящий набор, а не синтетика: `Elements.from_tle` идёт через
    `Satrec.twoline2rv`, и придуманные строки он разбирает не так, как реальные."""
    lines = [
        ln.rstrip("\n")
        for ln in (STRF / "l10.tle").read_text(errors="replace").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    for i in range(len(lines) - 1):
        if lines[i].startswith("1 ") and lines[i + 1].startswith("2 "):
            return TleLines(tle0="ЭТАЛОН", tle1=lines[i], tle2=lines[i + 1])
    raise AssertionError(f"в {STRF / 'l10.tle'} нет пары строк TLE")


SEED = _seed_lines()
SEED_ELEMENTS = Elements.from_tle(SEED.tle1, SEED.tle2)


def _moved(**delta: float) -> Elements:
    """Элементы, сдвинутые относительно эталонных на заданные приращения."""
    order = (
        "incl_deg",
        "raan_deg",
        "ecc",
        "argp_deg",
        "ma_deg",
        "rev_per_day",
        "bstar",
    )
    assert set(delta) <= set(order), f"неизвестный элемент: {set(delta) - set(order)}"
    return SEED_ELEMENTS.with_vector(
        SEED_ELEMENTS.to_vector() + [delta.get(name, 0.0) for name in order]
    )


def _lines(elements: Elements) -> TleLines:
    line1, line2 = to_lines(elements)
    return TleLines(tle0=SEED.tle0, tle1=line1, tle2=line2)


def _shifted(delta_ma_deg: float) -> TleLines:
    """Результат «фита», отличающийся от затравки сдвигом средней аномалии.

    Сдвиг по `M` — самый прямой способ развести положения на заданное
    расстояние вдоль орбиты, не трогая форму.
    """
    return _lines(_moved(ma_deg=delta_ma_deg))


def _run(**overrides) -> FitRun:
    fields = {
        "status": "ok",
        "rms_khz": 0.42,
        "n_points": 1240,
        "config": {"observation_ids": [1037258, 1039405]},
        "tle": SEED,
        # Затравка **этого прогона**, а не текущая затравка сессии: с фазы 7
        # последнюю можно менять, и порог обязан судить по первой.
        "elements_in": elements_to_dict(SEED_ELEMENTS),
    }
    fields.update(overrides)
    return FitRun(
        uuid=uuid4(),
        session_uuid=uuid4(),
        created_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
        author_sub="sub",
        elements_out={},
        epoch_mjd=SEED_ELEMENTS.epoch_mjd,
        rms_pre_khz=3.87,
        per_observation=[],
        residuals={},
        prior_dominated=[],
        **fields,
    )


def test_good_run_passes() -> None:
    """Иначе все проверки ниже зеленели бы на порогe, который запрещает всё."""
    check_quality(_run())


def test_failed_run_is_refused_even_with_good_rms() -> None:
    """Ровно тот случай, ради которого добавлено пятое условие: у прогона
    со статусом `failed` элементы и невязки есть, и RMS проходит по числу,
    но `least_squares` до этих элементов не сошёлся."""
    with pytest.raises(ConflictError, match="не сошёлся"):
        check_quality(_run(status="failed"))


def test_rms_above_threshold_is_refused() -> None:
    with pytest.raises(ConflictError, match="RMS"):
        check_quality(_run(rms_khz=MAX_RMS_KHZ + 0.01))


def test_too_few_points_is_refused() -> None:
    with pytest.raises(ConflictError, match="точек"):
        check_quality(_run(n_points=MIN_POINTS - 1))


def test_single_observation_is_refused() -> None:
    """Из одного прохода наблюдаемы примерно две величины: RMS правдоподобен
    при бессмысленных элементах (algorithms.md §4.4)."""
    with pytest.raises(ConflictError, match="наблюдений"):
        check_quality(_run(config={"observation_ids": [1037258][: MIN_OBSERVATIONS - 1]}))


def test_far_from_seed_is_refused() -> None:
    """Фит, уехавший на сотни километров, — это другой объект или
    развалившийся оптимизатор, а не уточнение орбиты."""
    with pytest.raises(ConflictError, match="расхождение"):
        check_quality(_run(tle=_shifted(1.0)))


def test_small_shift_from_seed_passes() -> None:
    """Порог не должен отсекать нормальное уточнение: сдвиг на пару десятков
    километров вдоль орбиты — обычный результат фита."""
    run = _run(tle=_shifted(0.05))
    check_quality(run)

    from domain.od.reepoch import separation_km

    separation = separation_km(
        SEED_ELEMENTS, Elements.from_tle(run.tle.tle1, run.tle.tle2), run.epoch_mjd
    )
    assert 0.0 < separation < MAX_SEPARATION_KM


def test_zero_eccentricity_is_refused() -> None:
    """Шаг 7 гайда. `classel` зажимает отрицательный эксцентриситет ровно
    в ноль, и круговая орбита на месте эллиптической проходит и по RMS,
    и по расхождению: положение почти то же, а элемент потерян."""
    collapsed = _moved(ecc=-SEED_ELEMENTS.ecc)
    assert collapsed.ecc == 0.0, "заготовка теста не обнулила эксцентриситет"

    with pytest.raises(ConflictError, match="эксцентриситет"):
        check_quality(_run(tle=_lines(collapsed)))


def test_separation_is_judged_against_the_run_seed_not_the_session() -> None:
    """Дефект, который чинит переход на `elements_in`.

    Прогон фитили из затравки, уехавшей на градус по средней аномалии, и его
    результат лежит рядом с **ней**. Пока порог читал `session.seed`, любая
    правка затравки сессии пересуживала такой прогон по элементам, которых
    он никогда не видел, — и отказывала в публикации задним числом.
    """
    run_seed = _moved(ma_deg=1.0)
    run = _run(
        elements_in=elements_to_dict(run_seed),
        tle=_lines(run_seed.with_vector(run_seed.to_vector())),
    )
    check_quality(run)

    # И то же самое было бы отвергнуто, считай мы от эталонной затравки.
    with pytest.raises(ConflictError, match="расхождение"):
        check_quality(_run(tle=run.tle))
