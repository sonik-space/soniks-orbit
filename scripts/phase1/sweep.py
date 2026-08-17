#!/usr/bin/env python3
"""Прогон извлечения по всему закешированному корпусу.

    uv run python scripts/phase1/sweep.py [observation_id ...]

Без аргументов берёт все наблюдения, у которых в `scripts/phase0/cache/`
лежит PNG, то есть сети не требует.

Зачем: открытые вопросы 9 и 10 закрываются замером по корпусу, а не по одному
наблюдению. Одиночный `end_to_end.py` отвечает на вопрос «правильно ли
извлекается эталон», а этот стенд — на вопросы «на скольких наблюдениях
извлечение вообще срабатывает» и «одинакова ли конвенция оси частот
у разных станций».

Гейт для любой правки поиска гребня: RMS на 1527888 не хуже 0.0250 кГц
**и** покрытие строго выше записанного. Оба числа печатаются в подвале.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "phase0"))
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from cache import CACHE, get_observation  # noqa: E402
from end_to_end import measure  # noqa: E402

REFERENCE_ID = 1527888
REFERENCE_RMS_KHZ = 0.0250
C_KM_S = 299792.458


def cached_ids() -> list[int]:
    return sorted(
        int(re.search(r"\d+", p.name).group()) for p in CACHE.glob("wf_*.png")
    )


def signal_tag(meta) -> str:
    """Короткая метка модуляции из `satnogs:wf-signal` для таблицы."""
    if meta.modulation.startswith("2-FSK"):
        return f"2FSK{meta.deviation_hz / 1000:.1f}" if meta.deviation_hz else "2FSK"
    if meta.modulation.startswith("narrowband"):
        return "nbdig"
    return meta.modulation[:7] or "—"


def axis_regression(result) -> tuple[float, float]:
    """Коэффициент регрессии `f_offset` на предсказанный доплер и R².

    Открытый вопрос 9: если ось частот инвертирована у всей сети, коэффициент
    везде близок к −1; если это свойство станции, он разделился бы по станциям.
    Предсказанный доплер берётся на центральной частоте наблюдения, поэтому
    коэффициент безразмерный и сравним между наблюдениями.
    """
    f_offset = result.points.f_offset_hz
    doppler_hz = -result.meta.center_freq_hz * result.v_km_s / C_KM_S
    k, b = np.polyfit(doppler_hz, f_offset, 1)
    resid = f_offset - (k * doppler_hz + b)
    total = f_offset - f_offset.mean()
    r2 = 1.0 - float(np.sum(resid**2) / np.sum(total**2))
    return float(k), r2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("observation_id", type=int, nargs="*")
    ap.add_argument("--snr", type=float, default=4.0)
    ap.add_argument("--bin-seconds", type=float, default=1.0)
    args = ap.parse_args()

    ids = args.observation_id or cached_ids()

    print(f"{'наблюдение':>10} {'ст':>4} {'сигнал':>7} {'точек':>6} {'RMS,кГц':>8} "
          f"{'запас':>6} {'k':>7} {'R²':>6}  конвенция")
    print("-" * 90)

    ok = 0
    reference_rms = None
    for oid in ids:
        try:
            r = measure(oid, snr_threshold=args.snr, bin_seconds=args.bin_seconds)
        except Exception as exc:  # непригодное наблюдение — строка, а не падение
            print(f"{oid:>10} {'':>4} {'':>5} {'—':>6}   {type(exc).__name__}: {exc}")
            continue

        station = get_observation(oid).get("ground_station")
        tag = signal_tag(r.meta)
        if r.sgp4_errors:
            print(f"{oid:>10} {station:>4} {tag:>7} {'—':>6}   "
                  f"SGP4: ошибок {r.sgp4_errors}")
            continue
        if len(r.points) == 0:
            print(f"{oid:>10} {station:>4} {tag:>7} {'—':>6}   пусто")
            continue

        ok += 1
        if oid == REFERENCE_ID:
            reference_rms = r.rms_khz
        k, r2 = axis_regression(r)
        print(f"{oid:>10} {station:>4} {tag:>7} {len(r.points):>6} "
              f"{r.rms_khz:>8.4f} {min(r.margin, 9999):>6.0f} "
              f"{k:>7.3f} {r2:>6.3f}  {r.convention}")

    print("-" * 88)
    print(f"покрытие {ok} из {len(ids)}")
    if reference_rms is None:
        print(f"эталон {REFERENCE_ID} не прогонялся — гейт не проверен")
        return 0
    verdict = "не хуже" if reference_rms <= REFERENCE_RMS_KHZ + 5e-5 else "ХУЖЕ"
    print(f"эталон {REFERENCE_ID}: {reference_rms:.4f} кГц, "
          f"{verdict} записанных {REFERENCE_RMS_KHZ:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
