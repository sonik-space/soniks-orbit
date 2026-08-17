"""Таблица цветов из colorbar и монотонный прокси мощности.

Формулы — algorithms.md §1.6.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from . import CalibrationError
from .axes import AxesBox

# Расстояние в RGB, дальше которого пиксель считается оверлеем, а не данными.
OVERLAY_DISTANCE = 30.0


def lut_from_colorbar(rgb: np.ndarray, box: AxesBox) -> np.ndarray:
    """Таблица цветов из самого изображения, индекс 0 — минимум мощности.

    Ключевая находка: colorbar на картинке — это точная таблица, поэтому
    не нужно знать ни имя colormap, ни параметры `PowerNorm`. Хардкодить
    colormap нельзя категорически: в исходнике клиента стоит `jet`, а замер
    на боевом водопаде давал viridis.

    Поиску гребня нужен только **монотонный** прокси мощности, и он
    получается по построению — по положению в таблице.
    """
    strip = rgb[box.top + 1 : box.bottom, box.cb_left + 1 : box.cb_right]
    if strip.size == 0:
        raise CalibrationError("colorbar пуст")
    lut = strip.mean(axis=1)[::-1].astype(float)  # снизу вверх = от минимума
    if len(np.unique(lut.round(0), axis=0)) < 16:
        raise CalibrationError(
            f"в colorbar всего {len(np.unique(lut.round(0), axis=0))} различных "
            f"цветов — на таблицу не похоже"
        )
    return lut


def decode_intensity(
    rgb: np.ndarray, box: AxesBox, lut: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Монотонный прокси мощности в [0,1] и маска оверлеев.

    Расстояние до ближайшей записи таблицы бесплатно детектирует оверлеи —
    маркеры декодированных кадров, аннотацию девиации, кривые мешающих
    спутников: их цвета в таблице нет.
    """
    interior = rgb[box.top + 1 : box.bottom, box.left + 1 : box.right].astype(float)
    h, w = interior.shape[:2]
    dist, idx = cKDTree(lut).query(interior.reshape(-1, 3))
    z = (idx / (len(lut) - 1)).reshape(h, w)
    overlay = (dist > OVERLAY_DISTANCE).reshape(h, w)
    z = np.where(overlay, np.nan, z)
    return z[::-1], overlay[::-1]  # origin='lower': время снизу вверх
