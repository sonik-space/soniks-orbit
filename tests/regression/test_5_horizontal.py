"""Ступень 5 лестницы: горизонтальные координаты и момент сближения.

Изолирует `equatorial2horizontal` и `tca_mjd` — всё остальное к этому моменту
уже проверено ступенями 1–4. Азимут и высота приходят из той же прогонки SGP4,
что и лучевая скорость (`topocentric`), поэтому если ступень 1 зелёная,
а эта красная — виновата формула перевода, и больше ничего.

Про TCA формулировка утвердительная: `rffit` берёт ближайший из 1024 отсчётов
сетки, мы интерполируем нуль. Тест требует, чтобы мы попадали в пределах
одного шага их сетки **и** чтобы модуль лучевой скорости в нашем моменте был
не больше, чем в их. То есть мы обязаны быть не хуже, а не «совпадать
с точностью до шага».
"""

from __future__ import annotations

import numpy as np

from domain.od.elements import Elements
from domain.od.geometry import tca_mjd, topocentric

TOL_DEG = 1e-6


def _wrap180(delta: np.ndarray) -> np.ndarray:
    """Разница азимутов: 359.9999° и 0.0001° отстоят на 0.0002°, а не на 360."""
    return np.abs((delta + 180.0) % 360.0 - 180.0)


def test_horizontal_matches_c(golden: dict, seed: Elements, capsys) -> None:
    sites = sorted({int(s) for s in golden["site_id"]})
    d_az = np.empty_like(golden["mjd"])
    d_el = np.empty_like(golden["mjd"])

    sat = seed.to_satrec()
    for site in sites:
        m = golden["site_id"] == site
        _, az, el, err = topocentric(
            sat,
            golden["mjd"][m],
            float(golden["lat_deg"][m][0]),
            float(golden["lng_deg"][m][0]),
            float(golden["alt_km"][m][0]),
        )
        assert np.all(err == 0), f"SGP4 вернул код ошибки на станции {site}"
        d_az[m] = _wrap180(az - golden["az_deg"][m])
        d_el[m] = np.abs(el - golden["el_deg"][m])

    with capsys.disabled():
        print(
            f"\n  {golden['dat'].split('/')[-1]} {golden['free_params']}: "
            f"азимут до {d_az.max():.3e}°, высота до {d_el.max():.3e}°"
        )

    assert d_el.max() < TOL_DEG, f"высота разошлась на {d_el.max():.3e}°"
    assert d_az.max() < TOL_DEG, f"азимут разошёлся на {d_az.max():.3e}°"


def test_tca_is_not_worse(golden: dict, seed: Elements, capsys) -> None:
    grid = golden["grid"]
    mjd = np.linspace(grid["mjd_min"], grid["mjd_max"], grid["n"])
    step = (grid["mjd_max"] - grid["mjd_min"]) / (grid["n"] - 1)

    sat = seed.to_satrec()
    for block in golden["tca"]:
        if block["mjd"] is None:
            continue  # проход целиком вне окна данных: сравнивать не с чем
        site = block["site_id"]
        m = golden["site_id"] == site

        lat = float(golden["lat_deg"][m][0])
        lng = float(golden["lng_deg"][m][0])
        alt_km = float(golden["alt_km"][m][0])

        v, _, el, err = topocentric(sat, mjd, lat, lng, alt_km)
        assert np.all(err == 0), f"SGP4 вернул код ошибки на станции {site}"

        # Окно данных, как в условии `mjd<d.mjdmax && mjd>d.mjdmin` (rffit.c:502):
        # без него метка может уехать на соседний проход, которого в данных нет.
        window = (mjd > golden["mjd"].min()) & (mjd < golden["mjd"].max())
        ours = tca_mjd(mjd, v, np.where(window, el, -90.0))
        assert ours is not None, f"на станции {site} нуль скорости не найден"

        v_ours = float(topocentric(sat, np.array([ours]), lat, lng, alt_km)[0][0])
        v_theirs = float(
            topocentric(sat, np.array([block["mjd"]]), lat, lng, alt_km)[0][0]
        )

        with capsys.disabled():
            print(
                f"\n  станция {site}: TCA на {abs(ours - block['mjd']) / step:.3f} "
                f"шага сетки от эталона, |v| {abs(v_ours):.3e} против "
                f"{abs(v_theirs):.3e} км/с"
            )

        assert abs(ours - block["mjd"]) < step, (
            f"станция {site}: наш TCA отстоит от эталонного на "
            f"{abs(ours - block['mjd']) / step:.2f} шага сетки"
        )
        assert abs(v_ours) <= abs(v_theirs), (
            f"станция {site}: интерполяция дала |v| = {abs(v_ours):.3e} км/с, "
            f"хуже ближайшего отсчёта эталона {abs(v_theirs):.3e}"
        )
