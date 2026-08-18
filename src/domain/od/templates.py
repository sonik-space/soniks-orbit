"""Шаблонные затравки орбит — порт клавиши `t` из `rffit.c:1092-1143`.

Нужны там, где затравки нет вовсе: у наблюдения неопознанного объекта TLE
в `obs["tle"]` либо отсутствует, либо принадлежит соседу по запуску. Оператор
`rffit` в этом случае берёт грубый шаблон, гонит фит и смотрит, сходится ли.

Три из четырёх шаблонов — константы. **LEO не константа**: эталон ставит
восходящий узел под станцию, а среднюю аномалию — под её широту, чтобы
полярная орбита проходила над наблюдателем примерно в середине набора.
Поэтому шаблон строится на сервере (правило 9) и требует площадку и время.

Номер объекта и обозначение эталон тоже подставляет свои — `99999` и
`13900A`. Первое здесь остаётся (`Elements.satno` по умолчанию), второе
приклеивается на уровне строк TLE, а не элементов.
"""

from __future__ import annotations

from typing import Literal

from .elements import Elements
from .geometry import gmst

TemplateName = Literal["leo", "gto", "gso", "heo"]

# Наклонение, эксцентриситет, аргумент перигея, средняя аномалия,
# среднее движение, B* — в точности таблица `rffit.c:1092-1143`.
# RAAN и, у LEO, средняя аномалия зависят от площадки и считаются ниже.
_FIXED: dict[str, dict[str, float]] = {
    "leo": {"incl_deg": 90.0, "ecc": 0.0001, "argp_deg": 0.0, "rev_per_day": 14.0,
            "bstar": 5e-5},
    "gto": {"incl_deg": 20.0, "ecc": 0.7, "argp_deg": 0.0, "ma_deg": 0.0,
            "raan_deg": 0.0, "rev_per_day": 2.25, "bstar": 0.0},
    "gso": {"incl_deg": 10.0, "ecc": 0.0, "argp_deg": 0.0, "ma_deg": 0.0,
            "raan_deg": 0.0, "rev_per_day": 1.0027, "bstar": 0.0},
    "heo": {"incl_deg": 63.434, "ecc": 0.71, "argp_deg": 270.0, "ma_deg": 0.0,
            "raan_deg": 0.0, "rev_per_day": 2.006, "bstar": 0.0},
}

TEMPLATE_NAMES: tuple[str, ...] = tuple(_FIXED)


def template(
    name: str, *, epoch_mjd: float, lat_deg: float, lng_deg: float
) -> Elements:
    """Шаблонная затравка на заданную эпоху и площадку.

    `epoch_mjd` — середина набора, как `compute_mean_mjd` в эталоне
    (`rffit.c:70`): шаблон обязан стоять посреди данных, иначе первый же фит
    начинается с полувитка невязки.

    `ecc` у GSO в эталоне ровно ноль. Здесь он таким и остаётся: это затравка,
    а не результат, и порог публикации (`MIN_ECC`) стоит на выходе фита,
    а не на входе.
    """
    if name not in _FIXED:
        raise ValueError(f"неизвестный шаблон {name!r}, есть {', '.join(_FIXED)}")

    block = dict(_FIXED[name])
    if name == "leo":
        block["raan_deg"] = (gmst(epoch_mjd) + lng_deg) % 360.0
        block["ma_deg"] = lat_deg % 360.0

    return Elements(epoch_mjd=epoch_mjd, **block)
