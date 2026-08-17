#!/usr/bin/env python3
"""Поиск наблюдений, пригодных для замера качества извлечения (число 2).

    uv run python scripts/phase0/scan_observations.py [--pages N] [--baud 9600]

Печатает таблицу id / бод / полоса / элевация / кадры и сводку.

Отбор осознанный, а не «первые попавшиеся»:

  - **`demoddata_count` больше порога.** Декодированные кадры означают, что
    сигнал реально принят и разобран, а не что человек увидел на картинке
    что-то похожее. Это самый сильный доступный признак пригодности,
    и он же самый дешёвый: счётчик лежит прямо в списке, поэтому отсев идёт
    до Range-запроса за метаданными PNG.
  - **Узкополосная телеметрия, 1200..9600 бод.** Наблюдения с широкой полосой
    (240 кГц) — это метеоспутники с APT/LRPT; раздел определения орбиты
    для них не предназначен, и мерить на них качество извлечения
    доплеровского гребня бессмысленно.
  - **Есть `satnogs:wf-dat`.** Без метаданных полоса невосстановима,
    наблюдение непригодно (algorithms.md §1.8).

Порядок проверок — от дешёвых к дорогим: счётчик кадров из списка,
затем передатчик (кешируется), и только потом первые килобайты PNG.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sonik_api import get_transmitter, iter_observations, peek_wf_dat  # noqa: E402

NARROWBAND_BAUD = (1200, 2400, 4800, 9600)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=8, help="страниц по 25 наблюдений")
    ap.add_argument("--baud", type=int, action="append", help="только эта скорость")
    ap.add_argument("--min-demod", type=int, default=15,
                    help="минимум декодированных кадров")
    ap.add_argument("--min-altitude", type=float, default=0.0)
    ap.add_argument("--end", default="2026-08-16T12:00:00Z",
                    help="ISO-время: наблюдения, закончившиеся не позже")
    ap.add_argument("--out", type=Path,
                    help="куда сложить отобранное JSON-ом: перебор долгий, "
                         "и терять его результат из-за обрезанного вывода обидно")
    args = ap.parse_args()
    bauds = tuple(args.baud) if args.baud else NARROWBAND_BAUD

    bands: collections.Counter[str] = collections.Counter()
    rows = []
    listed = no_meta = 0

    print(f"{'id':>8} {'бод':>5} {'полоса':>7} {'элев':>5} {'кадров':>7} "
          f"{'norad':>6}  спутник")
    print("-" * 72)

    for obs in iter_observations(pages=args.pages, end=args.end, status="good"):
        listed += 1
        if not obs.get("waterfall"):
            continue
        if (obs.get("demoddata_count") or 0) < args.min_demod:
            continue
        if (obs.get("max_altitude") or 0) < args.min_altitude:
            continue

        tx = get_transmitter(obs.get("transmitter") or "")
        baud = tx.get("baud") if tx else None
        if baud is None or int(baud) not in bauds:
            continue

        wf = peek_wf_dat(obs["waterfall"])
        if wf is None:
            no_meta += 1
            continue

        samp = int(float(wf["samp_rate"]))
        bands[str(samp)] += 1
        rows.append({"id": obs["id"], "baud": int(baud), "samp_rate": samp,
                     "max_altitude": obs.get("max_altitude") or 0.0,
                     "demoddata_count": obs.get("demoddata_count"),
                     "norad_cat_id": obs.get("norad_cat_id"),
                     "satellite": tx.get("satellite_name")})
        print(f"{obs['id']:>8} {int(baud):>5} {samp:>7} "
              f"{obs.get('max_altitude') or 0:>5.0f} "
              f"{obs.get('demoddata_count'):>7} {obs.get('norad_cat_id', '?'):>6}  "
              f"{tx.get('satellite_name')}")

    print("-" * 72)
    print(f"просмотрено {listed}, подошло {len(rows)}, "
          f"без метаданных {no_meta}")
    print(f"полосы: {dict(bands.most_common())}")
    per_baud = collections.Counter(r["baud"] for r in rows)
    print(f"по скоростям: {dict(sorted(per_baud.items()))}")
    if args.out:
        args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        print(f"отобранное записано в {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
