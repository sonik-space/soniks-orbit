"""Сшивка публикации: выбор эпохи, перенос и сборка строк TLE.

**Единственное** место, где решается «на какой момент» — как `extraction.py`
для извлечения и `fitting.py` для фита (правило 8). Обе точки входа,
`POST /fits/{id}/reepoch` и `POST /fits/{id}/publish`, зовут отсюда:
иначе предпросмотр строк и то, что уходит в каталог, разошлись бы,
и заметили бы это уже после публикации.

Единицы (правило 2): наружу эпоха идёт в ISO, внутри — MJD.
"""

from __future__ import annotations

import datetime as dt

from application.dtos.publish import EpochRequest
from application.services.fitting import mjd_from_iso, to_tle
from domain.exceptions import BadRequestError
from domain.models import FitRun, OdSession, TleLines
from domain.od.elements import Elements
from domain.od.reepoch import reepoch

# Век в двузначном годе строки TLE: как в `Satrec.twoline2rv`.
_YY_PIVOT = 57


def resolve_epoch_mjd(request: EpochRequest, run: FitRun, session: OdSession) -> float:
    """Три формы запроса → один MJD."""
    if request.epoch_iso is not None:
        return mjd_from_iso(request.epoch_iso)
    if request.epoch_yyddd is not None:
        return _mjd_from_yyddd(request.epoch_yyddd)
    return _latest_observation_mjd(run, session)


def reepoch_run(
    run: FitRun, session: OdSession, request: EpochRequest | None
) -> tuple[float, TleLines]:
    """Эпоха и строки TLE прогона: перенесённые или как есть.

    Без запроса ничего не пересчитывается — публикуется ровно то TLE,
    которое человек видел в ответе фита.
    """
    if request is None:
        return run.epoch_mjd, run.tle

    target_mjd = resolve_epoch_mjd(request, run, session)
    moved = reepoch(Elements.from_tle(run.tle.tle1, run.tle.tle2), target_mjd)
    return target_mjd, to_tle(moved, session.seed)


def _mjd_from_yyddd(value: str) -> float:
    """`26005.391632037` — год и дробный день года, как в самой строке TLE."""
    yy, _, ddd = value.partition(".")
    year = int(yy[:2])
    year += 2000 if year < _YY_PIVOT else 1900
    day_of_year = float(f"{yy[2:]}.{ddd}")
    start = dt.datetime(year, 1, 1, tzinfo=dt.UTC)
    return mjd_from_iso(start) + day_of_year - 1.0


def _latest_observation_mjd(run: FitRun, session: OdSession) -> float:
    """Конец последнего прохода, участвовавшего **в этом прогоне**.

    Берётся из замороженного снимка ответа API (правило 10), а не из свежего
    запроса: снимок — единственное, что делает публикацию воспроизводимой.
    Наблюдения сессии, не попавшие в прогон, не учитываются — иначе эпоха
    уехала бы туда, где данных фита нет.
    """
    used = set(run.config.get("observation_ids") or [])
    ends = [
        dt.datetime.fromisoformat(track.meta["end"])
        for track in session.observations
        if track.observation_id in used and track.meta.get("end")
    ]
    if not ends:
        raise BadRequestError(
            "у наблюдений прогона нет времени окончания: эпоху надо задать явно"
        )
    return mjd_from_iso(max(ends))
