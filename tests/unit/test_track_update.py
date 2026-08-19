"""Правка трека руками: `PUT .../track` и слияние при повторном извлечении.

Асинхронность гоняется через `asyncio.run`, чтобы не тащить `pytest-asyncio`
(правило 5: без фикстур и фреймворков сверх `pytest`).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from application.commands.session.update_track import UpdateTrackInteractor
from application.dtos.session import TrackPointsRequest, UpdateTrackRequest
from domain.exceptions import BadRequestError
from domain.models import ObservationTrack

CENTER_FREQ_HZ = 435973500.0
OBS = json.loads(
    (Path(__file__).parents[1] / "golden/waterfalls/obs_1527888.json").read_text()
)


class FakeRepo:
    def __init__(self, track: ObservationTrack | None) -> None:
        self._track = track
        self.saved: dict | None = None

    async def get_observation(self, *_: object) -> ObservationTrack | None:
        return self._track

    async def save_points(
        self, observation_uuid: UUID, *, points: dict, diagnostics: dict
    ) -> None:
        self.saved = {"points": points, "diagnostics": diagnostics}


class FakeTransaction:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


def _track(calibration: dict | None) -> ObservationTrack:
    return ObservationTrack(
        uuid=uuid4(),
        observation_id=1527888,
        meta=OBS,
        extraction_status="ok",
        calibration=calibration,
    )


def _request(**columns: list) -> UpdateTrackRequest:
    return UpdateTrackRequest(points=TrackPointsRequest(**columns))


def test_server_computes_absolute_frequency_itself() -> None:
    """`f_abs_hz` от клиента не принимается: он считается одной формулой ядра
    `received_freq_hz`, то есть `f_центра − f_смещение` (правило 9)."""
    repo = FakeRepo(_track({"center_freq_hz": CENTER_FREQ_HZ}))
    request = _request(
        mjd=[61268.44, 61268.45],
        f_offset_hz=[-8000.0, 8000.0],
        enabled=[True, True],
        source=["manual", "manual"],
        weight=[1.0, 1.0],
    )

    asyncio.run(UpdateTrackInteractor(repo, FakeTransaction())(uuid4(), 1527888, request))

    assert repo.saved is not None
    assert repo.saved["points"]["f_abs_hz"] == [
        CENTER_FREQ_HZ + 8000.0,
        CENTER_FREQ_HZ - 8000.0,
    ]
    assert repo.saved["points"]["snr"] == [0.0, 0.0]
    # Диагностика пересчитывается по новому набору, иначе RMS в списке
    # описывал бы набор, которого уже нет.
    assert repo.saved["diagnostics"]["rms_khz"] is not None


def test_empty_track_gets_no_numbers() -> None:
    """При пустом наборе диагностика — `null`, а не ноль: ноль читался бы
    как измеренное значение."""
    repo = FakeRepo(_track({"center_freq_hz": CENTER_FREQ_HZ}))

    asyncio.run(UpdateTrackInteractor(repo, FakeTransaction())(uuid4(), 1527888, _request()))

    assert repo.saved is not None
    diagnostics = repo.saved["diagnostics"]
    assert diagnostics["rms_khz"] is None
    assert diagnostics["carrier_hz"] is None
    assert diagnostics["margin"] is None


def test_without_calibration_it_refuses() -> None:
    """Центральная частота живёт в калибровке: в ответе Django её нет."""
    repo = FakeRepo(_track(None))

    with pytest.raises(BadRequestError):
        asyncio.run(
            UpdateTrackInteractor(repo, FakeTransaction())(uuid4(), 1527888, _request())
        )


def test_columns_of_different_length_are_rejected() -> None:
    with pytest.raises(ValueError, match="разной длины"):
        _request(
            mjd=[61268.44, 61268.45],
            f_offset_hz=[-8000.0],
            enabled=[True, True],
            source=["manual", "manual"],
            weight=[1.0, 1.0],
        )
