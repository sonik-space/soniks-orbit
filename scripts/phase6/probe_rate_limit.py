#!/usr/bin/env python3
"""Замер лимита частоты запросов боевого API — открытый вопрос 3.

    uv run python scripts/phase6/probe_rate_limit.py

Вопрос стоит открытым с фазы 0 и блокирует фазу 6: перебор масштаба каталога
и фоновая задача по наблюдениям — ровно та нагрузка, ради которой он заведён.

Конфигурация монолита уже прочитана (`network/settings.py`): глобального
`DEFAULT_THROTTLE_CLASSES` нет, троттлится единственный интересный нам
эндпоинт `/api/latesttles/` — `ScopedRateThrottle`, 60/мин, у анонимных
по IP. Остаётся непроверенным то, чего в репозитории монолита нет вовсе, —
слой nginx. Его видно только запросами.

Проба **только читает**. Ни один запрос ничего не меняет, водопад берётся
один и тот же, а срабатывание троттла на `/api/latesttles/` блокирует
на минуту этот эндпоинт и ничего больше.
"""

from __future__ import annotations

import argparse
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field

BASE = "https://sonik.space"
UNTHROTTLED = f"{BASE}/api/observations/?format=json"
THROTTLED = f"{BASE}/api/latesttles/?format=json&norad_cat_id=64880"

# Ступени: (подпись, запросов в секунду, длительность в секундах).
LADDER = (("1/с", 1.0, 10.0), ("5/с", 5.0, 10.0), ("10/с", 10.0, 10.0))

# Документированный лимит `latesttles` — 60/мин. Просим на один больше:
# если троттл живой, последний обязан вернуть 429.
THROTTLE_BURST = 61


@dataclass
class Probe:
    """Результат одной ступени."""

    label: str
    codes: Counter = field(default_factory=Counter)
    latencies: list[float] = field(default_factory=list)
    retry_after: str | None = None

    def percentile(self, q: float) -> float:
        if not self.latencies:
            return float("nan")
        ordered = sorted(self.latencies)
        return ordered[min(len(ordered) - 1, int(q * len(ordered)))]

    def row(self) -> str:
        codes = " ".join(f"{c}×{n}" for c, n in sorted(self.codes.items()))
        return (
            f"{self.label:12s} {sum(self.codes.values()):5d} "
            f"{codes:20s} {self.percentile(0.5):7.3f} {self.percentile(0.95):7.3f}"
        )


def fetch(url: str) -> tuple[int, float, str | None]:
    """Один GET. Возвращает (код, задержка в секундах, Retry-After)."""
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            response.read()
            return response.status, time.perf_counter() - started, None
    except urllib.error.HTTPError as error:
        error.read()
        return (
            error.code,
            time.perf_counter() - started,
            error.headers.get("Retry-After"),
        )
    except urllib.error.URLError:
        # Сетевой отказ — не код ответа, но и не повод бросать пробу.
        return 0, time.perf_counter() - started, None


def run_step(url: str, label: str, rate: float, seconds: float) -> Probe:
    """Держит заданный темп: запросы идут по расписанию, а не пачкой."""
    probe = Probe(label)
    period = 1.0 / rate
    deadline = time.perf_counter() + seconds
    slot = time.perf_counter()
    while slot < deadline:
        code, latency, retry_after = fetch(url)
        probe.codes[code] += 1
        probe.latencies.append(latency)
        if retry_after and probe.retry_after is None:
            probe.retry_after = retry_after
        slot += period
        pause = slot - time.perf_counter()
        if pause > 0:
            time.sleep(pause)
    return probe


def run_burst(url: str, label: str, count: int) -> Probe:
    """Подряд, без пауз: ищем границу окна, а не держим темп."""
    probe = Probe(label)
    for _ in range(count):
        code, latency, retry_after = fetch(url)
        probe.codes[code] += 1
        probe.latencies.append(latency)
        if retry_after and probe.retry_after is None:
            probe.retry_after = retry_after
        if code == 429:
            break
    return probe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-throttled",
        action="store_true",
        help="не трогать /api/latesttles/ (проба блокирует его на минуту)",
    )
    args = parser.parse_args()

    print(f"Боевой API: {BASE}\n")
    print(
        f"{'ступень':12s} {'запросов':>5s} {'коды':20s} {'p50, с':>7s} {'p95, с':>7s}"
    )

    probes = [run_step(UNTHROTTLED, label, rate, secs) for label, rate, secs in LADDER]

    if not args.skip_throttled:
        probes.append(run_burst(THROTTLED, f"{THROTTLE_BURST} подряд", THROTTLE_BURST))

    for probe in probes:
        print(probe.row())
        if probe.retry_after is not None:
            print(f"{'':12s} Retry-After: {probe.retry_after}")

    ladder = probes[: len(LADDER)]
    throttled_ladder = sum(p.codes[429] for p in ladder)
    print()
    if throttled_ladder:
        print(
            f"429 на нетроттлируемом пути: {throttled_ladder} — есть слой поверх Django"
        )
    else:
        print("429 на /api/observations/ нет: слоя поверх Django не обнаружено")

    if not args.skip_throttled:
        burst = probes[-1]
        if burst.codes[429]:
            fired_at = sum(burst.codes.values())
            print(
                f"/api/latesttles/ отдал 429 на запросе {fired_at} — троттл 60/мин живой"
            )
        else:
            print("/api/latesttles/ не отдал 429 — троттл не сработал, проверить ключ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
