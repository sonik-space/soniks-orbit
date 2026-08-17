"""Загрузка golden-файлов эталона `rffit` и общие для лестницы величины.

Файлы создаются `tests/regression/cdriver` один раз и коммитятся. В CI
компилятор C не нужен. Обновлять их можно только осознанно, отдельным
коммитом с объяснением, почему эталон изменился (правило 5).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from domain.od.doppler import fac
from domain.od.elements import Elements
from domain.od.fit import Segment
from domain.od.geometry import range_rate

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_NAMES = [p.stem for p in sorted(GOLDEN_DIR.glob("*.json"))]


def load_golden(name: str) -> dict:
    g = json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))
    pts = g["points"]
    for key, src in (
        ("mjd", "mjd"),
        ("f_khz", "freq_khz"),
        ("flux", "flux"),
        ("site_id", "site_id"),
        ("v_km_s", "v_km_s"),
        ("lat_deg", "lat_deg"),
        ("lng_deg", "lng_deg"),
        ("alt_km", "alt_km"),
    ):
        g[key] = np.array([p[src] for p in pts])
    return g


def elements_of(block: dict, satno: int) -> Elements:
    return Elements(
        incl_deg=block["incl_deg"],
        raan_deg=block["raan_deg"],
        ecc=block["ecc"],
        argp_deg=block["argp_deg"],
        ma_deg=block["ma_deg"],
        rev_per_day=block["rev_per_day"],
        bstar=block["bstar"],
        epoch_mjd=block["epoch_mjd"],
        satno=satno,
    )


def segments_of(g: dict) -> list[Segment]:
    """Точки, разбитые по станциям.

    В режиме совместимости несущая всё равно одна на весь набор, но геометрия
    наблюдателя своя у каждой станции, поэтому считать надо по группам.
    """
    out = []
    for site in sorted({int(s) for s in g["site_id"]}):
        m = g["site_id"] == site
        out.append(
            Segment(
                mjd=g["mjd"][m],
                f_khz=g["f_khz"][m],
                weight=g["flux"][m],
                lat_deg=float(g["lat_deg"][m][0]),
                lng_deg=float(g["lng_deg"][m][0]),
                alt_km=float(g["alt_km"][m][0]),
                key=str(site),
            )
        )
    return out


def fac_at(elements: Elements, g: dict) -> np.ndarray:
    """Доплеровский множитель на каждой точке в исходном порядке."""
    sat = elements.to_satrec()
    out = np.empty_like(g["mjd"])
    for site in {int(s) for s in g["site_id"]}:
        m = g["site_id"] == site
        v, err = range_rate(
            sat,
            g["mjd"][m],
            float(g["lat_deg"][m][0]),
            float(g["lng_deg"][m][0]),
            float(g["alt_km"][m][0]),
        )
        assert np.all(err == 0), f"SGP4 вернул код ошибки на станции {site}"
        out[m] = fac(v)
    return out


@pytest.fixture(params=GOLDEN_NAMES)
def golden(request) -> dict:
    return load_golden(request.param)


@pytest.fixture
def seed(golden: dict) -> Elements:
    return elements_of(golden["seed"], golden["satno"])


@pytest.fixture
def fitted(golden: dict) -> Elements:
    """Элементы, к которым пришёл эталон."""
    return elements_of(golden["post"]["elements"], golden["satno"])


@pytest.fixture
def segments(golden: dict) -> list[Segment]:
    return segments_of(golden)
