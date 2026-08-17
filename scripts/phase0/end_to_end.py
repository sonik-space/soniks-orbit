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
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from domain.od.doppler import fac as doppler_fac  # noqa: E402

from domain.od.elements import Elements  # noqa: E402
from domain.od.fit import profile_carrier, rms_khz  # noqa: E402
from domain.od.geometry import range_rate  # noqa: E402
from sonik_api import get_observation, get_waterfall  # noqa: E402
from waterfall_extract import (  # noqa: E402
    CalibrationError,
    dc_mask,
    decode_intensity,
    detect_axes_box,
    detect_time_ticks,
    extract_ridge,
    freq_offset_hz,
    lut_from_colorbar,
    peak_width_limits_px,
    tick_step_px,
)

MJD_UNIX_EPOCH = 40587.0
NICE_TICK_MINUTES = (1, 2, 5, 10, 15, 30, 60)
C_KM_S = 299792.458

# Как смещение на водопаде связано с принятой частотой.
#
# algorithms.md §3 предполагает ровно один вариант: клиент ведёт приёмник
# по предсказанию, поэтому на оси отложен остаток, и доплер возвращается
# формулой `f = cf + fo − cf·v/c`. Замер этого не подтвердил: на наблюдении
# 1527888 смещение проходит полную S-кривую размахом 16314 Гц при размахе
# сырого доплера 16343 Гц (отношение 1.00, то есть коррекции не было),
# причём с обратным знаком.
#
# Отсюда две независимые двоичные неизвестные — велась ли коррекция при
# записи и в какую сторону растёт ось частот. Это свойство приёмного тракта
# станции, а не число, которое можно вывести из метаданных, поэтому оно
# **измеряется** по самим данным: выигрывает вариант с наименьшим RMS.
# Отношение 1.00 по размаху заодно исключает вариант «коррекция с неверным
# знаком», который дал бы двойной размах.
AXIS_MODELS = {
    "сырой, ось прямая": lambda cf, fo, v: cf + fo,
    "сырой, ось инвертирована": lambda cf, fo, v: cf - fo,
    "доплер снят, ось прямая": lambda cf, fo, v: cf + fo - cf * v / C_KM_S,
    "доплер снят, ось инвертирована": lambda cf, fo, v: cf - fo - cf * v / C_KM_S,
}


def load_waterfall(path: Path) -> tuple[np.ndarray, dict, dict]:
    """PNG → массив RGB и метаданные. Единственное место с PIL (правило 1).

    Отсутствие `satnogs:wf-dat` — **громкий отказ**, а не догадка о полосе.
    Эвристика `48e3` из старого инструмента (в комментарии честно помеченная
    «very bad heuristic») давала правдоподобный неверный результат, а поле
    `satnogs_rx_samp_rate` станции через API не отдаётся, так что взять полосу
    больше неоткуда (algorithms.md §1.1).
    """
    img = Image.open(path)
    raw = img.info.get("satnogs:wf-dat")
    if not raw:
        raise CalibrationError(
            f"{path.name}: нет satnogs:wf-dat. Наблюдение непригодно — станция "
            f"на клиенте старше 2.2.x, полоса невосстановима."
        )
    signal = json.loads(img.info.get("satnogs:wf-signal", "{}"))
    return np.asarray(img.convert("RGB")), json.loads(raw), signal


def mjd_of(when: dt.datetime) -> float:
    return MJD_UNIX_EPOCH + when.timestamp() / 86400.0


def parse_iso(text: str) -> dt.datetime:
    """Устойчивый разбор меток: доли секунды бывают и не бывают (правило 4)."""
    text = text.strip().replace("Z", "+00:00")
    stamp = dt.datetime.fromisoformat(text)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def calibrate_time(
    ticks_img_rows: np.ndarray, box, t_ref: dt.datetime, duration_s: float
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("observation_id", type=int)
    ap.add_argument("--snr", type=float, default=4.0)
    ap.add_argument("--bin-seconds", type=float, default=1.0)
    args = ap.parse_args()

    obs = get_observation(args.observation_id)
    rgb, wf, signal = load_waterfall(get_waterfall(obs))

    samp_rate = int(float(wf["samp_rate"]))
    nchan = int(wf["nchan"])
    center_freq_hz = float(wf["center_freq"])
    bin_hz = samp_rate / nchan

    box = detect_axes_box(rgb)
    ticks = detect_time_ticks(rgb, box)
    lut = lut_from_colorbar(rgb, box)
    z, overlay = decode_intensity(rgb, box, lut)

    start, end = parse_iso(obs["start"]), parse_iso(obs["end"])
    t_bottom_mjd, sec_per_px = calibrate_time(
        ticks, box, parse_iso(wf["timestamp"]), (end - start).total_seconds()
    )

    limits = peak_width_limits_px(
        box.width, nchan, samp_rate, signal.get("bw_99_hz")
    )
    ridge = extract_ridge(
        z,
        bin_rows=max(int(round(args.bin_seconds / sec_per_px)), 1),
        width_limits_px=limits,
        dc_cols=dc_mask(box.width, samp_rate, nchan),
        snr_threshold=args.snr,
    )
    if ridge.row_px.size == 0:
        print("извлечение ничего не нашло — это нормальное состояние, "
              "а не ошибка (decisions/001)")
        return 2

    mjd = t_bottom_mjd + ridge.row_px * sec_per_px / 86400.0
    f_offset = freq_offset_hz(ridge.col_px, box.width, samp_rate, nchan)

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
        print(f"SGP4 вернул коды ошибок на {int(np.sum(err != 0))} точках")
        return 3

    fac = doppler_fac(v_km_s)
    scored = []
    for name, model in AXIS_MODELS.items():
        f_abs = model(center_freq_hz, f_offset, v_km_s)
        carrier = profile_carrier(fac, f_abs / 1000.0, ridge.weight)
        scored.append((rms_khz(f_abs / 1000.0 - fac * carrier), name, carrier))
    scored.sort()
    rms, convention, carrier_khz = scored[0]
    margin = scored[1][0] / rms if rms > 0 else float("inf")

    age_days = mjd.mean() - seed.epoch_mjd
    print(f"наблюдение   {obs['id']}  norad {obs.get('norad_cat_id')}  "
          f"{obs.get('station_name')}  элевация {obs.get('max_altitude')}°")
    print(f"картинка     {rgb.shape[1]}×{rgb.shape[0]}, рамка "
          f"[{box.left},{box.right}]×[{box.top},{box.bottom}], "
          f"colorbar [{box.cb_left},{box.cb_right}]")
    print(f"калибровка   полоса {samp_rate} Гц, {bin_hz:.2f} Гц/канал, "
          f"{samp_rate / box.width:.1f} Гц/пиксель")
    print(f"деления      {ticks.size} шт, шаг {tick_step_px(ticks):.1f} px "
          f"(разброс {np.std(np.diff(ticks)):.2f}), {sec_per_px:.4f} с/пиксель")
    print(f"colorbar     {len(lut)} записей, оверлеев "
          f"{100 * overlay.mean():.2f}% пикселей")
    print(f"трек         {ridge.row_px.size} точек, SNR "
          f"{ridge.snr.min():.1f}..{ridge.snr.max():.1f}, "
          f"ширина пика {limits[0]:.1f}..{limits[1]:.1f} px")
    print(f"TLE          {tle.get('tle_source', '?')}, возраст "
          f"{age_days:.2f} сут, {tle['tle0'].strip()}")
    print(f"несущая      {carrier_khz * 1000:.1f} Гц, "
          f"{carrier_khz * 1000 - center_freq_hz:+.1f} Гц от центра")
    print(f"конвенция    {convention} (лучше следующей в {margin:.0f} раз)")
    if margin < 2.0:
        print("             ВНИМАНИЕ: варианты неразличимы, трек ненадёжен")
    print()
    verdict = (
        "ПОРОГ ПРОЙДЕН" if rms < 0.5
        else "ХУЖЕ 1 кГц" if rms > 1.0
        else "между 0.5 и 1 кГц"
    )
    print(f"RMS          {rms:.4f} кГц   {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
