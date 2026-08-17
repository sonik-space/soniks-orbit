"""Ступень 2 лестницы: профилированная несущая против эталона.

При фиксированных элементах затравки несущая находится в замкнутом виде,
без всякой оптимизации. Ступень изолирует ровно эту формулу и формулу
невязки — оптимизатор здесь ещё не участвует.

Допуск 1 Гц = 0.001 кГц.
"""

from __future__ import annotations

from domain.od.elements import Elements
from domain.od.fit import profile_carrier, rms_khz

from conftest import fac_at

TOL_KHZ = 1e-3  # 1 Гц


def test_carrier_matches_c(golden: dict, seed: Elements) -> None:
    """`Σ fac·f / Σ fac²` — в точности `sum1/sum2` из `rffit.c:1687`.

    Веса не применяются: эталон читает столбец качества из `.dat` и
    игнорирует его. Наша несущая по весам — это улучшение, и проверяется
    оно ступенью 4, а не здесь.
    """
    got = profile_carrier(fac_at(seed, golden), golden["f_khz"])
    want = golden["pre"]["ffit_khz"]
    assert abs(got - want) < TOL_KHZ, (
        f"несущая {got:.6f} против эталонных {want:.6f} кГц, "
        f"расхождение {abs(got - want) * 1000:.3f} Гц"
    )


def test_rms_before_fit_matches_c(golden: dict, seed: Elements) -> None:
    """RMS до фита — `compute_rms` (rffit.c:1707), невзвешенно, в кГц.

    Проверяет формулу невязки отдельно от оптимизатора: если ступень 3
    потом покраснеет, здесь уже будет известно, что дело не в невязке.
    """
    resid = golden["f_khz"] - fac_at(seed, golden) * golden["pre"]["ffit_khz"]
    got = rms_khz(resid)
    want = golden["pre"]["rms_khz"]
    assert abs(got - want) < TOL_KHZ, (
        f"RMS до фита {got:.6f} против эталонных {want:.6f} кГц"
    )
