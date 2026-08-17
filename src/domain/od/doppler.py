"""Доплер первого порядка.

Клиент станции ведёт приёмник по предсказанию из опорного TLE, поэтому по оси
частот водопада отложен не сам доплер, а **остаток**. Чтобы получить
абсолютную принятую частоту, коррекцию нужно вернуть обратно (algorithms.md §3).
"""

from __future__ import annotations

import numpy as np

from .constants import C_KM_S


def fac(v_km_s: np.ndarray | float) -> np.ndarray | float:
    """Доплеровский множитель `1 − v/c`. Удаляется (`v > 0`) — частота ниже."""
    return 1.0 - np.asarray(v_km_s, dtype=float) / C_KM_S


def undo_doppler(
    center_freq_hz: float,
    f_offset_hz: np.ndarray,
    v_km_s: np.ndarray,
) -> np.ndarray:
    """Абсолютная принятая частота из смещения на водопаде, Гц.

        f_abs = f_центра + f_смещение(t) − f_центра · v_r(t)/c

    `v_r` считается по TLE, которое было у наблюдения **в момент записи**:
    именно по нему клиент вёл приёмник. Поэтому снимок ответа API
    замораживается (правило 10).
    """
    return center_freq_hz + np.asarray(f_offset_hz, dtype=float) - center_freq_hz * (
        np.asarray(v_km_s, dtype=float) / C_KM_S
    )
