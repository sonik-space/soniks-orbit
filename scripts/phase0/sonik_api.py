"""Доступ к боевому API СОНИКС и кеш водопадов. Только для скриптов фазы 0.

В сервисе это станет `infrastructure/network_api/` и `infrastructure/images/`
за интерфейсом из `application/interfaces/`. Здесь — голые функции: фаза 0
не заводит слоёв.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

BASE = "https://sonik.space"
CACHE = Path(__file__).parent / "cache"
TIMEOUT = 60


def get_observation(observation_id: int, *, refresh: bool = False) -> dict:
    """Ответ `GET /api/observations/{id}/` целиком, с кешем на диске.

    Ответ кешируется и в сервисе будет замораживаться в
    `od_session_observations.meta` (правило 10): TLE в каталоге обновляется
    каждые 4 часа, и без снимка пересчёт по новому TLE изменил бы смысл уже
    посчитанных частот.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"obs_{observation_id}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))

    r = requests.get(f"{BASE}/api/observations/{observation_id}/", timeout=TIMEOUT)
    r.raise_for_status()
    obs = r.json()
    path.write_text(json.dumps(obs, ensure_ascii=False, indent=1), encoding="utf-8")
    return obs


def get_waterfall(obs: dict) -> Path:
    """Скачивает PNG водопада в кеш и возвращает путь.

    Файлы неизменяемы, поэтому кеш по `observation_id` безопасен и обязателен:
    без него нагрузка на S3 избыточна (decisions/009).
    """
    url = obs.get("waterfall")
    if not url:
        raise ValueError(f"у наблюдения {obs['id']} нет водопада")

    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"wf_{obs['id']}.png"
    if path.exists():
        return path

    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    path.write_bytes(r.content)
    return path


def iter_observations(pages: int = 40, **params):
    """Постранично по `GET /api/observations/`. Курсор — в заголовке `Link`.

    Полезные фильтры (`network/api/filters.py::ObservationViewFilter`):
    `end` — не позже указанного ISO-времени, `status=good`,
    `waterfall_status=1` — размеченные человеком как «есть сигнал».
    Без `end` первые страницы забиты наблюдениями, которые ещё идут
    и водопада пока не имеют.
    """
    url = f"{BASE}/api/observations/"
    first = True
    for _ in range(pages):
        r = requests.get(url, params=params if first else None, timeout=TIMEOUT)
        r.raise_for_status()
        first = False
        yield from r.json()

        link = r.headers.get("Link", "")
        if 'rel="next"' not in link:
            return
        url = link[link.index("<") + 1 : link.index(">")].replace(
            "http://", "https://", 1
        )


_TX_CACHE: dict[str, dict] = {}


def get_transmitter(uuid: str) -> dict | None:
    """Запись передатчика по uuid, с кешем на диске.

    Нужна ради полей `baud` и `downlink_low`: в ответе наблюдения лежит
    только uuid. Раздел работает с узкополосной телеметрией
    (1200/2400/4800/9600 бод); широкая полоса — это метеоспутники, для них
    инструмент не предназначен.

    Запрашивается по одному uuid, а не списком: `GET /api/transmitters/`
    отдаёт ровно 100 записей и не листается (ни `page`, ни `limit`, ни
    заголовок `Link` не работают), так что полный справочник оттуда
    не собрать.
    """
    if not uuid:
        return None
    if uuid in _TX_CACHE:
        return _TX_CACHE[uuid]

    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "transmitters.json"
    disk = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if uuid in disk:
        _TX_CACHE[uuid] = disk[uuid]
        return disk[uuid]

    r = requests.get(f"{BASE}/api/transmitters/", params={"uuid": uuid}, timeout=TIMEOUT)
    r.raise_for_status()
    items = r.json()
    record = items[0] if items else None
    disk[uuid] = record
    _TX_CACHE[uuid] = record
    path.write_text(json.dumps(disk, ensure_ascii=False), encoding="utf-8")
    return record


def png_text_chunks(blob: bytes) -> dict[str, str]:
    """Текстовые чанки PNG из началa файла, без полной загрузки картинки.

    `matplotlib.savefig(metadata=...)` пишет их до `IDAT`, поэтому первых
    килобайт достаточно, и весь водопад ради метаданных качать не нужно.
    """
    out: dict[str, str] = {}
    if not blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return out

    at = 8
    while at + 8 <= len(blob):
        length = int.from_bytes(blob[at : at + 4], "big")
        kind = blob[at + 4 : at + 8]
        if kind == b"IDAT":
            break
        data = blob[at + 8 : at + 8 + length]
        if len(data) < length:
            break  # чанк не поместился в скачанный кусок
        if kind in (b"tEXt", b"iTXt") and b"\x00" in data:
            key, _, value = data.partition(b"\x00")
            out[key.decode("latin-1")] = value.lstrip(b"\x00").decode(
                "utf-8", "replace"
            )
        at += 12 + length
    return out


def peek_wf_dat(url: str, nbytes: int = 16384) -> dict | None:
    """`satnogs:wf-dat` по Range-запросу первых килобайт PNG."""
    r = requests.get(url, headers={"Range": f"bytes=0-{nbytes - 1}"}, timeout=TIMEOUT)
    if r.status_code not in (200, 206):
        return None
    raw = png_text_chunks(r.content).get("satnogs:wf-dat")
    return json.loads(raw) if raw else None
