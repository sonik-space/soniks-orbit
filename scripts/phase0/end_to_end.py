#!/usr/bin/env python3
"""Число go/no-go №2: качество извлечения трека из пикселей PNG.

    uv run python scripts/phase0/end_to_end.py <observation_id>

Цепочка целиком: JSON из боевого API → PNG → рамка осей → калибровка времени
по делениям → LUT из colorbar → гребень → снятие доплер-коррекции по TLE
наблюдения → профилирование несущей → RMS.

**Орбитального фита нет.** Профилируется только несущая, элементы не двигаются.
Поэтому одно число разом валидирует разбор метаданных, детекцию рамки,
калибровку по делениям, отображение пиксель → (время, частота) и поиск гребня:
если TLE наблюдения заведомо хорошее, весь остаток невязки — это ошибки
извлечения (testing.md §2).

Порог фазы 0 — RMS < 0.5 кГц. Хуже 1 кГц — условие возврата к отложенному
решению decisions/011.

Сама цепочка живёт в `application/services/extraction.py` — единственном
разрешённом месте сшивки (правило 8). Здесь остались только ввод-вывод
и печать, чтобы стенд мерил ровно то, что считает боевой код.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from cache import get_observation, load_waterfall

from application.services.extraction import Extraction, extract_track
from domain.waterfall.axes import tick_step_px


def measure(
    observation_id: int, *, snr_threshold: float = 4.0, bin_seconds: float = 1.0
) -> Extraction:
    """Извлечение по одному наблюдению из боевого API и дискового кеша."""
    obs = get_observation(observation_id)
    rgb, meta = load_waterfall(obs)
    return extract_track(
        rgb, meta, obs, snr_threshold=snr_threshold, bin_seconds=bin_seconds
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("observation_id", type=int)
    ap.add_argument("--snr", type=float, default=4.0)
    ap.add_argument("--bin-seconds", type=float, default=1.0)
    args = ap.parse_args()

    r = measure(
        args.observation_id, snr_threshold=args.snr, bin_seconds=args.bin_seconds
    )
    obs = get_observation(args.observation_id)
    meta, box, ridge = r.meta, r.box, r.ridge

    if r.ridge.row_px.size == 0:
        print(
            "извлечение ничего не нашло — это нормальное состояние, "
            "а не ошибка (decisions/001)"
        )
        return 2
    if r.sgp4_errors:
        print(f"SGP4 вернул коды ошибок на {r.sgp4_errors} точках")
        return 3

    tle = obs["tle"]
    print(
        f"наблюдение   {obs['id']}  norad {obs.get('norad_cat_id')}  "
        f"{obs.get('station_name')}  элевация {obs.get('max_altitude')}°"
    )
    print(
        f"картинка     {r.shape[1]}×{r.shape[0]}, рамка "
        f"[{box.left},{box.right}]×[{box.top},{box.bottom}], "
        f"colorbar [{box.cb_left},{box.cb_right}]"
    )
    print(
        f"калибровка   полоса {meta.samp_rate_hz} Гц, {meta.bin_hz:.2f} Гц/канал, "
        f"{meta.samp_rate_hz / box.width:.1f} Гц/пиксель"
    )
    print(
        f"деления      {r.ticks.size} шт, шаг {tick_step_px(r.ticks):.1f} px "
        f"(разброс {np.std(np.diff(r.ticks)):.2f}), "
        f"{r.calibration.sec_per_px:.4f} с/пиксель"
    )
    print(
        f"colorbar     {r.lut_len} записей, оверлеев "
        f"{100 * r.overlay_frac:.2f}% пикселей"
    )
    print(
        f"трек         {len(r.points)} точек, SNR "
        f"{ridge.snr.min():.1f}..{ridge.snr.max():.1f}, "
        f"ширина пика {r.width_limits_px[0]:.1f}.."
        f"{r.width_limits_px[1]:.1f} px"
    )
    print(
        f"TLE          {tle.get('tle_source', '?')}, возраст "
        f"{r.age_days:.2f} сут, {tle['tle0'].strip()}"
    )
    print(
        f"несущая      {r.carrier_hz:.1f} Гц, "
        f"{r.carrier_hz - meta.center_freq_hz:+.1f} Гц от центра"
    )
    print(f"конвенция    {r.convention} (лучше следующей в {r.margin:.0f} раз)")
    if not r.reliable:
        print("             ВНИМАНИЕ: варианты неразличимы, трек ненадёжен")
    print()
    verdict = (
        "ПОРОГ ПРОЙДЕН"
        if r.rms_khz < 0.5
        else "ХУЖЕ 1 кГц"
        if r.rms_khz > 1.0
        else "между 0.5 и 1 кГц"
    )
    print(f"RMS          {r.rms_khz:.4f} кГц   {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
