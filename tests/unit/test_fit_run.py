"""Прогон фита: защита, невязки индекс-в-индекс и воспроизводимость.

Асинхронность гоняется через `asyncio.run`, чтобы не тащить `pytest-asyncio`
(правило 5: без фикстур и фреймворков сверх `pytest`).

Треки синтетические, но геометрия настоящая: времена, станция и TLE берутся
из замороженных снимков `tests/golden/waterfalls/`, а частота считается тем же
доплеровским множителем, что и в ядре. Два наблюдения — два прохода одного
объекта 64880 с разных времён, то есть ровно тот случай, ради которого
несущая своя на каждое наблюдение.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest

from application.commands.fit.create import RunFitInteractor
from application.dtos.fit import PriorSigmasSchema, RunFitRequest
from core.configs.fit import FitSettings
from domain.exceptions import BadRequestError
from domain.models import FitRun, ObservationTrack, OdSession, TleLines
from domain.od.doppler import fac as doppler_fac
from domain.od.elements import Elements
from domain.od.geometry import range_rate
from domain.od.tle import to_lines

GOLDEN = Path(__file__).parents[1] / "golden/waterfalls"
MJD_UNIX_EPOCH = 40587.0
CARRIER_HZ = 435975000.0


def _mjd(iso: str) -> float:
    return dt.datetime.fromisoformat(iso).timestamp() / 86400.0 + MJD_UNIX_EPOCH


def _track(
    observation_id: int, n: int = 40, disabled: tuple[int, ...] = ()
) -> ObservationTrack:
    """Наблюдение с треком, лежащим точно на его собственном TLE."""
    meta = json.loads((GOLDEN / f"obs_{observation_id}.json").read_text())
    start, end = _mjd(meta["start"]), _mjd(meta["end"])
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

    return ObservationTrack(
        uuid=uuid4(),
        observation_id=observation_id,
        meta=meta,
        extraction_status="ok",
        calibration={"center_freq_hz": meta["observation_frequency"]},
        points={
            "mjd": mjd.tolist(),
            "f_abs_hz": f_abs_hz.tolist(),
            "f_offset_hz": (meta["observation_frequency"] - f_abs_hz).tolist(),
            "snr": [10.0] * n,
            "weight": [1.0] * n,
            "enabled": [i not in disabled for i in range(n)],
            "source": ["auto"] * n,
        },
    )


def _session(*tracks: ObservationTrack, ma_shift_deg: float = 0.0) -> OdSession:
    """Сессия с затравкой из снимка первого наблюдения.

    `ma_shift_deg` сдвигает среднюю аномалию затравки: синтетический трек лежит
    точно на своём TLE, и без сдвига фиту нечего делать — он сходится на первом
    же вычислении невязок.
    """
    meta = tracks[0].meta
    tle = meta["tle"]
    if ma_shift_deg:
        seed = Elements.from_tle(tle["tle1"], tle["tle2"])
        vector = seed.to_vector()
        vector[4] += ma_shift_deg
        line1, line2 = to_lines(seed.with_vector(vector))
        tle = {"tle0": tle["tle0"], "tle1": line1, "tle2": line2}
    return OdSession(
        uuid=uuid4(),
        name="проверка фита",
        norad_id=meta["norad_cat_id"],
        owner_sub="sub",
        seed=TleLines(tle0=tle["tle0"], tle1=tle["tle1"], tle2=tle["tle2"]),
        seed_source="observation",
        status="draft",
        observations=list(tracks),
    )


class FakeSessionRepo:
    def __init__(self, session: OdSession) -> None:
        self._session = session
        self.status: str | None = None

    async def get(self, session_uuid: UUID) -> OdSession:
        return self._session

    async def set_status(self, session_uuid: UUID, status: str) -> None:
        self.status = status


class FakeFitRepo:
    def __init__(self) -> None:
        self.saved: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> FitRun:
        self.saved = kwargs
        return FitRun(
            uuid=uuid4(),
            created_at=dt.datetime.now(tz=dt.UTC),
            **kwargs,
        )


class FakeTransaction:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


def _run(session: OdSession, request: RunFitRequest | None = None, **overrides):
    repo = FakeSessionRepo(session)
    fit_repo = FakeFitRepo()
    transaction = FakeTransaction()
    interactor = RunFitInteractor(repo, fit_repo, transaction, FitSettings(**overrides))
    run = asyncio.run(interactor(session.uuid, request or RunFitRequest(), "sub"))
    return run, repo, fit_repo, transaction


def test_one_observation_is_refused() -> None:
    """Из одного прохода наблюдаемы примерно две величины: фит по нему даёт
    правдоподобный RMS при бессмысленных элементах (algorithms.md §4.4)."""
    with pytest.raises(BadRequestError, match="наблюдений с точками 1"):
        _run(_session(_track(1527888)))


def test_too_few_enabled_points_are_refused() -> None:
    """Погашенные человеком точки в фит не идут, и защита считает именно
    включённые."""
    tracks = (_track(1527888, n=12, disabled=(0, 1, 2)), _track(1526972, n=8))
    with pytest.raises(BadRequestError, match="включённых точек 17"):
        _run(_session(*tracks))


def test_residuals_are_index_aligned_with_points() -> None:
    """`residuals` индекс-в-индекс соответствует `points` того же наблюдения:
    выделение в панели невязок и на водопаде — один и тот же ключ
    `${obsId}:${idx}`."""
    disabled = (3, 7, 11)
    tracks = (_track(1527888, disabled=disabled), _track(1526972))
    _, _, fit_repo, _ = _run(_session(*tracks))

    assert fit_repo.saved is not None
    block = fit_repo.saved["residuals"]["1527888"]
    points = tracks[0].points

    assert len(block["residual_khz"]) == len(points["mjd"])
    assert block["mjd"] == points["mjd"]
    missing = {i for i, v in enumerate(block["residual_khz"]) if v is None}
    assert missing == set(disabled), "null стоит не ровно на погашенных точках"
    assert fit_repo.saved["n_points"] == 40 - len(disabled) + 40


def test_failed_run_still_carries_elements_and_residuals() -> None:
    """Несошедшийся прогон сохраняется со статусом `failed`, но с последними
    элементами и невязками — иначе в UI не видно, что пошло не так."""
    run, repo, _fit_repo, transaction = _run(
        _session(_track(1527888), _track(1526972), ma_shift_deg=2.0), MAX_NFEV=1
    )

    assert run.status == "failed"
    assert run.elements_out["inclination_deg"] > 0
    assert run.residuals["1527888"]["residual_khz"][0] is not None
    # Статус сессии на неудачном прогоне не трогается.
    assert repo.status is None
    assert transaction.committed


def test_request_knobs_reach_the_saved_run() -> None:
    """σ и `f_scale` — калибровочные ручки: без них в прогоне опубликованное
    TLE невоспроизводимо (algorithms.md §4.3)."""
    request = RunFitRequest(
        prior_sigmas=PriorSigmasSchema(eccentricity=0.02, argp_plus_m_deg=1.5),
        f_scale=0.25,
    )
    run, repo, _, _ = _run(_session(_track(1527888), _track(1526972)), request)

    config = run.config
    assert config["f_scale"] == 0.25
    assert config["prior_sigmas"]["eccentricity"] == 0.02
    assert config["prior_sigmas"]["argp_plus_m_deg"] == 1.5
    # Незаданное берётся из конфигурации, а не обнуляется.
    assert config["prior_sigmas"]["inclination_deg"] == FitSettings().INCLINATION_DEG
    assert config["observation_ids"] == [1526972, 1527888]
    assert repo.status == "fitted"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
