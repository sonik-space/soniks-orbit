"""Три формы запроса эпохи дают один и тот же момент (api.md, фаза 5).

Форма `yyddd` — самая опасная из трёх: год двузначный, день года считается
от единицы, а не от нуля, и ошибка в сутки не видна ни в строке TLE,
ни в графике невязок — она всплывёт смещением наведения.
"""

from __future__ import annotations

import datetime as dt
from uuid import uuid4

import pytest

from application.dtos.publish import EpochRequest
from application.services.publishing import resolve_epoch_mjd
from domain.exceptions import BadRequestError
from domain.models import FitRun, ObservationTrack, OdSession, TleLines

SEED = TleLines(
    tle0="LOBACHEVSKY",
    tle1="1 98423U          26005.39163204  .00000000  00000-0  00000-0 0    07",
    tle2="2 98423  97.4103  80.5800 0016000 120.0000 240.0000 15.20900000    05",
)


def _run(observation_ids: list[int]) -> FitRun:
    return FitRun(
        uuid=uuid4(),
        session_uuid=uuid4(),
        created_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
        author_sub="sub",
        config={"observation_ids": observation_ids},
        elements_in={},
        elements_out={},
        tle=SEED,
        epoch_mjd=61045.0,
        rms_khz=0.42,
        rms_pre_khz=3.87,
        n_points=1240,
        per_observation=[],
        residuals={},
        prior_dominated=[],
        status="ok",
    )


def _session(ends: dict[int, str | None]) -> OdSession:
    return OdSession(
        uuid=uuid4(),
        name="сессия",
        norad_id=98423,
        owner_sub="sub",
        seed=SEED,
        seed_source="observation",
        status="fitted",
        observations=[
            ObservationTrack(
                uuid=uuid4(),
                observation_id=observation_id,
                meta={"end": end} if end else {},
                extraction_status="ok",
            )
            for observation_id, end in ends.items()
        ],
    )


def test_iso_and_yyddd_describe_the_same_instant() -> None:
    """`26005.391632037` — это 2026-01-05T09:23:57Z, пятый день года."""
    run, session = _run([1]), _session({1: "2026-01-05T09:28:00+00:00"})

    from_iso = resolve_epoch_mjd(
        EpochRequest(epoch_iso=dt.datetime(2026, 1, 5, 9, 23, 57, tzinfo=dt.UTC)),
        run,
        session,
    )
    from_yyddd = resolve_epoch_mjd(
        EpochRequest(epoch_yyddd="26005.391632037"), run, session
    )

    # Секунда в MJD это 1.16e-5, так что допуск здесь — доли секунды.
    assert from_yyddd == pytest.approx(from_iso, abs=1e-6)


def test_latest_observation_takes_the_maximum_within_the_run() -> None:
    """Наблюдение сессии, не попавшее в прогон, эпоху не двигает: иначе она
    уехала бы туда, где данных фита нет."""
    run = _run([1, 2])
    session = _session(
        {
            1: "2026-01-05T09:28:00+00:00",
            2: "2026-01-05T11:04:00+00:00",
            3: "2026-01-06T20:00:00+00:00",  # в прогоне не участвовало
        }
    )

    resolved = resolve_epoch_mjd(EpochRequest(epoch="latest_observation"), run, session)

    expected = resolve_epoch_mjd(
        EpochRequest(epoch_iso=dt.datetime(2026, 1, 5, 11, 4, tzinfo=dt.UTC)),
        run,
        session,
    )
    assert resolved == pytest.approx(expected, abs=1e-9)


def test_latest_observation_without_end_refuses() -> None:
    """Молча взять эпоху прогона было бы хуже: оператор попросил конец
    последнего прохода и не узнал бы, что получил не его."""
    with pytest.raises(BadRequestError):
        resolve_epoch_mjd(
            EpochRequest(epoch="latest_observation"), _run([1]), _session({1: None})
        )


@pytest.mark.parametrize(
    "payload",
    [{}, {"epoch": "latest_observation", "epoch_yyddd": "26005.391632037"}],
)
def test_exactly_one_field_is_required(payload: dict) -> None:
    with pytest.raises(ValueError):
        EpochRequest(**payload)
