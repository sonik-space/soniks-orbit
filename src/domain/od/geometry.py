"""Геометрия наблюдателя: лучевая скорость, азимут, высота, момент сближения.

Зеркало `strf/rffit.c:1406-1512` (`velocity`, `obspos_xyz`, `gmst`, `dgmst`)
и `rffit.c:1615-1625` (`equatorial2horizontal`).
Совпадать должно до последней формулы, иначе регрессионный тест не сойдётся
(algorithms.md §3).

Единицы: время — MJD, углы на входе — градусы, длины — километры,
скорости — км/с.
"""

from __future__ import annotations

import numpy as np

from .constants import FLAT, XKMPER

_D2R = np.pi / 180.0
_R2D = 180.0 / np.pi


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


def equatorial2horizontal(
    mjd: np.ndarray,
    lat_deg: float,
    lng_deg: float,
    ra_deg: np.ndarray,
    de_deg: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Экваториальные координаты в горизонтальные. Зеркало `rffit.c:1615`.

    Возвращает `(az_deg, alt_deg)`: азимут от севера через восток в [0, 360),
    высота над горизонтом в [-90, 90].
    """
    h = gmst(mjd) + lng_deg - ra_deg
    sin_lat, cos_lat = np.sin(lat_deg * _D2R), np.cos(lat_deg * _D2R)

    az = np.mod(
        np.arctan2(
            np.sin(h * _D2R),
            np.cos(h * _D2R) * sin_lat - np.tan(de_deg * _D2R) * cos_lat,
        )
        * _R2D,
        360.0,
    )
    alt = (
        np.arcsin(
            sin_lat * np.sin(de_deg * _D2R)
            + cos_lat * np.cos(de_deg * _D2R) * np.cos(h * _D2R)
        )
        * _R2D
    )
    return az, alt


def topocentric(
    satrec,
    mjd: np.ndarray,
    lat_deg: float,
    lng_deg: float,
    alt_km: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Всё, что даёт одна прогонка SGP4: `(v_km_s, az_deg, alt_deg, err)`.

    Зеркало `velocity()` из `rffit.c:1406` целиком, включая азимут и высоту,
    которые там считаются той же арифметикой `dx` и в том же вызове.
    Вторая копия этой арифметики ради «отдельной функции для панели неба» —
    ровно то место, куда проникает ошибка единиц (правило 2), поэтому точка
    вызова SGP4 здесь одна, а `range_rate` — тонкая обёртка над ней.

    `err` — коды ошибок SGP4 по точкам. Разбираться с ними обязан вызывающий:
    молча подставленный NaN превратится в необъяснимую невязку.
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

    v_km_s = np.einsum("ij,ij->i", dx, dv) / rho
    ra = np.mod(np.arctan2(dx[:, 1], dx[:, 0]) * _R2D, 360.0)
    de = np.arcsin(dx[:, 2] / rho) * _R2D
    az, alt = equatorial2horizontal(mjd, lat_deg, lng_deg, ra, de)
    return v_km_s, az, alt, np.asarray(err)


def range_rate(
    satrec,
    mjd: np.ndarray,
    lat_deg: float,
    lng_deg: float,
    alt_km: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Лучевая скорость «наблюдатель → спутник», км/с.

    Положительная — спутник удаляется (частота ниже). Отдельное имя, потому
    что фит, скрининг и ступени 1–4 лестницы горизонтальные координаты
    не используют, а читаются с ним короче.
    """
    v_km_s, _, _, err = topocentric(satrec, mjd, lat_deg, lng_deg, alt_km)
    return v_km_s, err


def tca_mjd(mjd: np.ndarray, v_km_s: np.ndarray, alt_deg: np.ndarray) -> float | None:
    """Момент наибольшего сближения: нуль лучевой скорости над горизонтом.

    `rffit.c:501-505` берёт ближайший из 1024 отсчётов сетки, здесь нуль
    интерполируется линейно — при шаге сетки в десятки секунд это разница
    того же порядка. Смена знака берётся **последняя** в окне, как там же
    (`mjdtca` перезаписывается в цикле): в наборе из нескольких проходов
    метка ставится на последний.

    `None`, если над горизонтом скорость знака не меняет.
    """
    sign = np.signbit(v_km_s)
    crossings = np.flatnonzero((sign[:-1] != sign[1:]) & (alt_deg[1:] > 0.0))
    if crossings.size == 0:
        return None
    i = int(crossings[-1])
    v0, v1 = float(v_km_s[i]), float(v_km_s[i + 1])
    return float(mjd[i]) + (float(mjd[i + 1]) - float(mjd[i])) * v0 / (v0 - v1)
