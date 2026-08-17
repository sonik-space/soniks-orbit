"""Формы, общие сессии и фиту: строки TLE и элементы орбиты.

Отдельный модуль ради направления импортов. `dtos/session.py` встраивает
последний прогон фита и модельную кривую, а `dtos/fit.py` возвращает TLE —
без общего низа получается цикл.

Единицы (правило 2): углы в градусах, `n` в оборотах за сутки, эпоха
наружу — ISO 8601 UTC, а не MJD.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TleSchema(BaseModel):
    tle0: str
    tle1: str
    tle2: str


class ElementsSchema(BaseModel):
    inclination_deg: float
    raan_deg: float
    eccentricity: float
    argp_deg: float
    mean_anomaly_deg: float
    mean_motion_rev_day: float
    bstar: float
    epoch: datetime
