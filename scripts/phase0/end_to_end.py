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

Замер вынесен в `measure()`, чтобы прогон по всему корпусу
(`scripts/phase1/sweep.py`) гонял ровно ту же цепочку, а не её копию.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from domain.od.constants import C_KM_S  # noqa: E402
from domain.od.doppler import fac as doppler_fac, received_freq_hz  # noqa: E402
from domain.od.elements import Elements  # noqa: E402
from domain.od.fit import profile_carrier, rms_khz  # noqa: E402
from domain.od.geometry import range_rate  # noqa: E402
from domain.waterfall.axes import (  # noqa: E402
    calibrate_time,
    detect_axes_box,
    detect_time_ticks,
    freq_offset_hz,
    tick_step_px,
)
from domain.waterfall.colormap import decode_intensity, lut_from_colorbar  # noqa: E402
from domain.waterfall.metadata import WaterfallMeta, parse_iso  # noqa: E402
from domain.waterfall.ridge import dc_mask, extract_ridge, peak_width_limits_px  # noqa: E402
from sonik_api import get_observation, get_waterfall  # noqa: E402

# Минимальный размах частоты трека. Доплер за проход на 435 МГц проходит
# 16 кГц даже на низкой элевации (замер на 1527888, 22°), а стационарная
# помеха — доли килогерца. Порог отсекает вторую, не задевая первый.
MIN_TRACK_SPAN_HZ = 2000.0

# Как смещение на водопаде связано с принятой частотой.
#
# Две независимые двоичные неизвестные: велась ли доплеровская коррекция при
# записи и в какую сторону растёт ось частот. Ни та, ни другая из метаданных
# не выводится, поэтому обе **измеряются** по самим данным — выигрывает
# вариант с наименьшим RMS, и запас до следующего печатается.
#
# Замер по корпусу (`scripts/phase1/sweep.py`) выигрывает «сырой, ось
# инвертирована» на всех извлечённых наблюдениях восьми станций, поэтому
# именно он лежит в ядре как `received_freq_hz`. Перебор остаётся здесь
# диагностикой: маленький запас означает, что трек ненадёжен.
AXIS_MODELS = {
    "сырой, ось прямая": lambda cf, fo, v: cf + fo,
    "сырой, ось инвертирована": lambda cf, fo, v: received_freq_hz(cf, fo),
    "доплер снят, ось прямая": lambda cf, fo, v: cf + fo - cf * v / C_KM_S,
    "доплер снят, ось инвертирована": lambda cf, fo, v: cf - fo - cf * v / C_KM_S,
}


def load_waterfall(path: Path) -> tuple[np.ndarray, WaterfallMeta]:
    """PNG → массив RGB и калибровка. Единственное место с PIL (правило 1)."""
    img = Image.open(path)
    return np.asarray(img.convert("RGB")), WaterfallMeta.from_png_text(img.info)


def measure(
    observation_id: int, *, snr_threshold: float = 4.0, bin_seconds: float = 1.0
) -> dict:
    """То же, что `measure_waterfall`, но данные берутся из боевого API и кеша."""
    obs = get_observation(observation_id)
    rgb, meta = load_waterfall(get_waterfall(obs))
    return measure_waterfall(
        rgb, meta, obs, snr_threshold=snr_threshold, bin_seconds=bin_seconds
    )


def measure_waterfall(
    rgb: np.ndarray,
    meta: WaterfallMeta,
    obs: dict,
    *,
    snr_threshold: float = 4.0,
    bin_seconds: float = 1.0,
) -> dict:
    """Вся цепочка на одном наблюдении. Диагностика — словарём, печать снаружи.

    Ввода-вывода здесь нет намеренно: этой же функцией гоняются golden-тесты
    по закоммиченным PNG, без сети и без кеша.

    Ключ `points` равен нулю, если извлечение ничего не нашло: это нормальное
    состояние, а не ошибка (decisions/001), поэтому исключения тут нет.
    """
    box = detect_axes_box(rgb)
    ticks = detect_time_ticks(rgb, box)
    lut = lut_from_colorbar(rgb, box)
    z, overlay = decode_intensity(rgb, box, lut)

    start, end = parse_iso(obs["start"]), parse_iso(obs["end"])
    t_bottom_mjd, sec_per_px = calibrate_time(
        ticks, box, meta.t_ref, (end - start).total_seconds()
    )

    limits = peak_width_limits_px(
        box.width, meta.nchan, meta.samp_rate_hz, meta.bw_99_hz
    )
    ridge = extract_ridge(
        z,
        bin_rows=max(int(round(bin_seconds / sec_per_px)), 1),
        width_limits_px=limits,
        dc_cols=dc_mask(box.width, meta.samp_rate_hz, meta.nchan),
        snr_threshold=snr_threshold,
        chain_min_span_px=MIN_TRACK_SPAN_HZ * box.width / meta.samp_rate_hz,
    )

    out = {
        "obs": obs,
        "meta": meta,
        "box": box,
        "shape": rgb.shape,
        "ticks": ticks,
        "lut_len": len(lut),
        "overlay_frac": float(overlay.mean()),
        "sec_per_px": sec_per_px,
        "width_limits_px": limits,
        "points": int(ridge.row_px.size),
        "ridge": ridge,
    }
    if ridge.row_px.size == 0:
        return out

    mjd = t_bottom_mjd + ridge.row_px * sec_per_px / 86400.0
    f_offset_hz_track = freq_offset_hz(
        ridge.col_px, box.width, meta.samp_rate_hz, meta.nchan
    )

    tle = obs["tle"]
    seed = Elements.from_tle(tle["tle1"], tle["tle2"])
    v_km_s, err = range_rate(
        seed.to_satrec(),
        mjd,
        float(obs["station_lat"]),
        float(obs["station_lng"]),
        float(obs["station_alt"]) / 1000.0,  # API отдаёт метры, ядро ждёт км
    )
    if np.any(err != 0):
        out["sgp4_errors"] = int(np.sum(err != 0))
        return out

    fac = doppler_fac(v_km_s)
    scored = []
    for name, model in AXIS_MODELS.items():
        f_abs = model(meta.center_freq_hz, f_offset_hz_track, v_km_s)
        carrier = profile_carrier(fac, f_abs / 1000.0, ridge.weight)
        scored.append((rms_khz(f_abs / 1000.0 - fac * carrier), name, carrier))
    scored.sort()
    rms, convention, carrier_khz = scored[0]

    out.update(
        {
            "mjd": mjd,
            "f_offset_hz": f_offset_hz_track,
            "v_km_s": v_km_s,
            "rms_khz": rms,
            "convention": convention,
            "margin": scored[1][0] / rms if rms > 0 else float("inf"),
            "carrier_khz": carrier_khz,
            "age_days": float(mjd.mean() - seed.epoch_mjd),
        }
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("observation_id", type=int)
    ap.add_argument("--snr", type=float, default=4.0)
    ap.add_argument("--bin-seconds", type=float, default=1.0)
    args = ap.parse_args()

    r = measure(
        args.observation_id, snr_threshold=args.snr, bin_seconds=args.bin_seconds
    )
    obs, meta, box, ridge = r["obs"], r["meta"], r["box"], r["ridge"]

    if r["points"] == 0:
        print("извлечение ничего не нашло — это нормальное состояние, "
              "а не ошибка (decisions/001)")
        return 2
    if "sgp4_errors" in r:
        print(f"SGP4 вернул коды ошибок на {r['sgp4_errors']} точках")
        return 3

    tle = obs["tle"]
    print(f"наблюдение   {obs['id']}  norad {obs.get('norad_cat_id')}  "
          f"{obs.get('station_name')}  элевация {obs.get('max_altitude')}°")
    print(f"картинка     {r['shape'][1]}×{r['shape'][0]}, рамка "
          f"[{box.left},{box.right}]×[{box.top},{box.bottom}], "
          f"colorbar [{box.cb_left},{box.cb_right}]")
    print(f"калибровка   полоса {meta.samp_rate_hz} Гц, {meta.bin_hz:.2f} Гц/канал, "
          f"{meta.samp_rate_hz / box.width:.1f} Гц/пиксель")
    print(f"деления      {r['ticks'].size} шт, шаг {tick_step_px(r['ticks']):.1f} px "
          f"(разброс {np.std(np.diff(r['ticks'])):.2f}), "
          f"{r['sec_per_px']:.4f} с/пиксель")
    print(f"colorbar     {r['lut_len']} записей, оверлеев "
          f"{100 * r['overlay_frac']:.2f}% пикселей")
    print(f"трек         {r['points']} точек, SNR "
          f"{ridge.snr.min():.1f}..{ridge.snr.max():.1f}, "
          f"ширина пика {r['width_limits_px'][0]:.1f}.."
          f"{r['width_limits_px'][1]:.1f} px")
    print(f"TLE          {tle.get('tle_source', '?')}, возраст "
          f"{r['age_days']:.2f} сут, {tle['tle0'].strip()}")
    print(f"несущая      {r['carrier_khz'] * 1000:.1f} Гц, "
          f"{r['carrier_khz'] * 1000 - meta.center_freq_hz:+.1f} Гц от центра")
    print(f"конвенция    {r['convention']} (лучше следующей в {r['margin']:.0f} раз)")
    if r["margin"] < 2.0:
        print("             ВНИМАНИЕ: варианты неразличимы, трек ненадёжен")
    print()
    rms = r["rms_khz"]
    verdict = (
        "ПОРОГ ПРОЙДЕН" if rms < 0.5
        else "ХУЖЕ 1 кГц" if rms > 1.0
        else "между 0.5 и 1 кГц"
    )
    print(f"RMS          {rms:.4f} кГц   {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
