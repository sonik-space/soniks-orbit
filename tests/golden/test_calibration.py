"""Калибровка водопада на реальных водопадах (testing.md §2).

Восемь боевых PNG с закоммиченным ответом API. Сети не требуется: и картинка,
и снимок наблюдения лежат рядом, как они и будут лежать в
`od_session_observations.meta` (правило 10).

Раньше здесь проверялся ещё и автоматически найденный трек — число точек, RMS
и конвенция. Эти проверки сняты вместе с автоизвлечением (decisions/015):
измерять было нечего, потому что мерился трек, садившийся на помеху. Осталось
то, что и было настоящим барьером и от человека не зависит: рамка осей
и деления времени. Сломается разметка водопада в клиенте — сломаются они,
и это единственное, что способно молча испортить уже поставленные точки.

Ожидания лежат в `calibration.json` и правятся **только осознанно, отдельным
коммитом с объяснением** (правило 5): обновление golden ради зелёного CI —
это удаление теста.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from application.services.calibration import Calibrated, calibrate_observation
from domain.waterfall.axes import tick_step_px
from infrastructure.images.loader import decode

HERE = Path(__file__).parent
WATERFALLS = HERE / "waterfalls"
GOLDEN = json.loads((HERE / "calibration.json").read_text(encoding="utf-8"))


def _calibrate(observation_id: str) -> Calibrated:
    rgb, meta = decode(WATERFALLS / f"wf_{observation_id}.png")
    obs = json.loads(
        (WATERFALLS / f"obs_{observation_id}.json").read_text(encoding="utf-8")
    )
    return calibrate_observation(rgb, meta, obs)


@pytest.fixture(scope="module", params=sorted(GOLDEN))
def case(request) -> tuple[Calibrated, dict]:
    return _calibrate(request.param), GOLDEN[request.param]


def test_axes_box_is_exact(case) -> None:
    """Рамка — единственное, что обязано совпадать до пикселя: она детектируется,
    а не считается, и именно она ломается от правок вёрстки в клиенте."""
    got, want = case
    box = got.box
    assert [box.left, box.right, box.top, box.bottom] == want["box"]
    assert [box.cb_left, box.cb_right] == want["colorbar"]
    assert list(got.shape[:2]) == want["shape"]


def test_time_ticks_are_evenly_spaced(case) -> None:
    """Деления стоят на целых минутах, поэтому шаг обязан быть равномерным
    с точностью до полупикселя — центр серии из 1-2 пикселей иначе не выразить.
    Разброс больше означает, что в узкую полосу поиска попало что-то ещё:
    подпись времени, край рамки, оверлей."""
    got, want = case
    ticks = got.ticks
    assert ticks.size == want["ticks"]
    assert tick_step_px(ticks) == pytest.approx(want["tick_step_px"], abs=0.05)
    assert np.std(np.diff(ticks)) <= 0.5


def test_axes_map_pixels_to_data(case) -> None:
    """Отображение пиксель ↔ (время, смещение) — то, во что превращается клик
    человека. Проверяются края: нижняя строка это начало наблюдения, а шаг
    по времени восстанавливает его длительность."""
    got, _ = case
    c = got.calibration
    assert c.plot_w > 0 and c.plot_h > 0
    assert c.sec_per_px > 0
    assert c.f_min_hz == -c.samp_rate_hz / 2.0
    assert c.f_max_hz == pytest.approx(c.samp_rate_hz / 2.0 - c.bin_hz)
    # Полная высота области графика обязана покрывать наблюдение целиком:
    # иначе часть прохода будет невозможно разметить.
    assert (c.plot_h - 1) * c.sec_per_px > 60.0
