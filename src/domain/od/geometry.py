"""Геометрия наблюдателя и лучевая скорость.

Зеркало `strf/rffit.c:1406-1512` (`velocity`, `obspos_xyz`, `gmst`, `dgmst`).
Совпадать должно до последней формулы, иначе регрессионный тест не сойдётся
(algorithms.md §3).

Единицы: время — MJD, углы на входе — градусы, длины — километры,
скорости — км/с.
"""

from __future__ import annotations

import numpy as np

from .constants import FLAT, XKMPER

_D2R = np.pi / 180.0


def gmst(mjd: np.ndarray | float) -> np.ndarray | float:
    """Среднее гринвичское звёздное время, градусы в [0, 360)."""
    t = (np.asarray(mjd, dtype=float) - 51544.5) / 36525.0
    g = 280.46061837 + 360.98564736629 * (np.asarray(mjd, dtype=float) - 51544.5)
    g = g + t * t * (0.000387933 - t / 38710000.0)
    return np.mod(g, 360.0)


def dgmst(mjd: np.ndarray | float) -> np.ndarray | float:
    """Скорость изменения gmst, градусов в сутки."""
    t = (np.asarray(mjd, dtype=float) - 51544.5) / 36525.0
    return 360.98564736629 + t * (0.000387933 - t / 38710000.0)


def obspos_xyz(
    mjd: np.ndarray,
    lat_deg: float,
    lng_deg: float,
    alt_km: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Положение и скорость наблюдателя в той же системе, что и SGP4.

    Возвращает два массива формы (N, 3) в км и км/с.

    **Высота в километрах.** Django API отдаёт метры, `sites.txt` strf — метры,
    но `rfsites.c` делит их на 1000 при чтении. Ошибка здесь даёт систематику,
    которую фит поглотит несущей и никто не заметит.
    """
    mjd = np.atleast_1d(np.asarray(mjd, dtype=float))

    sl = np.sin(lat_deg * _D2R)
    ff = np.sqrt(1.0 - FLAT * (2.0 - FLAT) * sl * sl)
    gc = 1.0 / ff + alt_km / XKMPER
    gs = (1.0 - FLAT) * (1.0 - FLAT) / ff + alt_km / XKMPER

    theta = (gmst(mjd) + lng_deg) * _D2R
    dtheta = dgmst(mjd) * _D2R / 86400.0  # рад/с

    cos_lat = np.cos(lat_deg * _D2R)
    pos = np.stack(
        [
            gc * cos_lat * np.cos(theta) * XKMPER,
            gc * cos_lat * np.sin(theta) * XKMPER,
            np.full_like(mjd, gs * sl * XKMPER),
        ],
        axis=-1,
    )
    vel = np.stack(
        [
            -gc * cos_lat * np.sin(theta) * XKMPER * dtheta,
            gc * cos_lat * np.cos(theta) * XKMPER * dtheta,
            np.zeros_like(mjd),
        ],
        axis=-1,
    )
    return pos, vel


def range_rate(
    satrec,
    mjd: np.ndarray,
    lat_deg: float,
    lng_deg: float,
    alt_km: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Лучевая скорость «наблюдатель → спутник», км/с.

    Положительная — спутник удаляется (частота ниже). Зеркало `velocity()`
    из `rffit.c:1406`.

    Возвращает `(v_km_s, err)`, где `err` — коды ошибок SGP4 по точкам.
    Разбираться с ними обязан вызывающий: молча подставленный NaN превратится
    в необъяснимую невязку.
    """
    mjd = np.atleast_1d(np.asarray(mjd, dtype=float))

    # Юлианская дата одним double, как `satpos_xyz(mjd+2400000.5, ...)`
    # в `rffit.c:1415`, а не разложенная на (jd, fr).
    #
    # Разложение точнее арифметически, но даёт время, отличающееся от того,
    # по которому считал эталон, примерно на 2e-5 с. При ускорении спутника
    # ~0.01 км/с² это ~2e-7 км/с — и ровно такое расхождение и наблюдалось.
    # С одним double согласие 5e-11 км/с. По доплеру цена вопроса меньше
    # милигерца, так что воспроизводимость важнее.
    jd = mjd + 2400000.5
    err, r, v = satrec.sgp4_array(jd, np.zeros_like(mjd))

    obspos, obsvel = obspos_xyz(mjd, lat_deg, lng_deg, alt_km)
    dx = np.asarray(r) - obspos
    dv = np.asarray(v) - obsvel
    rho = np.linalg.norm(dx, axis=-1)
    return np.einsum("ij,ij->i", dx, dv) / rho, np.asarray(err)
