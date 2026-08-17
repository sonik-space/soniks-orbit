"""Извлечение трека на реальных водопадах (testing.md §2).

Восемь боевых PNG с закоммиченным ответом API. Сети не требуется: и картинка,
и снимок наблюдения лежат рядом, как они и будут лежать в
`od_session_observations.meta` (правило 10).

Набор подобран по случаям, а не по красоте: одиночная несущая, плотная
гребёнка 2-FSK на обеих запасных ступенях, слабый проход со стационарной
помехой, полоса 240 кГц, `weak/noise` без `deviation_hz` и картинка другого
размера. Ожидания лежат в `extraction.json` и правятся **только осознанно,
отдельным коммитом с объяснением** (правило 5): обновление golden ради
зелёного CI — это удаление теста.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from domain.waterfall.axes import tick_step_px
from end_to_end import measure_waterfall
from domain.waterfall.metadata import WaterfallMeta

HERE = Path(__file__).parent
WATERFALLS = HERE / "waterfalls"
GOLDEN = json.loads((HERE / "extraction.json").read_text(encoding="utf-8"))


def _measure(observation_id: str) -> dict:
    img = Image.open(WATERFALLS / f"wf_{observation_id}.png")
    obs = json.loads(
        (WATERFALLS / f"obs_{observation_id}.json").read_text(encoding="utf-8")
    )
    return measure_waterfall(
        np.asarray(img.convert("RGB")), WaterfallMeta.from_png_text(img.info), obs
    )


@pytest.fixture(scope="module", params=sorted(GOLDEN))
def case(request) -> tuple[dict, dict]:
    return _measure(request.param), GOLDEN[request.param]


def test_axes_box_is_exact(case) -> None:
    """Рамка — единственное, что обязано совпадать до пикселя: она детектируется,
    а не считается, и именно она ломается от правок вёрстки в клиенте."""
    got, want = case
    box = got["box"]
    assert [box.left, box.right, box.top, box.bottom] == want["box"]
    assert [box.cb_left, box.cb_right] == want["colorbar"]
    assert list(got["shape"][:2]) == want["shape"]


def test_time_ticks_are_evenly_spaced(case) -> None:
    """Деления стоят на целых минутах, поэтому шаг обязан быть равномерным
    с точностью до полупикселя — центр серии из 1-2 пикселей иначе не выразить.
    Разброс больше означает, что в узкую полосу поиска попало что-то ещё:
    подпись времени, край рамки, оверлей."""
    got, want = case
    ticks = got["ticks"]
    assert ticks.size == want["ticks"]
    assert tick_step_px(ticks) == pytest.approx(want["tick_step_px"], abs=0.05)
    assert np.std(np.diff(ticks)) <= 0.5


def test_colorbar_lut(case) -> None:
    got, want = case
    assert got["lut_len"] == want["lut_len"]
    assert got["overlay_frac"] == pytest.approx(want["overlay_frac"], abs=0.002)


def test_track_length(case) -> None:
    """±20% по числу точек: точное число зависит от отсева по 3σ, но обвал
    вдвое означает, что сломался поиск гребня."""
    got, want = case
    if want["points"] == 0:
        assert got["points"] == 0, "здесь трека быть не должно"
        return
    assert got["points"] == pytest.approx(want["points"], rel=0.2)


def test_rms_against_the_observation_tle(case) -> None:
    """Самая сильная одиночная проверка: трек обязан лечь на TLE наблюдения
    **без орбитального фита**, профилируется только несущая. Одно число разом
    валидирует метаданные, рамку, калибровку по делениям, отображение
    пиксель → (время, частота), снятие доплера и поиск гребня."""
    got, want = case
    if want["points"] == 0:
        return
    assert got["convention"] == want["convention"]
    assert got["rms_khz"] == pytest.approx(want["rms_khz"], rel=0.1)
    assert got["margin"] >= want["margin_at_least"]


def test_reference_observation_holds_its_number() -> None:
    """Порог фазы 0 и гейт для любой правки поиска гребня.

    0.0250 кГц на 1527888 — то число, которым закрыт go/no-go №2. Оно
    проверяется отдельно и жёстко: относительный допуск остальных случаев
    здесь недопустим, потому что именно этот замер разрешает не возвращаться
    к decisions/011.
    """
    got = _measure("1527888")
    assert got["rms_khz"] < 0.0251
    assert got["margin"] > 200
