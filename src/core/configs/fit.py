from pydantic import BaseModel

from domain.od.fit import DEFAULT_PRIOR_SIGMAS, DEFAULT_SIGMA_ARGP_PLUS_M


class FitSettings(BaseModel):
    """Умолчания фита: априорные σ (algorithms.md §4.3), `f_scale` и защита.

    σ — **калибровочные ручки**: они передаются в запросе и сохраняются
    в `od_fit_runs.config`, иначе опубликованное TLE невоспроизводимо
    (decisions/004).

    Числа берутся из ядра, а не переписываются здесь: вторая копия
    калиброванных величин рано или поздно разойдётся с первой молча.
    Правило 1 это разрешает — оно запрещает ядру импортировать чужое,
    а не наоборот.
    """

    INCLINATION_DEG: float = DEFAULT_PRIOR_SIGMAS[0]
    RAAN_DEG: float = DEFAULT_PRIOR_SIGMAS[1]
    ECCENTRICITY: float = DEFAULT_PRIOR_SIGMAS[2]
    ARGP_DEG: float = DEFAULT_PRIOR_SIGMAS[3]
    MEAN_ANOMALY_DEG: float = DEFAULT_PRIOR_SIGMAS[4]
    MEAN_MOTION_REV_DAY: float = DEFAULT_PRIOR_SIGMAS[5]
    BSTAR: float = DEFAULT_PRIOR_SIGMAS[6]
    ARGP_PLUS_M_DEG: float = DEFAULT_SIGMA_ARGP_PLUS_M

    F_SCALE: float = 0.5
    MAX_NFEV: int = 200

    # Защита из algorithms.md §4.4: из одного прохода наблюдаемы примерно
    # две величины, и фит по нему даёт правдоподобный RMS при бессмысленных
    # элементах. Отказ здесь дешевле, чем разбор такого результата потом.
    MIN_ENABLED_POINTS: int = 20
    MIN_OBSERVATIONS: int = 2

    # Точек модельной кривой поверх водопада. Заменяет `ikhnosoniks`:
    # кривая идёт через весь проход, в том числе там, где точек нет.
    MODEL_CURVE_POINTS: int = 200
