"""Рамка осей, калибровка оси времени и отображение пикселя в частоту.

Формулы — algorithms.md §1.3-1.5.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from . import CalibrationError

# Признак линии осей: чёрные и ненасыщенные. Наивный поиск «тёмных пикселей»
# не работает — нижний конец любой colormap тоже тёмный (algorithms.md §1.3).
SPINE_MAX_LEVEL = 90
SPINE_MAX_CHROMA = 20
SPINE_COVERAGE = 0.6

COLORBAR_WIDTH_PX = (10, 60)

# Шаги, которые может выбрать `MinuteLocator` клиента.
NICE_TICK_MINUTES = (1, 2, 5, 10, 15, 30, 60)

# MJD полуночи 1970-01-01. Единственное место, где время из календаря
# переводится в MJD, поэтому константа живёт рядом с ним, а не в od/constants.py
# (там константы `rffit`, сверяемые с эталоном).
MJD_UNIX_EPOCH = 40587.0


@dataclass(frozen=True)
class AxesBox:
    """Рамка области графика и colorbar в пикселях, включительно."""

    left: int
    right: int
    top: int
    bottom: int
    cb_left: int
    cb_right: int

    @property
    def width(self) -> int:
        return self.right - self.left - 1

    @property
    def height(self) -> int:
        return self.bottom - self.top - 1


def spine_mask(rgb: np.ndarray) -> np.ndarray:
    """Маска ахроматичных тёмных пикселей — линий осей и делений."""
    mx = rgb.max(axis=2).astype(np.int16)
    mn = rgb.min(axis=2).astype(np.int16)
    return (mx < SPINE_MAX_LEVEL) & ((mx - mn) < SPINE_MAX_CHROMA)


def _run_centers(frac: np.ndarray, threshold: float = SPINE_COVERAGE) -> np.ndarray:
    """Центры непрерывных серий, где доля выше порога.

    Линия толщиной в 1-2 пикселя даёт серию, а не одиночный индекс, поэтому
    брать надо центр, иначе рамка съедет на полпикселя.
    """
    hit = frac > threshold
    if not hit.any():
        return np.array([], dtype=float)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], hit.view(np.int8), [0]))))
    starts, ends = edges[0::2], edges[1::2]
    return (starts + ends - 1) / 2.0


def detect_axes_box(rgb: np.ndarray) -> AxesBox:
    """Рамка осей и colorbar.

    Хардкодить координаты нельзя: `bbox_inches="tight"` в клиенте плюс
    оверлеи с `clip_on=False` двигают область графика от картинки к картинке
    (замерено 823×1603, 832×1603, 841×1676). Старый tabulation-helper
    хардкодил `(66,1553)-(686,13)` и на этом ошибался (правило 4).

    Пара границ графика — **соседняя** пара вертикальных линий с наибольшим
    разносом. Именно соседняя: на боевом водопаде колонки идут
    `[81, 681, 743, 763]`, и наибольший разнос по всем парам дал бы
    `(81, 763)`, то есть график вместе с colorbar. Соседние разносы
    `600 / 62 / 20` выбирают `(81, 681)` верно.
    """
    h, w = rgb.shape[:2]
    spine = spine_mask(rgb)

    cols = _run_centers(spine.sum(axis=0) / h)
    rows = _run_centers(spine.sum(axis=1) / w)
    if cols.size < 2 or rows.size < 2:
        raise CalibrationError(
            f"рамка осей не найдена: вертикальных линий {cols.size}, "
            f"горизонтальных {rows.size}"
        )

    gaps = np.diff(cols)
    k = int(np.argmax(gaps))
    left, right = int(round(cols[k])), int(round(cols[k + 1]))

    top, bottom = int(round(rows[0])), int(round(rows[-1]))

    cb_left = cb_right = -1
    right_cols = cols[k + 2 :]
    for a, b in zip(right_cols[:-1], right_cols[1:]):
        if COLORBAR_WIDTH_PX[0] <= (b - a) <= COLORBAR_WIDTH_PX[1]:
            cb_left, cb_right = int(round(a)), int(round(b))
            break
    if cb_left < 0:
        raise CalibrationError(
            "colorbar не найден правее области графика — без него неоткуда "
            "взять таблицу цветов, а угадывать colormap нельзя"
        )

    box = AxesBox(left, right, top, bottom, cb_left, cb_right)

    if box.width < 0.3 * w or box.height < 0.3 * h:
        raise CalibrationError(
            f"область графика {box.width}×{box.height} слишком мала "
            f"для картинки {w}×{h}"
        )
    interior = rgb[box.top + 1 : box.bottom, box.left + 1 : box.right]
    if (interior.min(axis=2) > 240).mean() > 0.9:
        raise CalibrationError("внутренность рамки почти белая — рендер не удался")
    return box


def detect_time_ticks(rgb: np.ndarray, box: AxesBox, reach: int = 5) -> np.ndarray:
    """Строки делений оси времени, в координатах изображения.

    Клиент ставит их `MinuteLocator(interval=INTERVAL_IN_MINUTES)`, то есть
    строго на целых минутах. Это единственный способ привязать ось времени:
    границы оси — метки первой и последней строки данных, а `tabs[0]`
    в метаданные PNG не попадает (algorithms.md §1.4).

    Полоса поиска узкая и вплотную к рамке. Деление у matplotlib длиной
    3.5 пункта, при 100 dpi это ~5 px, и стоит оно прямо у оси. Если брать
    полосу шире, доля размывается ниже порога (замер: при reach=10 деление
    даёт 0.4 и не находится ни одно), а ещё левее начинаются подписи времени,
    которые тоже чёрные и ахроматичные.
    """
    band = spine_mask(rgb)[:, max(box.left - reach, 0) : box.left]
    if band.size == 0:
        return np.array([], dtype=float)
    return _run_centers(band.mean(axis=1), threshold=0.5)


def tick_step_px(ticks: np.ndarray) -> float:
    """Шаг делений, выведенный из данных.

    Шаг **не** считается равным минуте: при длинном проходе `MinuteLocator`
    выбирает другой интервал. Медиана, а не среднее, чтобы одно случайно
    склеившееся деление не сдвинуло масштаб.
    """
    if ticks.size < 2:
        raise CalibrationError(f"делений оси времени {ticks.size}, нужно хотя бы два")
    return float(np.median(np.diff(ticks)))


def mjd_of(when: dt.datetime) -> float:
    return MJD_UNIX_EPOCH + when.timestamp() / 86400.0


def calibrate_time(
    ticks_img_rows: np.ndarray,
    box: AxesBox,
    t_ref: dt.datetime,
    duration_s: float,
) -> tuple[float, float]:
    """Время нижней строки области графика (MJD) и секунд на пиксель.

    Шаг делений выводится из данных, а не считается минутой: при длинном
    проходе `MinuteLocator` выбирает другой интервал. Абсолютная привязка
    следует из того, что деления стоят на целых минутах, а `t_ref` даёт
    оценку с точностью до `tabs[0]` (замер ≈0.28 с) — на фоне шага в минуту
    округление однозначно.
    """
    step_px = tick_step_px(ticks_img_rows)

    approx_sec_per_px = duration_s / box.height
    approx_interval_s = step_px * approx_sec_per_px
    interval_min = min(
        NICE_TICK_MINUTES, key=lambda m: abs(m * 60.0 - approx_interval_s)
    )
    sec_per_px = interval_min * 60.0 / step_px

    # Среднее деление: у него наименьшее плечо для ошибки масштаба.
    mid_row = float(np.median(ticks_img_rows))
    i_mid = (box.bottom - 1) - mid_row

    t_ref_mjd = mjd_of(t_ref)
    approx_mid_mjd = t_ref_mjd + i_mid * sec_per_px / 86400.0
    step_days = interval_min * 60.0 / 86400.0
    exact_mid_mjd = round(approx_mid_mjd / step_days) * step_days

    t_bottom_mjd = exact_mid_mjd - i_mid * sec_per_px / 86400.0
    return t_bottom_mjd, sec_per_px


def freq_offset_hz(j_px: np.ndarray, width_px: int, samp_rate: int, nchan: int):
    """Смещение частоты по столбцу области графика, Гц.

    `extent` задаёт внешние края нарисованного массива, а его границы —
    координаты центров первого и последнего канала, поэтому доля `u`
    переводится сперва в индекс канала, и только потом в частоту
    (algorithms.md §1.5).

    Ось несимметрична: клиент строит сетку с `endpoint=False`, поэтому
    верхний канал это `samp_rate/2 − bin_hz`, а не `+samp_rate/2`.
    Наивное симметричное `±samp_rate/2` дало бы постоянные +28 Гц.
    """
    bin_hz = samp_rate / nchan
    u = (np.asarray(j_px, dtype=float) + 0.5) / width_px
    return -samp_rate / 2.0 + (u * nchan - 0.5) * bin_hz
