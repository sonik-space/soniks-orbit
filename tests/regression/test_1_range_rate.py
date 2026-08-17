"""Ступень 1 лестницы: лучевая скорость против эталона.

Изолирует SGP4, положение наблюдателя, GMST и единицы высоты станции —
и ничего больше. Пока эта ступень красная, идти к несущей и фиту бессмысленно:
расхождение, найденное сразу на уровне фита, неотлаживаемо (правило 3).

Допуск 1e-6 км/с. Расхождение до ~1e-5 объяснимо и ожидаемо: `strf/sgdp4.c` —
более старый порт SGP4, чем `python-sgp4` (Vallado 2006). Больше — это наша
ошибка, и чинить её надо здесь.
"""

from __future__ import annotations

import numpy as np

from domain.od.elements import Elements
from domain.od.geometry import obspos_xyz, range_rate

TOL_KM_S = 1e-6


def test_site_positions_are_finite_and_on_earth(golden: dict) -> None:
    """Сначала станции: если разошлись они, дальше идти незачем.

    Ловит перепутанные метры и километры — самую вероятную ошибку в этом
    месте (правило 2). Радиус наблюдателя обязан лежать в пределах пары
    десятков километров от земного.
    """
    for site in {int(s) for s in golden["site_id"]}:
        m = golden["site_id"] == site
        pos, vel = obspos_xyz(
            golden["mjd"][m],
            float(golden["lat_deg"][m][0]),
            float(golden["lng_deg"][m][0]),
            float(golden["alt_km"][m][0]),
        )
        r = np.linalg.norm(pos, axis=-1)
        assert np.all(np.isfinite(pos)) and np.all(np.isfinite(vel))
        assert np.all((r > 6350.0) & (r < 6390.0)), (
            f"станция {site}: радиус {r.min():.3f}..{r.max():.3f} км. "
            f"Похоже на высоту в метрах вместо километров."
        )
        # Скорость вращения Земли на экваторе ~0.465 км/с, на полюсе 0.
        assert np.all(np.linalg.norm(vel, axis=-1) < 0.47)


def test_range_rate_matches_c(golden: dict, seed: Elements) -> None:
    sat = seed.to_satrec()

    got = np.empty_like(golden["v_km_s"])
    for site in {int(s) for s in golden["site_id"]}:
        m = golden["site_id"] == site
        v, err = range_rate(
            sat,
            golden["mjd"][m],
            float(golden["lat_deg"][m][0]),
            float(golden["lng_deg"][m][0]),
            float(golden["alt_km"][m][0]),
        )
        assert np.all(err == 0), f"SGP4 вернул код ошибки на станции {site}"
        got[m] = v

    d = np.abs(got - golden["v_km_s"])
    assert d.max() < TOL_KM_S, (
        f"максимальное расхождение {d.max():.3e} км/с при допуске {TOL_KM_S:.0e}. "
        f"Медиана {np.median(d):.3e}. Если разброс похож на постоянное смещение — "
        f"ищите положение наблюдателя или GMST; если растёт со временем — SGP4."
    )
