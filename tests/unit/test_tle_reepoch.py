"""Round-trip TLE и неподвижная точка переноса эпохи (testing.md §3).

Данные — все `.tle` из `strf/`, то есть настоящие наборы, которыми
пользовались при реальных фитах, а не синтетика.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from domain.od.elements import Elements
from domain.od.reepoch import reepoch, _state_at
from domain.od.tle import TLE_LINE_LENGTH, checksum, to_lines

STRF = Path(__file__).resolve().parents[3] / "strf"


def _tle_sets() -> list[tuple[str, str, str]]:
    """Пары строк из всех `.tle`: часть файлов с именем, часть без, плюс
    строки комментариев `#` с отчётом о фите."""
    out = []
    for path in sorted(STRF.glob("*.tle")):
        lines = [
            ln.rstrip("\n")
            for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip() and not ln.startswith("#")
        ]
        for i in range(len(lines) - 1):
            if lines[i].startswith("1 ") and lines[i + 1].startswith("2 "):
                out.append((path.name, lines[i], lines[i + 1]))
    return out


TLE_SETS = _tle_sets()

# Фикстура переноса эпохи выбрана явно, а не «первая попавшаяся».
# В `geoscan-1.tle` объект сходит с орбиты: B* = 5e-4 при e = 0.059,
# и SGP4 возвращает код ошибки уже через двое суток. Проверять на нём
# неподвижную точку значило бы проверять поведение при отказе.
REEPOCH_FIXTURE = next(
    (t for t in TLE_SETS if t[0] == "l10.tle"), TLE_SETS[0] if TLE_SETS else None
)


def test_fixture_files_are_present() -> None:
    """Иначе параметризация пуста и тест зеленеет, ничего не проверив."""
    assert len(TLE_SETS) >= 30, f"в {STRF} найдено {len(TLE_SETS)} наборов"


@pytest.mark.parametrize(
    "name,line1,line2", TLE_SETS, ids=[f"{n}-{i}" for i, (n, _, _) in enumerate(TLE_SETS)]
)
def test_tle_round_trip(name: str, line1: str, line2: str) -> None:
    seed = Elements.from_tle(line1, line2)
    out1, out2 = to_lines(
        seed, intldes=line1[9:17].strip(), elnum=int(line1[64:68]), revnum=int(line2[63:68])
    )

    assert len(out1) == len(out2) == TLE_LINE_LENGTH
    assert int(out1[68]) == checksum(out1)
    assert int(out2[68]) == checksum(out2)

    back = Elements.from_tle(out1, out2)
    for field in ("incl_deg", "raan_deg", "ecc", "argp_deg", "ma_deg", "rev_per_day"):
        assert getattr(back, field) == pytest.approx(getattr(seed, field), abs=1e-9), field
    assert back.epoch_mjd == pytest.approx(seed.epoch_mjd, abs=1e-9)
    assert back.bstar == pytest.approx(seed.bstar, rel=1e-9, abs=1e-12)


def test_reepoch_to_its_own_epoch_returns_the_seed() -> None:
    """Ошибка знака в неподвижной точке видна именно здесь.

    `argp` и `M` сравниваются **суммой**: при `e ≈ 0.002` по отдельности они
    вырождены, и требовать их совпадения значило бы проверять свойство
    оптимизатора, а не математику (та же оговорка, что в testing.md §1).
    """
    name, line1, line2 = REEPOCH_FIXTURE
    seed = Elements.from_tle(line1, line2)
    same = reepoch(seed, seed.epoch_mjd)

    assert same.incl_deg == pytest.approx(seed.incl_deg, abs=1e-7)
    assert same.raan_deg == pytest.approx(seed.raan_deg, abs=1e-7)
    assert same.ecc == pytest.approx(seed.ecc, abs=1e-7)
    assert same.rev_per_day == pytest.approx(seed.rev_per_day, abs=1e-7)
    assert (same.argp_deg + same.ma_deg) % 360.0 == pytest.approx(
        (seed.argp_deg + seed.ma_deg) % 360.0, abs=1e-7
    )
    assert same.bstar == seed.bstar


@pytest.mark.parametrize("dt_days", [0.0, 0.5, 2.0, 10.0, -5.0])
def test_reepoch_keeps_the_state(dt_days: float) -> None:
    """Смысл переноса: на новой эпохе модель даёт то же положение и скорость.

    Это сильнее сравнения элементов — оно не зависит от того, как разошлись
    вырожденные направления.
    """
    name, line1, line2 = REEPOCH_FIXTURE
    seed = Elements.from_tle(line1, line2)
    target = seed.epoch_mjd + dt_days

    moved = reepoch(seed, target)
    r_seed, v_seed = _state_at(seed, target)
    r_moved, v_moved = _state_at(moved, target)

    assert np.linalg.norm(r_moved - r_seed) < 1e-6  # км, то есть миллиметры
    assert np.linalg.norm(v_moved - v_seed) < 1e-9
    assert moved.epoch_mjd == target


# Результат фита фазы 4 на двух проходах 64880. Орбита почти круговая:
# `e = 6.1e-4` при `argp + M ≈ 0.1°`, то есть перигей и средняя аномалия
# по отдельности не определены.
NEAR_CIRCULAR = (
    "1 64880U 25155E   26227.90891533  .00000000  00000-0  25503-3 0    02",
    "2 64880  97.4614 196.9574 0006122 343.2651  16.8325 15.31853568    05",
)


@pytest.mark.parametrize("dt_days", [0.0, 0.535, 2.0, 10.0, -234.0])
def test_reepoch_survives_a_near_circular_orbit(dt_days: float) -> None:
    """Неподвижная точка в координатах `(e, argp, M)` здесь **не сходится**.

    Замер до правки: `argp` и `M` расходились на ±43° за шаг при неподвижной
    сумме, приращение по `e` уходило в минус и зажималось нулём, критерий
    `max|delta| < tol` не срабатывал ни разу, и функция молча возвращала
    точку с ошибкой **8.4 км** — вчетверо меньше порога публикации, то есть
    такое TLE ушло бы в каталог наведения сети незамеченным.

    Полсуток в списке — не круглое число, а тот самый интервал, на котором
    это вылезло: конец последнего прохода сессии, обычный выбор эпохи.
    """
    seed = Elements.from_tle(*NEAR_CIRCULAR)
    moved = reepoch(seed, seed.epoch_mjd + dt_days)

    r_seed, _ = _state_at(seed, moved.epoch_mjd)
    r_moved, _ = _state_at(moved, moved.epoch_mjd)
    assert np.linalg.norm(r_moved - r_seed) < 1e-6

    # Эксцентриситет не должен схлопываться в ноль: с `e = 0` модель
    # физически не может воспроизвести состояние, и это была вторая половина
    # той же поломки. Допуск относительный и широкий: на переносе через
    # восемь месяцев средний `e` честно уползает на несколько процентов,
    # а ловим мы здесь схлопывание, то есть все сто.
    assert moved.ecc == pytest.approx(seed.ecc, rel=0.15)
