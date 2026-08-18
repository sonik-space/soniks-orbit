"""Перенос эпохи TLE. Заменяет `sattools/propagate`.

Задача: получить средние элементы SGP4 на новую эпоху так, чтобы модель
давала на ней то же положение и ту же скорость, что и исходная.

Прямой путь «прогнать SGP4 и снять кеплеровы элементы» неверен: снятые
элементы **оскулирующие**, а SGP4 принимает **средние**, и разница между
ними на LEO составляет километры. Поэтому разность гасится неподвижной
точкой (algorithms.md §5).
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from .constants import MU_KM3_S2
from .elements import Elements

# Насколько положение перенесённой модели вправе разойтись с исходной
# на целевой эпохе. Не подгоняемая ручка: перенос обязан воспроизводить
# состояние, и метр здесь — запас на численный шум, а не допуск.
MAX_TRANSFER_RESIDUAL_KM = 1e-3

_D2R = np.pi / 180.0
_R2D = 180.0 / np.pi
# Углы в векторе неподвижной точки: наклонение, RAAN и средняя долгота
# перигея `argp + M`. Сам `argp` и сама `M` в этот вектор не входят — почему,
# написано у `_nonsingular`.
_ANGLE_IDX = (0, 1, 4)


def classel(r_km: np.ndarray, v_km_s: np.ndarray, mjd: float, satno: int = 99999):
    """Оскулирующие кеплеровы элементы из положения и скорости, TEME.

    `n` возвращается в оборотах за сутки, углы — в градусах, как в `Elements`.
    """
    r = np.asarray(r_km, dtype=float)
    v = np.asarray(v_km_s, dtype=float)
    rr = float(np.linalg.norm(r))
    vv = float(np.linalg.norm(v))

    h = np.cross(r, v)
    hh = float(np.linalg.norm(h))

    incl = np.arccos(np.clip(h[2] / hh, -1.0, 1.0))
    raan = np.arctan2(h[0], -h[1])

    e_vec = ((vv * vv - MU_KM3_S2 / rr) * r - float(np.dot(r, v)) * v) / MU_KM3_S2
    ecc = float(np.linalg.norm(e_vec))

    a = 1.0 / (2.0 / rr - vv * vv / MU_KM3_S2)

    # Аргумент перигея и истинная аномалия — от линии узлов и от перигея
    # соответственно, обе через atan2, чтобы не терять квадрант.
    sin_i = np.sin(incl)
    if sin_i < 1e-12:  # экваториальная орбита: узел не определён
        raan = 0.0
        sin_i = 1e-12
    argp = np.arctan2(e_vec[2] / sin_i, e_vec[0] * np.cos(raan) + e_vec[1] * np.sin(raan))
    u = np.arctan2(r[2] / sin_i, r[0] * np.cos(raan) + r[1] * np.sin(raan))
    nu = u - argp

    # Средняя аномалия через эксцентрическую. При e → 0 argp и nu по
    # отдельности вырождаются, но их сумма — нет, и SGP4 потребляет именно её.
    ecc_c = min(ecc, 1.0 - 1e-12)
    ea = 2.0 * np.arctan2(
        np.sqrt(1.0 - ecc_c) * np.sin(0.5 * nu), np.sqrt(1.0 + ecc_c) * np.cos(0.5 * nu)
    )
    ma = ea - ecc_c * np.sin(ea)

    rev_per_day = 86400.0 / (2.0 * np.pi) * np.sqrt(MU_KM3_S2 / a**3)

    return Elements(
        incl_deg=float(incl * _R2D) % 360.0,
        raan_deg=float(raan * _R2D) % 360.0,
        ecc=ecc,
        argp_deg=float(argp * _R2D) % 360.0,
        ma_deg=float(ma * _R2D) % 360.0,
        rev_per_day=float(rev_per_day),
        bstar=0.0,
        epoch_mjd=mjd,
        satno=satno,
    )


def _state_at(elements: Elements, mjd: float) -> tuple[np.ndarray, np.ndarray]:
    """Положение и скорость SGP4 в TEME на заданный MJD."""
    err, r, v = elements.to_satrec().sgp4(mjd + 2400000.5, 0.0)
    if err != 0:
        raise ValueError(f"SGP4 вернул код ошибки {err} на MJD {mjd}")
    return np.array(r), np.array(v)


def _nonsingular(el: Elements) -> np.ndarray:
    """Вектор неподвижной точки в невырожденных координатах.

        [наклонение, RAAN, e·cos(argp), e·sin(argp), argp + M, n, B*]

    **Итерировать по `(e, argp, M)` нельзя.** Замер на прогоне 64880
    (`e = 6.1e-4`, `argp + M ≈ 0.1°`): сумма `argp + M` сходится с первого
    шага и дальше стоит намертво, а слагаемые расходятся ровно на ±43° за шаг
    в разные стороны, потому что по отдельности они при `e → 0` не определены.
    Приращение по ним не убывает никогда, критерий `max|delta| < tol`
    не срабатывает, цикл вырабатывает все 100 шагов и возвращает произвольную
    точку гребня. Заодно приращение по `e` уходит в минус, `with_vector`
    зажимает его нулём, и модель с `e = 0` больше не воспроизводит состояние:
    на этом прогоне ошибка составила **8.4 км**.

    Пара `(e·cos argp, e·sin argp)` определена и при нулевом эксцентриситете,
    знака не имеет и в зажим не упирается, а `argp + M` — та самая
    комбинация, которая наблюдаема. Ровно та же замена, по той же причине,
    уже сделана в приорах фита (`domain/od/fit.py`, decisions/004).
    """
    argp = el.argp_deg * _D2R
    return np.array(
        [
            el.incl_deg,
            el.raan_deg,
            el.ecc * np.cos(argp),
            el.ecc * np.sin(argp),
            (el.argp_deg + el.ma_deg) % 360.0,
            el.rev_per_day,
            el.bstar,
        ],
        dtype=float,
    )


def _from_nonsingular(vec: np.ndarray, template: Elements) -> Elements:
    """Обратно к `Elements`. Зажимы те же, что в `Elements.with_vector`."""
    k, h = float(vec[2]), float(vec[3])
    ecc = min(float(np.hypot(k, h)), 0.999)
    argp = float(np.arctan2(h, k)) * _R2D % 360.0
    return replace(
        template,
        incl_deg=float(vec[0]),
        raan_deg=float(vec[1]) % 360.0,
        ecc=ecc,
        argp_deg=argp,
        ma_deg=(float(vec[4]) - argp) % 360.0,
        rev_per_day=max(float(vec[5]), 0.05),
        bstar=float(vec[6]),
    )


def separation_km(a: Elements, b: Elements, mjd: float) -> float:
    """Расстояние между положениями двух наборов элементов на общий момент.

    Правильная проверка переноса эпохи — сравнение **состояния**, а не
    элементов: при `e ≈ 0` направления `argp` и `M` вырождены и расходятся
    поодиночке при неизменной сумме. Этим же числом порог публикации
    проверяет расхождение результата фита с затравкой (decisions/007).
    """
    r_a, _ = _state_at(a, mjd)
    r_b, _ = _state_at(b, mjd)
    return float(np.linalg.norm(r_a - r_b))


def reepoch(
    seed: Elements,
    target_mjd: float,
    max_iterations: int = 100,
    tol: float = 1e-10,
) -> Elements:
    """Средние элементы на новую эпоху.

    Неподвижная точка `orb ← orb + (orb0 − orb1)`, где `orb0` — оскулирующие
    элементы искомого состояния, а `orb1` — оскулирующие элементы того, что
    SGP4 выдаёт по текущему приближению.

    **Четырёх шагов, записанных в algorithms.md §5, не хватает.** Замер
    на `l10.tle`: сходимость геометрическая, множитель ≈0.6 за шаг, и после
    4 шагов положение расходится с целевым на 1.1 км при переносе на нулевой
    интервал и на 5.4 км при переносе на 10 суток. Нужный порядок — десятки
    шагов: 20 дают 0.4 м, 40 — микрометры. Шаг стоит один вызов SGP4,
    то есть микросекунды, поэтому цикл идёт до сходимости по приращению,
    а не фиксированное число раз.

    **Обёртка углов после каждого сложения обязательна.** Без неё разность
    вроде `0.1° − 359.9°` читается как −359.8° вместо +0.2°, и неподвижная
    точка расходится ровно вблизи нуля, то есть на каждой третьей орбите.

    `B*`, номер объекта и международное обозначение переносятся как есть:
    они не элементы движения, а паспорт объекта. `ndot`/`nddot` обнуляются —
    SGP4 их не использует.
    """
    r, v = _state_at(seed, target_mjd)
    orb0 = classel(r, v, target_mjd, seed.satno)
    target = _nonsingular(orb0)

    orb = orb0
    for _ in range(max_iterations):
        r1, v1 = _state_at(orb, target_mjd)
        orb1 = classel(r1, v1, target_mjd, seed.satno)

        delta = target - _nonsingular(orb1)
        delta[list(_ANGLE_IDX)] = (delta[list(_ANGLE_IDX)] + 180.0) % 360.0 - 180.0
        orb = _from_nonsingular(_nonsingular(orb) + delta, orb)
        if np.max(np.abs(delta)) < tol:
            break

    moved = Elements(
        incl_deg=orb.incl_deg,
        raan_deg=orb.raan_deg,
        ecc=orb.ecc,
        argp_deg=orb.argp_deg,
        ma_deg=orb.ma_deg,
        rev_per_day=orb.rev_per_day,
        bstar=seed.bstar,
        epoch_mjd=target_mjd,
        satno=seed.satno,
    )

    # Проверка **состояния**, а не приращения элементов: несошедшаяся
    # неподвижная точка уже один раз вернула молча 8.4 км (см. `_nonsingular`),
    # а результат отсюда уходит в каталог наведения всей сети (правило 11).
    # Порог на три порядка выше численного шума (тесты дают микрометры)
    # и на четыре ниже всего, что имеет смысл.
    residual_km = separation_km(seed, moved, target_mjd)
    if residual_km > MAX_TRANSFER_RESIDUAL_KM:
        raise ValueError(
            f"перенос эпохи не сошёлся: положение разошлось на {residual_km * 1000:.1f} м"
        )
    return moved
