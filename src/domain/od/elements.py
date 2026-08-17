"""Элементы орбиты и построение SGP4-модели по ним.

Порядок параметров тот же, что в `rffit.c` (`chisq`, `fit_curve`):

    a[0] наклонение, град     a[4] средняя аномалия, град
    a[1] RAAN, град           a[5] среднее движение, об/сут
    a[2] эксцентриситет       a[6] B*
    a[3] аргумент перигея, град
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
from sgp4.api import WGS72, Satrec

from .constants import MJD_1949_12_31

_D2R = np.pi / 180.0
_TWOPI_PER_DAY_TO_RAD_PER_MIN = 2.0 * np.pi / 1440.0


@dataclass(frozen=True)
class Elements:
    """Средние элементы SGP4. Углы в градусах, `n` в оборотах за сутки."""

    incl_deg: float
    raan_deg: float
    ecc: float
    argp_deg: float
    ma_deg: float
    rev_per_day: float
    bstar: float
    epoch_mjd: float
    satno: int = 99999

    # --- вектор параметров -------------------------------------------------

    def to_vector(self) -> np.ndarray:
        return np.array(
            [
                self.incl_deg,
                self.raan_deg,
                self.ecc,
                self.argp_deg,
                self.ma_deg,
                self.rev_per_day,
                self.bstar,
            ],
            dtype=float,
        )

    def with_vector(self, a: np.ndarray) -> "Elements":
        """Элементы из вектора параметров, с зажимами и обёрткой углов.

        Зажимы повторяют `chisq` (`rffit.c:1645-1651`) буквально: без них фит
        уводит эксцентриситет за единицу и среднее движение в ноль, а SGP4
        начинает возвращать коды ошибок вместо чисел.
        """
        a = np.asarray(a, dtype=float)
        ecc = min(max(a[2], 0.0), 0.999)
        rev = max(a[5], 0.05)
        return replace(
            self,
            incl_deg=a[0],
            raan_deg=a[1] % 360.0,
            ecc=ecc,
            argp_deg=a[3] % 360.0,
            ma_deg=a[4] % 360.0,
            rev_per_day=rev,
            bstar=a[6],
        )

    # --- SGP4 --------------------------------------------------------------

    def to_satrec(self) -> Satrec:
        """Модель SGP4 по элементам, минуя строки TLE.

        Единицы — самое опасное место во всём модуле (правило 2):
        `sgp4init` принимает **радианы** и **рад/мин**, а не градусы и об/сут,
        и эпоху в сутках от 1949-12-31, а не в MJD. Ошибка тут даёт орбиту,
        которая выглядит правдоподобно и неверна.
        """
        sat = Satrec()
        sat.sgp4init(
            WGS72,
            "i",
            self.satno,
            self.epoch_mjd - MJD_1949_12_31,
            self.bstar,
            0.0,  # ndot: SGP4 его не использует
            0.0,  # nddot: то же
            self.ecc,
            self.argp_deg * _D2R,
            self.incl_deg * _D2R,
            self.ma_deg * _D2R,
            self.rev_per_day * _TWOPI_PER_DAY_TO_RAD_PER_MIN,
            self.raan_deg * _D2R,
        )
        return sat

    @classmethod
    def from_tle(cls, line1: str, line2: str) -> "Elements":
        sat = Satrec.twoline2rv(line1, line2)
        return cls(
            incl_deg=sat.inclo / _D2R,
            raan_deg=sat.nodeo / _D2R,
            ecc=sat.ecco,
            argp_deg=sat.argpo / _D2R,
            ma_deg=sat.mo / _D2R,
            rev_per_day=sat.no_kozai / _TWOPI_PER_DAY_TO_RAD_PER_MIN,
            bstar=sat.bstar,
            epoch_mjd=sat.jdsatepoch + sat.jdsatepochF - 2400000.5,
            satno=sat.satnum,
        )
