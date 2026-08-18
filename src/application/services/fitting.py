"""Сшивка фита: точки из JSONB → сегменты ядра → элементы, TLE и невязки.

Единственное место, где это происходит, — как `extraction.py` для извлечения
(правило 8). Если сборка сегментов или разбор невязок появились где-то ещё,
это ошибка, а не оптимизация.

Единицы (правило 2): ядро работает в **кГц** и **MJD**, хранение и API —
в **герцах** и ISO 8601. Пересчёт живёт здесь.
"""

from __future__ import annotations

import datetime as dt

import numpy as np

from application.dtos.common import ElementsSchema, TleSchema
from application.dtos.fit import (
    FitRunResponse,
    FitRunSummaryResponse,
    PerObservationFitResponse,
    PriorSigmasSchema,
    ResidualsResponse,
)
from application.dtos.session import (
    CalibrationResponse,
    LatestFitResponse,
    ModelCurveResponse,
)
from core.configs.fit import FitSettings
from domain.models import FitRun, ObservationTrack, TleLines
from domain.od.doppler import fac as doppler_fac
from domain.od.elements import Elements
from domain.od.fit import PARAM_NAMES, FitResult, Segment
from domain.od.geometry import range_rate
from domain.od.tle import to_lines

MJD_UNIX_EPOCH = 40587.0

# Имя поля запроса → индекс параметра в `PARAM_NAMES`. Единственная таблица
# соответствия: имена api.md человеческие (`eccentricity`), имена ядра
# повторяют `rffit` (`ecc`).
SIGMA_FIELDS: tuple[tuple[str, str], ...] = (
    ("inclination_deg", "incl_deg"),
    ("raan_deg", "raan_deg"),
    ("eccentricity", "ecc"),
    ("argp_deg", "argp_deg"),
    ("mean_anomaly_deg", "ma_deg"),
    ("mean_motion_rev_day", "rev_per_day"),
    ("bstar", "bstar"),
)

assert set(PARAM_NAMES) == {core for _, core in SIGMA_FIELDS}, (
    "таблица SIGMA_FIELDS разошлась с PARAM_NAMES ядра"
)


def prior_sigmas(
    request: PriorSigmasSchema | None,
    settings: FitSettings,
    *,
    priors_off: bool = False,
) -> tuple[np.ndarray, float]:
    """Семь σ в порядке `PARAM_NAMES` плюс σ на `argp + M`.

    Незаданное поле берётся из конфигурации, а не заменяется нулём: σ = 0
    означала бы жёстко зажатый параметр, чего в decisions/004 нет.

    `priors_off` — σ = ∞: приорный член вектора невязок обнуляется, потому что
    `(a − a_seed)/∞ = 0`. Масштаб параметров при этом **не уезжает**: он
    отдельная величина (`PARAM_SCALE`, см. шапку `domain/od/fit.py`), и именно
    поэтому выключение приоров здесь безопасно, а объединённая формула
    из algorithms.md §4.1 давала бы ecc = 0.4995.
    """
    if priors_off:
        return np.full(7, np.inf), float("inf")

    values = [
        getattr(request, field, None) if request else None for field, _ in SIGMA_FIELDS
    ]
    defaults = [
        settings.INCLINATION_DEG,
        settings.RAAN_DEG,
        settings.ECCENTRICITY,
        settings.ARGP_DEG,
        settings.MEAN_ANOMALY_DEG,
        settings.MEAN_MOTION_REV_DAY,
        settings.BSTAR,
    ]
    sigmas = np.array(
        [d if v is None else v for v, d in zip(values, defaults)], dtype=float
    )

    argp_plus_m = settings.ARGP_PLUS_M_DEG
    if request is not None and request.argp_plus_m_deg is not None:
        argp_plus_m = request.argp_plus_m_deg
    return sigmas, argp_plus_m


def sigmas_to_dict(sigmas: np.ndarray, argp_plus_m: float) -> dict[str, float] | None:
    """Блок для `od_fit_runs.config`: без сохранённых σ прогон невоспроизводим.

    При выключенных приорах — `None`, а не словарь бесконечностей: `Infinity`
    не сериализуется в JSON стандартным кодировщиком, и в JSONB такой прогон
    просто не записался бы. Флаг `priors_off` рядом в том же `config`.
    """
    if not np.all(np.isfinite(sigmas)):
        return None
    block = {field: float(sigmas[i]) for i, (field, _) in enumerate(SIGMA_FIELDS)}
    block["argp_plus_m_deg"] = float(argp_plus_m)
    return block


def build_segments(
    tracks: list[ObservationTrack],
) -> tuple[list[Segment], dict[int, list[int]]]:
    """Сегменты ядра из наблюдений сессии и исходные индексы их точек.

    Один сегмент — одно наблюдение, то есть одна несущая (decisions/003).
    Берутся только включённые точки: снятые человеком не удаляются, а гасятся,
    и в фит они не идут.

    Второе значение — индексы взятых точек в блоке `points` наблюдения.
    Без них невязки не разложить обратно индекс-в-индекс.
    """
    segments: list[Segment] = []
    used: dict[int, list[int]] = {}

    for track in tracks:
        points = track.points or {}
        enabled = points.get("enabled") or []
        indices = [i for i, on in enumerate(enabled) if on]
        if not indices:
            continue

        meta = track.meta
        segments.append(
            Segment(
                mjd=np.array([points["mjd"][i] for i in indices], dtype=float),
                # Ядро считает в кГц, хранение — в герцах (правило 2).
                f_khz=np.array(
                    [points["f_abs_hz"][i] / 1000.0 for i in indices], dtype=float
                ),
                weight=np.array([points["weight"][i] for i in indices], dtype=float),
                lat_deg=float(meta["station_lat"]),
                lng_deg=float(meta["station_lng"]),
                # API отдаёт метры, ядро ждёт км — как в `measure_points`.
                alt_km=float(meta["station_alt"]) / 1000.0,
                key=str(track.observation_id),
            )
        )
        used[track.observation_id] = indices

    return segments, used


def scatter_residuals(
    result: FitResult,
    segments: list[Segment],
    used: dict[int, list[int]],
    tracks: list[ObservationTrack],
) -> dict[int, dict]:
    """Плоский вектор невязок обратно по наблюдениям, индекс-в-индекс.

    `residual_khz` длиной с `points` наблюдения, `null` на выключенных точках:
    ноль читался бы как измеренная невязка. `mjd` идёт рядом, чтобы панель
    невязок не запрашивала треки всех наблюдений по отдельности.
    """
    by_key = {}
    at = 0
    for segment in segments:
        by_key[segment.key] = result.residuals_khz[at : at + segment.mjd.size]
        at += segment.mjd.size

    out: dict[int, dict] = {}
    for track in tracks:
        indices = used.get(track.observation_id)
        if indices is None:
            continue

        mjd = (track.points or {})["mjd"]
        column: list[float | None] = [None] * len(mjd)
        for position, index in enumerate(indices):
            column[index] = float(by_key[str(track.observation_id)][position])
        out[track.observation_id] = {"mjd": list(mjd), "residual_khz": column}

    return out


def model_curve(
    elements: Elements,
    carrier_khz: float,
    calibration: dict,
    n_points: int,
) -> ModelCurveResponse | None:
    """Модельная кривая на равномерной сетке времени водопада.

    Заменяет `ikhnosoniks`: кривая идёт через весь проход, в том числе там,
    где точек нет. Считается на сервере одной векторной прогонкой SGP4 —
    фронт доплер не снимает и абсолютную частоту не вычисляет (правило 9).

    Сетка берётся из калибровки, а не из точек: у наблюдения без трека
    её всё равно надо чем-то нарисовать.
    """
    t0 = calibration["t_bottom_mjd"]
    t1 = t0 + (calibration["plot_h"] - 1) * calibration["sec_per_px"] / 86400.0
    mjd = np.linspace(t0, t1, n_points)

    v_km_s, err = range_rate(
        elements.to_satrec(),
        mjd,
        calibration["station_lat"],
        calibration["station_lng"],
        calibration["station_alt_km"],
    )
    if np.any(err != 0):
        return None

    f_abs_hz = doppler_fac(v_km_s) * carrier_khz * 1000.0
    # Обратно к оси водопада той же формулой ядра: f_abs = f_центра − f_смещение.
    f_offset_hz = calibration["center_freq_hz"] - f_abs_hz
    return ModelCurveResponse(mjd=mjd.tolist(), f_offset_hz=f_offset_hz.tolist())


def calibration_schema(raw: dict | None) -> CalibrationResponse | None:
    """Блок калибровки из JSONB в форму API.

    Границы оси времени отдаются в ISO: MJD — внутренний формат ядра, наружу
    время идёт как ISO 8601 UTC (правило 2). Имена полей тоже расходятся
    (`samp_rate_hz` против `samp_rate`), поэтому мэппинг обязан быть один:
    его зовут и трек наблюдения сессии, и трек задания идентификации.
    """
    if not raw:
        return None

    t_min = raw["t_bottom_mjd"]
    t_max = t_min + (raw["plot_h"] - 1) * raw["sec_per_px"] / 86400.0
    return CalibrationResponse(
        img_w=raw["img_w"],
        img_h=raw["img_h"],
        plot_left=raw["plot_left"],
        plot_top=raw["plot_top"],
        plot_w=raw["plot_w"],
        plot_h=raw["plot_h"],
        t_min=iso_from_mjd(t_min),
        t_max=iso_from_mjd(t_max),
        f_min_hz=raw["f_min_hz"],
        f_max_hz=raw["f_max_hz"],
        center_freq_hz=raw["center_freq_hz"],
        samp_rate=raw["samp_rate_hz"],
        nchan=raw["nchan"],
        bin_hz=raw["bin_hz"],
    )


def curve_inputs(track: ObservationTrack) -> dict | None:
    """Калибровка плюс площадка наблюдения — всё, что нужно `model_curve`."""
    if not track.calibration:
        return None
    return {
        **track.calibration,
        "station_lat": float(track.meta["station_lat"]),
        "station_lng": float(track.meta["station_lng"]),
        "station_alt_km": float(track.meta["station_alt"]) / 1000.0,
    }


def to_tle(elements: Elements, seed: TleLines) -> TleLines:
    """Строки TLE результата.

    Международное обозначение переносится из затравки: в `Elements` его нет,
    оно не участвует в движении, но без него опубликованное TLE теряет
    паспортное поле.
    """
    line1, line2 = to_lines(elements, intldes=seed.tle1[9:17].strip())
    return TleLines(tle0=seed.tle0, tle1=line1, tle2=line2)


def elements_to_dict(elements: Elements) -> dict:
    return {
        "inclination_deg": elements.incl_deg,
        "raan_deg": elements.raan_deg,
        "eccentricity": elements.ecc,
        "argp_deg": elements.argp_deg,
        "mean_anomaly_deg": elements.ma_deg,
        "mean_motion_rev_day": elements.rev_per_day,
        "bstar": elements.bstar,
        "epoch_mjd": elements.epoch_mjd,
    }


def elements_from_dict(block: dict) -> Elements:
    """Обратно к `elements_to_dict`. Нужна порогу публикации: он сравнивает
    результат с затравкой **того прогона**, а не с текущей затравкой сессии,
    которую оператор с фазы 7 может менять."""
    return Elements(
        incl_deg=block["inclination_deg"],
        raan_deg=block["raan_deg"],
        ecc=block["eccentricity"],
        argp_deg=block["argp_deg"],
        ma_deg=block["mean_anomaly_deg"],
        rev_per_day=block["mean_motion_rev_day"],
        bstar=block["bstar"],
        epoch_mjd=block["epoch_mjd"],
    )


def elements_schema(block: dict) -> ElementsSchema:
    """Наружу эпоха идёт в ISO: MJD — внутренний формат ядра (правило 2)."""
    return ElementsSchema(
        inclination_deg=block["inclination_deg"],
        raan_deg=block["raan_deg"],
        eccentricity=block["eccentricity"],
        argp_deg=block["argp_deg"],
        mean_anomaly_deg=block["mean_anomaly_deg"],
        mean_motion_rev_day=block["mean_motion_rev_day"],
        bstar=block["bstar"],
        epoch=iso_from_mjd(block["epoch_mjd"]),
    )


def residuals_schema(block: dict) -> dict[int, ResidualsResponse]:
    return {
        int(observation_id): ResidualsResponse(**columns)
        for observation_id, columns in block.items()
    }


def fit_run_response(run: FitRun) -> FitRunResponse:
    return FitRunResponse(
        fit_run_id=run.uuid,
        created_at=run.created_at,
        status=run.status,
        rms_khz=run.rms_khz,
        rms_pre_khz=run.rms_pre_khz,
        n_points=run.n_points,
        elements_in=elements_schema(run.elements_in),
        elements_out=elements_schema(run.elements_out),
        prior_dominated=run.prior_dominated,
        tle=TleSchema(tle0=run.tle.tle0, tle1=run.tle.tle1, tle2=run.tle.tle2),
        per_observation=[
            PerObservationFitResponse(**block) for block in run.per_observation
        ],
        residuals=residuals_schema(run.residuals),
        config=run.config,
    )


def fit_run_summary(run: FitRun) -> FitRunSummaryResponse:
    return FitRunSummaryResponse(
        fit_run_id=run.uuid,
        created_at=run.created_at,
        status=run.status,
        rms_khz=run.rms_khz,
        rms_pre_khz=run.rms_pre_khz,
        n_points=run.n_points,
        elements_out=elements_schema(run.elements_out),
        prior_dominated=run.prior_dominated,
    )


def latest_fit_response(run: FitRun) -> LatestFitResponse:
    return LatestFitResponse(
        fit_run_id=run.uuid,
        status=run.status,
        rms_khz=run.rms_khz,
        elements_out=elements_schema(run.elements_out),
        tle=TleSchema(tle0=run.tle.tle0, tle1=run.tle.tle1, tle2=run.tle.tle2),
    )


def iso_from_mjd(mjd: float) -> dt.datetime:
    return dt.datetime.fromtimestamp((mjd - MJD_UNIX_EPOCH) * 86400.0, tz=dt.UTC)


def mjd_from_iso(when: dt.datetime) -> float:
    """Обратно к `iso_from_mjd`. Стоит рядом с ним, а не в новом модуле:
    четвёртая копия `MJD_UNIX_EPOCH` в проекте разошлась бы с первыми тремя.

    Метка без зоны считается UTC: во всём API время — UTC (правило 2),
    а `timestamp()` у наивной метки взял бы зону машины.
    """
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    return MJD_UNIX_EPOCH + when.timestamp() / 86400.0


def dominated_names(result: FitResult) -> list[str]:
    """Имена api.md вместо имён ядра: `prior_dominated` едет прямо в UI."""
    core_to_api = {core: api for api, core in SIGMA_FIELDS}
    return [core_to_api[name] for name in result.prior_dominated if name in core_to_api]
