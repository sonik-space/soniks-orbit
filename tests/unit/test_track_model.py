"""Модельная кривая поверх наблюдения, которого в прогоне не было.

Это шаг 5 гайда: проверить TLE по проходу, не участвовавшему в фите. Раньше
он был невыполним — `_model` искал несущую в `per_observation` и возвращал
`None`. Здесь и умирает `ikhnosoniks`.

Асинхронность гоняется через `asyncio.run`, чтобы не тащить `pytest-asyncio`
(правило 5). Треки синтетические, но геометрия настоящая: времена, станция
и TLE берутся из замороженных снимков `tests/golden/waterfalls/`.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest

from application.queries.session.by_uuid import GetTrackQuery
from application.services.fitting import carrier_khz_for, elements_to_dict, to_tle
from core.configs.fit import FitSettings
from domain.exceptions import NotFoundError
from domain.models import FitRun, ObservationTrack, OdSession, TleLines
from domain.od.doppler import fac as doppler_fac
from domain.od.elements import Elements
from domain.od.geometry import range_rate

GOLDEN = Path(__file__).parents[1] / "golden/waterfalls"
MJD_UNIX_EPOCH = 40587.0
CARRIER_HZ = 435975000.0

# Два прохода объекта 64880 с одним и тем же TLE в снимке: фит идёт по одному,
# кривая накладывается на второй. Совпадение TLE делает проверку острой —
# профилированная несущая обязана вернуть ровно CARRIER_HZ.
FITTED, UNSEEN = 1526972, 1526877


def _mjd(iso: str) -> float:
    return dt.datetime.fromisoformat(iso).timestamp() / 86400.0 + MJD_UNIX_EPOCH


def _track(observation_id: int, n: int = 40, *, with_points: bool = True):
    """Наблюдение с полной калибровкой и треком точно на его собственном TLE."""
    meta = json.loads((GOLDEN / f"obs_{observation_id}.json").read_text())
    start, end = _mjd(meta["start"]), _mjd(meta["end"])
    center_hz = float(meta["observation_frequency"])

    # Калибровка настоящей формы: `curve_inputs` берёт из неё сетку времени,
    # а `calibration_schema` — всю рамку осей целиком.
    plot_h = 1546
    calibration = {
        "img_w": 841,
        "img_h": 1676,
        "plot_left": 81,
        "plot_top": 15,
        "plot_w": 600,
        "plot_h": plot_h,
        "t_bottom_mjd": start,
        "sec_per_px": (end - start) * 86400.0 / (plot_h - 1),
        "f_min_hz": -28800.0,
        "f_max_hz": 28743.75,
        "center_freq_hz": center_hz,
        "samp_rate_hz": 57600,
        "nchan": 1024,
        "bin_hz": 56.25,
    }

    points = None
    if with_points:
        mjd = np.linspace(start + 0.1 * (end - start), end - 0.1 * (end - start), n)
        seed = Elements.from_tle(meta["tle"]["tle1"], meta["tle"]["tle2"])
        v_km_s, err = range_rate(
            seed.to_satrec(),
            mjd,
            float(meta["station_lat"]),
            float(meta["station_lng"]),
            float(meta["station_alt"]) / 1000.0,
        )
        assert not np.any(err), "затравка снимка не прогоняется на его же временах"
        f_abs_hz = doppler_fac(v_km_s) * CARRIER_HZ
        points = {
            "mjd": mjd.tolist(),
            "f_abs_hz": f_abs_hz.tolist(),
            "f_offset_hz": (center_hz - f_abs_hz).tolist(),
            "snr": [10.0] * n,
            "weight": [1.0] * n,
            "enabled": [True] * n,
            "source": ["auto"] * n,
        }

    return ObservationTrack(
        uuid=uuid4(),
        observation_id=observation_id,
        meta=meta,
        extraction_status="ok",
        calibration=calibration,
        points=points,
    )


def _run(session_uuid: UUID, observation_id: int) -> FitRun:
    """Прогон по одному наблюдению. Его TLE — то же, что в снимке `UNSEEN`."""
    meta = json.loads((GOLDEN / f"obs_{observation_id}.json").read_text())
    tle = meta["tle"]
    elements = elements_to_dict(Elements.from_tle(tle["tle1"], tle["tle2"]))
    return FitRun(
        uuid=uuid4(),
        session_uuid=session_uuid,
        created_at=dt.datetime.now(tz=dt.UTC),
        author_sub="sub",
        config={},
        elements_in=elements,
        elements_out=elements,
        tle=TleLines(tle0=tle["tle0"], tle1=tle["tle1"], tle2=tle["tle2"]),
        epoch_mjd=elements["epoch_mjd"],
        rms_khz=0.02,
        rms_pre_khz=0.03,
        n_points=40,
        per_observation=[{"observation_id": observation_id, "carrier_hz": CARRIER_HZ}],
        residuals={},
        prior_dominated=[],
        status="ok",
    )


class FakeSessionRepo:
    def __init__(self, *tracks: ObservationTrack) -> None:
        self._tracks = {t.observation_id: t for t in tracks}

    async def get_observation(self, _session_uuid: UUID, observation_id: int):
        return self._tracks.get(observation_id)

    async def get(self, session_uuid: UUID) -> OdSession:
        """Затравка — TLE первого наблюдения: `?fit=seed` обязан взять её,
        а не элементы прогона."""
        first = next(iter(self._tracks.values()))
        tle = first.meta["tle"]
        return OdSession(
            uuid=session_uuid,
            name="фикстура",
            norad_id=64880,
            owner_sub="sub",
            seed=TleLines(tle0=tle["tle0"], tle1=tle["tle1"], tle2=tle["tle2"]),
            seed_source="catalog",
            status="draft",
            observations=list(self._tracks.values()),
        )


class FakeFitRepo:
    def __init__(self, *runs: FitRun) -> None:
        self._runs = {r.uuid: r for r in runs}
        self._latest = runs[-1] if runs else None

    async def latest(self, _session_uuid: UUID) -> FitRun | None:
        return self._latest

    async def get(self, fit_run_id: UUID) -> FitRun | None:
        return self._runs.get(fit_run_id)


def _ask(tracks, runs, observation_id: int, fit=None):
    query = GetTrackQuery(FakeSessionRepo(*tracks), FakeFitRepo(*runs), FitSettings())
    return asyncio.run(query(uuid4(), observation_id, fit))


def test_carrier_is_profiled_from_the_observations_own_points() -> None:
    """Ступень 2 фолбэка: наблюдения в прогоне не было, но точки есть.

    Точки `UNSEEN` лежат на том же TLE, что и в прогоне, поэтому замкнутая
    форма обязана вернуть ровно ту несущую, из которой они построены. Допуск
    в герц — это проверка, что фолбэк действительно посчитал, а не подставил
    частоту наблюдения (435.9735 МГц, мимо на 1.5 кГц).
    """
    unseen = _track(UNSEEN)
    run = _run(uuid4(), FITTED)

    carrier_khz = carrier_khz_for(run, unseen)
    assert carrier_khz is not None
    assert abs(carrier_khz * 1000.0 - CARRIER_HZ) < 1.0


def test_carrier_falls_back_to_observation_frequency_without_points() -> None:
    """Ступень 3: точек нет вовсе — форма кривой всё равно нужна."""
    empty = _track(UNSEEN, with_points=False)
    carrier_khz = carrier_khz_for(_run(uuid4(), FITTED), empty)

    assert carrier_khz == empty.meta["observation_frequency"] / 1000.0


def test_model_is_returned_for_an_observation_outside_the_run() -> None:
    """Шаг 5 гайда целиком: прогон по одному проходу, кривая — на другом."""
    session_uuid = uuid4()
    tracks = (_track(FITTED), _track(UNSEEN))
    run = _run(session_uuid, FITTED)

    response = _ask(tracks, (run,), UNSEEN)

    assert response.model is not None, (
        "наблюдение вне прогона снова осталось без кривой"
    )
    model = response.model
    assert len(model.mjd) == len(model.f_offset_hz) == FitSettings().MODEL_CURVE_POINTS
    assert len(model.az_deg) == len(model.alt_deg) == len(model.mjd)
    assert max(model.alt_deg) > 0.0, "проход целиком под горизонтом"
    assert all(0.0 <= az < 360.0 for az in model.az_deg)
    # Метки времени: сближение внутри окна водопада, эпоха — от элементов прогона.
    assert model.t_ca is not None
    assert response.calibration.t_min <= model.t_ca <= response.calibration.t_max
    assert model.t_epoch is not None


def test_named_fit_from_another_session_is_not_overlaid() -> None:
    """`?fit=` берёт прогон **этой** сессии: чужой водопад под чужим TLE
    выглядит как разошедшийся фит, и объяснить это оператору нечем."""
    foreign = _run(uuid4(), FITTED)
    tracks = (_track(UNSEEN),)

    with pytest.raises(NotFoundError):
        _ask(tracks, (foreign,), UNSEEN, foreign.uuid)

    with pytest.raises(NotFoundError):
        _ask(tracks, (foreign,), UNSEEN, uuid4())


def test_seed_curve_exists_before_any_fit() -> None:
    """`?fit=seed` — база сравнения первому прогону.

    Прогонов нет вовсе, и без этой ветки `_model` вернул бы `None`: сравнивать
    первый фит было бы не с чем, а «было / стало» читалось бы только числом.
    """
    tracks = (_track(UNSEEN),)

    assert _ask(tracks, (), UNSEEN).model is None, "без прогонов кривой быть не должно"

    response = _ask(tracks, (), UNSEEN, "seed")
    assert response.model is not None
    assert len(response.model.mjd) == FitSettings().MODEL_CURVE_POINTS
    assert response.model.t_ca is not None


def test_seed_curve_ignores_the_latest_run() -> None:
    """Затравка — это затравка, а не последний прогон.

    Элементы прогона сдвинуты по средней аномалии; кривая затравки обязана
    остаться на несдвинутых, иначе сравнивать прогон было бы с самим собой.
    """
    tracks = (_track(UNSEEN),)
    session_uuid = uuid4()
    run = _run(session_uuid, UNSEEN)
    moved = Elements.from_tle(run.tle.tle1, run.tle.tle2)
    moved = moved.with_vector(moved.to_vector() + np.array([0, 0, 0, 0, 2.0, 0, 0]))
    shifted = FitRun(**{**run.__dict__, "tle": to_tle(moved, run.tle)})

    seed_curve = _ask(tracks, (shifted,), UNSEEN, "seed").model
    fit_curve = _ask(tracks, (shifted,), UNSEEN).model

    assert seed_curve is not None and fit_curve is not None
    difference = max(
        abs(a - b) for a, b in zip(seed_curve.f_offset_hz, fit_curve.f_offset_hz)
    )
    assert difference > 100.0, "кривая затравки совпала с кривой прогона"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
