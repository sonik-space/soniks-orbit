#!/usr/bin/env python3
"""Выгрузка эталонной разметки человека из сессии в файлы `truth/`.

    uv run python scripts/phase1/pull_truth.py <session_uuid>

Размечают в UI (`/orbit`), а стенд сравнения читает файлы: эталон должен
переживать снос кеша и работать офлайн, как и весь остальной стенд фазы 1.

Файл — снимок разметки, а не её история: повторный запуск перетирает его
целиком. Правят в UI, выгружают сюда. Времени выгрузки в файле нет намеренно:
иначе каждый прогон давал бы новый диф и `git diff` перестал бы показывать,
менялась ли сама разметка. Когда выгружено, знает git.

`f_abs_hz` в эталон не пишется намеренно. Абсолютная частота — это уже
применённая конвенция оси (`received_freq_hz`), а конвенция под подозрением
ровно в том же замере, ради которого эталон и собирается. Эталон содержит
только пиксельно-наблюдаемое: время и смещение от центра.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

TRUTH = Path(__file__).parent / "truth"
BASE = "http://127.0.0.1:8000/api/v1"


def pull(client: httpx.Client, base: str, uuid: str, note: str) -> list[Path]:
    session = client.get(f"{base}/sessions/{uuid}").raise_for_status().json()

    written = []
    for obs in session["observations"]:
        oid = obs["observation_id"]
        url = f"{base}/sessions/{uuid}/observations/{oid}/track"
        points = client.get(url).raise_for_status().json()["points"]

        # Только ручные и только непогашенные: погашенная точка — это отказ
        # человека от собственной отметки, и в эталоне ей делать нечего.
        keep = [
            i
            for i, source in enumerate(points["source"])
            if source == "manual" and points["enabled"][i]
        ]
        if not keep:
            print(f"{oid}: ручных точек нет, пропуск")
            continue

        path = TRUTH / f"obs_{oid}.json"
        path.write_text(
            json.dumps(
                {
                    "observation_id": oid,
                    "session_uuid": uuid,
                    "note": note,
                    "mjd": [points["mjd"][i] for i in keep],
                    "f_offset_hz": [points["f_offset_hz"][i] for i in keep],
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"{oid}: {len(keep)} точек → {path}")
        written.append(path)

    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session_uuid")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    TRUTH.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30.0) as client:
        written = pull(client, args.base.rstrip("/"), args.session_uuid, args.note)

    if not written:
        print("ни одного файла: в сессии нет ручной разметки", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
