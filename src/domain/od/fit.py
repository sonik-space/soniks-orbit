"""Фит элементов орбиты по доплеровским измерениям.

Порт математики `rffit.c` (`chisq`, `compute_rms`, `fit_curve`) с одним
обобщением: несущая может быть своей у каждого наблюдения, а не одной
на весь набор (decisions/003). Режим совместимости — `compat=True` — сохраняет
поведение эталона и **обязан оставаться в коде**, иначе регрессионный тест
из testing.md §1 протухнет.

Единицы: частоты в вектор невязок приходят и уходят в **кГц**, как в `rffit`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from .doppler import fac as doppler_fac
from .elements import Elements
from .geometry import range_rate

# Шаги симплекса из `fit_curve` (rffit.c:1953). В нашем фите они работают
# масштабом параметров, а не шагом: `least_squares` оптимизирует
# p = (a − a_seed)/scale, поэтому x_scale остаётся единичным.
COMPAT_SCALE = np.array([5.0, 5.0, 0.1, 5.0, 5.0, 0.1, 1e-5])

# Априорные σ по умолчанию для LEO (algorithms.md §4.3).
DEFAULT_PRIOR_SIGMAS = np.array([0.05, 0.5, 0.001, 20.0, 20.0, 0.005, 1e-4])
DEFAULT_SIGMA_ARGP_PLUS_M = 5.0

# Масштаб параметров для оптимизатора. Численно совпадает с приорными σ,
# но это **отдельная величина**.
#
# algorithms.md §4.1 предлагает одну: p = (a − a_seed)/σ, и тогда приорный
# член получается бесплатно. Красиво, но ломается ровно там, где это важнее
# всего — при σ → ∞ («приоры выключены», проверка из testing.md §3).
# Масштаб уезжает вместе с σ, шаг численного якобиана перестаёт что-либо
# менять, границы по ecc схлопываются вокруг нуля, и `trf` вышвыривает
# стартовую точку на середину отрезка: замер дал ecc = 0.4995 и RMS 19.9 кГц
# на ровном месте. Цена разделения — одно деление в приорном члене.
PARAM_SCALE = DEFAULT_PRIOR_SIGMAS.copy()

_SGP4_FAILURE_RESIDUAL = 1e6


@dataclass(frozen=True)
class Segment:
    """Точки с одной общей несущей: наблюдение, а в режиме совместимости —
    весь набор целиком."""

    mjd: np.ndarray
    f_khz: np.ndarray
    weight: np.ndarray
    lat_deg: float
    lng_deg: float
    alt_km: float
    key: str = ""


@dataclass
class FitResult:
    elements: Elements
    rms_khz: float
    rms_pre_khz: float
    carriers_khz: dict[str, float]
    per_segment_rms_khz: dict[str, float]
    residuals_khz: np.ndarray
    success: bool
    nfev: int
    message: str = ""
    prior_dominated: list[str] = field(default_factory=list)


PARAM_NAMES = (
    "incl_deg",
    "raan_deg",
    "ecc",
    "argp_deg",
    "ma_deg",
    "rev_per_day",
    "bstar",
)


def profile_carrier(
    fac: np.ndarray, f_khz: np.ndarray, weight: np.ndarray | None = None
) -> float:
    """Несущая в замкнутом виде: `Σ w·fac·f / Σ w·fac²`, кГц.

    При `weight=None` — в точности `sum1/sum2` из `rffit.c:1687`: эталон веса
    не использует, столбец качества в `.dat` он читает и игнорирует.
    """
    if weight is None:
        return float(np.sum(fac * f_khz) / np.sum(fac * fac))
    return float(np.sum(weight * fac * f_khz) / np.sum(weight * fac * fac))


def _model(
    elements: Elements,
    segments: list[Segment],
    *,
    per_segment_carrier: bool,
    weighted: bool,
) -> tuple[np.ndarray, dict[str, float], bool]:
    """Невязки по данным (кГц) и подобранные несущие."""
    sat = elements.to_satrec()

    facs: list[np.ndarray] = []
    ok = True
    for seg in segments:
        v_km_s, err = range_rate(sat, seg.mjd, seg.lat_deg, seg.lng_deg, seg.alt_km)
        if np.any(err != 0):
            ok = False
        facs.append(doppler_fac(v_km_s))

    carriers: dict[str, float] = {}
    if per_segment_carrier:
        for seg, f in zip(segments, facs):
            w = seg.weight if weighted else None
            carriers[seg.key] = profile_carrier(f, seg.f_khz, w)
    else:
        all_fac = np.concatenate(facs)
        all_f = np.concatenate([s.f_khz for s in segments])
        all_w = np.concatenate([s.weight for s in segments]) if weighted else None
        one = profile_carrier(all_fac, all_f, all_w)
        carriers = {seg.key: one for seg in segments}

    resid = np.concatenate(
        [seg.f_khz - f * carriers[seg.key] for seg, f in zip(segments, facs)]
    )
    return resid, carriers, ok


def rms_khz(resid: np.ndarray) -> float:
    """RMS по данным, невзвешенно, в кГц — как `compute_rms` (rffit.c:1707)."""
    return float(np.sqrt(np.sum(resid**2) / resid.size))


def screen(
    elements: Elements, segments: list[Segment]
) -> tuple[float, dict[str, float]] | None:
    """Оценка кандидата **без движения элементов**: RMS и несущие.

    Первая ступень идентификации (algorithms.md §6): одна векторная прогонка
    SGP4 по точкам трека плюс профилирование несущей в замкнутом виде.
    Зеркало `fit_curve(orb, ia)` с нулевой маской свободных параметров —
    именно так `identify_satellite_from_doppler` из `rffit.c:152` оценивает
    каждый объект каталога под клавишей `i`.

    Это обёртка над `_model`, а не вторая реализация: второй копии снятия
    доплера и профилирования несущей в проекте быть не должно (правила 8 и 9).

    `None` — SGP4 вернул код ошибки хотя бы в одной точке. Кандидат не
    отбрасывается молча нулём: у сошедшего с орбиты объекта RMS не определён,
    а ноль выиграл бы ранжирование.
    """
    resid, carriers, ok = _model(
        elements, segments, per_segment_carrier=True, weighted=True
    )
    return (rms_khz(resid), carriers) if ok else None


def fit(
    seed: Elements,
    segments: list[Segment],
    *,
    compat: bool = False,
    free: str = "1111111",
    prior_sigmas: np.ndarray | None = None,
    sigma_argp_plus_m: float = DEFAULT_SIGMA_ARGP_PLUS_M,
    f_scale: float = 0.5,
    max_nfev: int = 200,
) -> FitResult:
    """Подгонка элементов.

    `compat=True` воспроизводит `rffit`: одна несущая на весь набор, веса
    игнорируются, приоры выключены, `loss='linear'`.

    `free` — маска из семи символов 0/1 в порядке `PARAM_NAMES`, зеркало
    массива `ia` в `fit_curve`. Зажатые параметры просто не входят в вектор
    оптимизации.
    """
    if len(free) != 7:
        raise ValueError("маска free должна быть из семи символов 0/1")
    free_idx = np.array([i for i, c in enumerate(free) if c == "1"])

    per_segment_carrier = not compat
    weighted = not compat
    scale = COMPAT_SCALE if compat else PARAM_SCALE
    sigmas = (
        DEFAULT_PRIOR_SIGMAS if prior_sigmas is None else np.asarray(prior_sigmas, float)
    )

    a_seed = seed.to_vector()
    argp_plus_m_seed = a_seed[3] + a_seed[4]

    # Зажимы `chisq` (ecc в [0, 0.999], n ≥ 0.05) существуют в эталоне потому,
    # что симплекс не умеет границ, и там они реализованы обрезкой аргумента
    # внутри целевой функции. Нам это вредит: за границей функция становится
    # плоской, численный якобиан по этому направлению обнуляется, и `trf`
    # останавливается по xtol, не дойдя до минимума (наблюдалось на
    # tusur338obs: ecc упирался ровно в 0 и RMS оставался хуже эталонного).
    # `trf` умеет границы честно, поэтому здесь они задаются явно.
    # Обрезка в `Elements.with_vector` остаётся страховкой от NaN.
    lo = np.full(7, -np.inf)
    hi = np.full(7, np.inf)
    lo[2], hi[2] = -a_seed[2] / scale[2], (0.999 - a_seed[2]) / scale[2]
    lo[5] = (0.05 - a_seed[5]) / scale[5]

    def elements_at(p_free: np.ndarray) -> Elements:
        a = a_seed.copy()
        a[free_idx] = a_seed[free_idx] + p_free * scale[free_idx]
        return seed.with_vector(a)

    n_data = sum(s.mjd.size for s in segments)

    def residual_vector(p_free: np.ndarray) -> np.ndarray:
        elements = elements_at(p_free)
        resid, _, ok = _model(
            elements,
            segments,
            per_segment_carrier=per_segment_carrier,
            weighted=weighted,
        )
        if not ok:
            # Не NaN: trf тогда сожмёт доверительную область, а не упадёт.
            return np.full(n_data + (0 if compat else 8), _SGP4_FAILURE_RESIDUAL)
        if compat:
            return resid

        a = elements.to_vector()
        prior = (a - a_seed) / sigmas
        argp_plus_m = (a[3] + a[4] - argp_plus_m_seed + 180.0) % 360.0 - 180.0
        return np.concatenate([resid, prior, [argp_plus_m / sigma_argp_plus_m]])

    resid_pre, _, _ = _model(
        seed, segments, per_segment_carrier=per_segment_carrier, weighted=weighted
    )
    rms_pre = rms_khz(resid_pre)

    res = least_squares(
        residual_vector,
        x0=np.zeros(free_idx.size),
        bounds=(lo[free_idx], hi[free_idx]),
        method="trf",
        loss="linear" if compat else "soft_l1",
        f_scale=f_scale,
        x_scale=1.0,
        xtol=1e-12,
        ftol=1e-12,
        gtol=1e-12,
        max_nfev=max_nfev,
        diff_step=1e-4,
    )

    elements = elements_at(res.x)
    resid, carriers, _ = _model(
        elements, segments, per_segment_carrier=per_segment_carrier, weighted=weighted
    )

    per_seg: dict[str, float] = {}
    at = 0
    for seg in segments:
        per_seg[seg.key] = rms_khz(resid[at : at + seg.mjd.size])
        at += seg.mjd.size

    # Приоров нет — «удержан приором» не определено ни для одного параметра.
    # Без проверки на конечность σ = ∞ даёт da = 0, и в список попадают **все**
    # свободные элементы: экспертный режим «без приоров» сообщал бы «данные
    # ничего не сдвинули» ровно на тех прогонах, где данные сдвинули всё.
    dominated = []
    if not compat and np.all(np.isfinite(sigmas)):
        da = np.abs(elements.to_vector() - a_seed) / sigmas
        dominated = [PARAM_NAMES[i] for i in free_idx if da[i] < 1.0]

    return FitResult(
        elements=elements,
        rms_khz=rms_khz(resid),
        rms_pre_khz=rms_pre,
        carriers_khz=carriers,
        per_segment_rms_khz=per_seg,
        residuals_khz=resid,
        success=bool(res.success),
        nfev=int(res.nfev),
        message=str(res.message),
        prior_dominated=dominated,
    )
