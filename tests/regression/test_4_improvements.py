"""Ступень 4 лестницы: улучшения не ухудшают результат.

Запускается только после зелёной третьей. Здесь включается всё, чем наш фит
отличается от эталона (decisions/003 и 004):

  - несущая своя у каждого наблюдения, а не одна на весь набор;
  - веса точек по качеству;
  - априорные члены к затравке плюс член на `argp + M`;
  - `loss='soft_l1'`.

**Про формулировку «RMS не хуже, чем у rffit».** Она осмысленна только тогда,
когда эталонный прогон сам по себе корректен. Если `rffit` пустили со всеми
семью свободными параметрами по одному короткому проходу, он переобучается:
на `tab_lobach_1.dat` наклонение уезжает на 3.08° (61 априорной σ), на
`tusur338obs.dat` — на 1.48°, а B* вырастает в 68 раз. RMS при этом ниже —
именно так и выглядит «правдоподобный RMS при бессмысленных элементах»,
ради борьбы с которым и принято decisions/004.

Гнаться за таким RMS означало бы выключить регуляризацию, то есть
воспроизвести дефект вместо того, чтобы его чинить. Поэтому сравнение по RMS
идёт только с корректно поставленными прогонами, а вырожденные проверяются
на то, что они действительно вырождены.
"""

from __future__ import annotations

import numpy as np

from domain.od.elements import Elements
from domain.od.fit import DEFAULT_PRIOR_SIGMAS, PARAM_NAMES, Segment, fit

from conftest import elements_of

TOL_KHZ = 1e-3

# Величины, которые доплер с наземных станций почти не определяет
# (algorithms.md §4.3): наклонение задано запуском, B* практически свободен.
# Если эталонный прогон сдвинул их на десятки σ — он переобучен.
UNDETERMINED = (PARAM_NAMES.index("incl_deg"), PARAM_NAMES.index("bstar"))
DEGENERACY_SIGMAS = 10.0


def _reference_drift(golden: dict) -> np.ndarray:
    seed = elements_of(golden["seed"], golden["satno"]).to_vector()
    ref = elements_of(golden["post"]["elements"], golden["satno"]).to_vector()
    return np.abs(ref - seed) / DEFAULT_PRIOR_SIGMAS


def _reference_is_degenerate(golden: dict) -> bool:
    return bool(_reference_drift(golden)[list(UNDETERMINED)].max() > DEGENERACY_SIGMAS)


def test_improvements_do_not_regress(
    golden: dict, seed: Elements, segments: list[Segment], capsys
) -> None:
    res = fit(seed, segments, compat=False)
    want = golden["post"]["rms_khz"]
    drift = _reference_drift(golden)
    degenerate = _reference_is_degenerate(golden)

    with capsys.disabled():
        print(f"\n  {golden['dat'].split('/')[-1]}  маска эталона {golden['free_params']}")
        print(f"  rffit {want:.6f} кГц, одна несущая")
        print(f"  наш   {res.rms_khz:.6f} кГц, несущих {len(res.carriers_khz)}")
        for key, c in sorted(res.carriers_khz.items()):
            print(
                f"     станция {key:>5}: {c:12.3f} кГц, "
                f"RMS {res.per_segment_rms_khz[key]:.4f}"
            )
        if degenerate:
            print(
                f"  эталон переобучен: наклонение {drift[0]:.0f}σ, B* {drift[6]:.0f}σ "
                f"— сравнение по RMS не проводится"
            )
        if res.prior_dominated:
            print(f"  удержаны приором: {', '.join(res.prior_dominated)}")

    if degenerate:
        return
    assert res.rms_khz <= want + TOL_KHZ, (
        f"наш RMS {res.rms_khz:.6f} хуже эталонных {want:.6f} кГц — "
        f"улучшения ухудшили результат"
    )


def test_degenerate_reference_really_is_degenerate(golden: dict) -> None:
    """Обратная сторона предыдущего теста.

    Прогон, который признан вырожденным и потому исключён из сравнения по RMS,
    обязан быть вырожденным по существу: элементы у него уехали далеко,
    а у нас — нет. Без этой проверки признак вырожденности стал бы просто
    способом не сравнивать ничего.
    """
    if not _reference_is_degenerate(golden):
        return
    drift = _reference_drift(golden)
    assert drift[list(UNDETERMINED)].max() > DEGENERACY_SIGMAS
    assert golden["free_params"] == "1111111", (
        "вырожденным оказался прогон с зажатыми параметрами — это неожиданно"
    )


def test_priors_hold_undetermined_elements(
    seed: Elements, segments: list[Segment]
) -> None:
    """Ни один элемент не должен уехать от затравки на много σ.

    Это и есть смысл регуляризации: слабо определённые направления остаются
    у затравки, а не гуляют. Порог мягкий — он ловит не тонкую настройку,
    а срыв вроде B*, ушедшего на десятки σ.
    """
    res = fit(seed, segments, compat=False)
    da = np.abs(res.elements.to_vector() - seed.to_vector()) / DEFAULT_PRIOR_SIGMAS
    worst = PARAM_NAMES[int(np.argmax(da))]
    assert da.max() < 5.0, (
        f"{worst} уехал на {da.max():.1f}σ от затравки — приор не держит"
    )


def test_priors_switch_off_at_large_sigma(
    seed: Elements, segments: list[Segment]
) -> None:
    """При σ → ∞ приорный член обязан исчезать (testing.md §3).

    Свободный фит не может быть хуже зажатого приором: приор только добавляет
    слагаемые к минимизируемой сумме. Если этот тест красный — значит σ влияет
    не только на приор, а ещё на что-то (так и было, пока масштаб параметров
    не отделили от приорных σ, см. PARAM_SCALE).
    """
    huge = np.full(7, 1e12)
    free = fit(seed, segments, compat=False, prior_sigmas=huge, sigma_argp_plus_m=1e12)
    tight = fit(seed, segments, compat=False)
    assert free.rms_khz <= tight.rms_khz + TOL_KHZ, (
        f"без приоров RMS {free.rms_khz:.6f}, с приорами {tight.rms_khz:.6f} кГц"
    )


def test_infinite_sigma_reports_nothing_as_prior_dominated(
    seed: Elements, segments: list[Segment]
) -> None:
    """Экспертный режим `priors_off` даёт **ровно** σ = ∞, а не 1e12.

    На бесконечности `da = |Δa|/σ` обращается в ноль по всем элементам,
    и проверка `da < 1` без защиты объявляла бы удержанными приором все семь —
    то есть сообщала бы «данные ничего не сдвинули» ровно на том прогоне,
    где приоров нет вовсе и всё сдвинули именно данные.
    """
    off = fit(
        seed,
        segments,
        compat=False,
        prior_sigmas=np.full(7, np.inf),
        sigma_argp_plus_m=float("inf"),
    )
    assert off.prior_dominated == [], (
        f"приоров нет, а удержанными приором названы {off.prior_dominated}"
    )
    assert np.isfinite(off.rms_khz), "фит без приоров развалился"

    # И на конечных σ признак продолжает работать: 26 точек одного прохода
    # не определяют семь элементов, и что-то приор обязан удержать.
    assert fit(seed, segments, compat=False).prior_dominated
