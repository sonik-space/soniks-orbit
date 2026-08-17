"""Единственное место сшивки «PNG → калибровка → гребень → снятие доплера».

Правило 8: если эта последовательность появилась ещё где-то, это ошибка,
а не оптимизация. Стенды `scripts/phase0/end_to_end.py` и `scripts/phase1/sweep.py`
и golden-тесты зовут отсюда, а не держат свою копию — иначе тест проверял бы
не то, что считает боевой код.

Ввода-вывода здесь нет: декодирование PNG — это инфраструктура
(`infrastructure/images/loader.py`), а сюда приходят уже готовые `np.ndarray`
и разобранные метаданные.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from application.interfaces.image_fetcher import WaterfallImages
from application.interfaces.repositories import SessionRepository
from application.interfaces.transaction import Transaction
from domain.models import ObservationTrack
from domain.od.constants import C_KM_S
from domain.od.doppler import fac as doppler_fac
from domain.od.doppler import received_freq_hz
from domain.od.elements import Elements
from domain.od.fit import profile_carrier, rms_khz
from domain.od.geometry import range_rate
from domain.waterfall import CalibrationError
from domain.waterfall.axes import (
    AxesBox,
    calibrate_time,
    detect_axes_box,
    detect_time_ticks,
    freq_offset_hz,
)
from domain.waterfall.colormap import decode_intensity, lut_from_colorbar
from domain.waterfall.metadata import WaterfallMeta, parse_iso
from domain.waterfall.ridge import (
    Ridge,
    dc_mask,
    extract_ridge,
    peak_width_limits_px,
)

# Минимальный размах частоты трека. Доплер за проход на 435 МГц проходит
# 16 кГц даже на низкой элевации (замер на 1527888, 22°), а стационарная
# помеха — доли килогерца. Порог отсекает вторую, не задевая первый.
MIN_TRACK_SPAN_HZ = 2000.0

DEFAULT_SNR_THRESHOLD = 4.0
DEFAULT_BIN_SECONDS = 1.0

# Как смещение на водопаде связано с принятой частотой.
#
# Две независимые двоичные неизвестные: велась ли доплеровская коррекция при
# записи и в какую сторону растёт ось частот. Ни та, ни другая из метаданных
# не выводится, поэтому обе **измеряются** по самим данным.
#
# Замер по корпусу закрыл открытый вопрос 9: выигрывает «сырой, ось
# инвертирована» на всех извлечённых наблюдениях восьми станций, и именно
# он лежит в ядре как `received_freq_hz`. Отсюда `f_abs_hz` считается **одной**
# формулой, а перебор остаётся диагностикой: запас порядка единицы означает,
# что варианты неразличимы, то есть трек ненадёжен, и это показывается
# пользователю (algorithms.md §3).
PRODUCTION_CONVENTION = "сырой, ось инвертирована"

AXIS_MODELS = {
    "сырой, ось прямая": lambda cf, fo, v: cf + fo,
    PRODUCTION_CONVENTION: lambda cf, fo, v: received_freq_hz(cf, fo),
    "доплер снят, ось прямая": lambda cf, fo, v: cf + fo - cf * v / C_KM_S,
    "доплер снят, ось инвертирована": lambda cf, fo, v: cf - fo - cf * v / C_KM_S,
}


@dataclass(frozen=True)
class Calibration:
    """Всё, что нужно фронту, чтобы обрезать картинку по рамке и линейно
    отображать экран в данные. Своей геометрии фронт не вычисляет (frontend.md).

    Кладётся в `od_session_observations.calibration` и отдаётся `GET .../track`.
    """

    img_w: int
    img_h: int
    plot_left: int
    plot_top: int
    plot_w: int
    plot_h: int
    f_min_hz: float
    f_max_hz: float
    center_freq_hz: float
    samp_rate_hz: int
    nchan: int
    bin_hz: float
    t_bottom_mjd: float
    sec_per_px: float

    @classmethod
    def of(
        cls,
        shape: tuple[int, ...],
        box: AxesBox,
        meta: WaterfallMeta,
        t_bottom_mjd: float,
        sec_per_px: float,
    ) -> Calibration:
        # Область данных — внутренность рамки, ровно те же срезы, по которым
        # считается интенсивность в `colormap.decode_intensity`.
        return cls(
            img_w=int(shape[1]),
            img_h=int(shape[0]),
            plot_left=box.left + 1,
            plot_top=box.top + 1,
            plot_w=box.width,
            plot_h=box.height,
            # Ось несимметрична: клиент строит сетку с `endpoint=False`,
            # поэтому верхний канал это `samp_rate/2 − bin_hz` (algorithms.md §1.2).
            f_min_hz=-meta.samp_rate_hz / 2.0,
            f_max_hz=meta.samp_rate_hz / 2.0 - meta.bin_hz,
            center_freq_hz=meta.center_freq_hz,
            samp_rate_hz=meta.samp_rate_hz,
            nchan=meta.nchan,
            bin_hz=meta.bin_hz,
            t_bottom_mjd=t_bottom_mjd,
            sec_per_px=sec_per_px,
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TrackPoints:
    """Точки трека колонками-массивами (data-model.md).

    Все массивы одной длины, индекс — идентификатор точки. Пара
    `(observation_id, index)` — ключ выделения во всём UI.
    """

    mjd: np.ndarray = field(default_factory=lambda: np.array([]))
    f_abs_hz: np.ndarray = field(default_factory=lambda: np.array([]))
    f_offset_hz: np.ndarray = field(default_factory=lambda: np.array([]))
    snr: np.ndarray = field(default_factory=lambda: np.array([]))
    weight: np.ndarray = field(default_factory=lambda: np.array([]))
    enabled: np.ndarray = field(default_factory=lambda: np.array([], dtype=bool))
    source: tuple[str, ...] = ()

    def __len__(self) -> int:
        return int(self.mjd.size)

    def to_columns(self) -> dict:
        """Блок для JSONB. Пишется и читается целиком, одним UPDATE."""
        return {
            "mjd": self.mjd.tolist(),
            "f_abs_hz": self.f_abs_hz.tolist(),
            "f_offset_hz": self.f_offset_hz.tolist(),
            "snr": self.snr.tolist(),
            "weight": self.weight.tolist(),
            "enabled": self.enabled.tolist(),
            "source": list(self.source),
        }


@dataclass(frozen=True)
class Measurement:
    """Снятие доплера и оценка набора точек — то, что считается **одинаково**
    для автоматического извлечения и для трека, поправленного руками.

    Живёт здесь, а не в двух местах, ровно по правилу 9: две реализации
    снятия доплер-коррекции обязательно разойдутся, и расхождение вылезет
    как необъяснимый вклад в невязки у ручных точек.
    """

    f_abs_hz: np.ndarray
    v_km_s: np.ndarray
    sgp4_errors: int = 0
    convention: str | None = None
    margin: float | None = None
    rms_khz: float | None = None
    carrier_hz: float | None = None
    age_days: float | None = None

    def diagnostics(self, overlay_frac: float = 0.0) -> dict:
        """То, что доезжает до UI помимо самих точек.

        При пустом треке числовые поля **отсутствуют**, а не равны нулю:
        ноль читался бы как измеренное значение.
        """
        margin = self.margin
        return {
            "rms_khz": self.rms_khz,
            "carrier_hz": self.carrier_hz,
            "convention": self.convention,
            "margin": None if margin == float("inf") else margin,
            # Запас порядка единицы означает, что четыре конвенции неразличимы,
            # то есть трек ненадёжен. Один ложный трек в корпусе (1527002)
            # выдаёт себя именно так, и это штатная диагностика, а не молчание.
            "reliable": margin is not None and margin >= 2.0,
            "overlay_frac": overlay_frac,
            "sgp4_errors": self.sgp4_errors,
            "age_days": self.age_days,
        }


def measure_points(
    obs: dict,
    center_freq_hz: float,
    mjd: np.ndarray,
    f_offset_hz: np.ndarray,
    weight: np.ndarray,
) -> Measurement:
    """Абсолютная частота и диагностика для набора точек.

    `obs` — замороженный снимок ответа API (правило 10): доплер снимается
    по тому TLE, которое было у наблюдения в момент записи.

    Пустой набор — не ошибка: возвращается измерение без чисел.
    """
    if mjd.size == 0:
        empty = np.array([])
        return Measurement(f_abs_hz=empty, v_km_s=empty)

    tle = obs["tle"]
    seed = Elements.from_tle(tle["tle1"], tle["tle2"])
    v_km_s, err = range_rate(
        seed.to_satrec(),
        mjd,
        float(obs["station_lat"]),
        float(obs["station_lng"]),
        float(obs["station_alt"]) / 1000.0,  # API отдаёт метры, ядро ждёт км
    )
    if np.any(err != 0):
        return Measurement(
            f_abs_hz=np.array([]),
            v_km_s=np.array([]),
            sgp4_errors=int(np.sum(err != 0)),
        )

    convention, margin, rms, carrier_khz = _score_conventions(
        center_freq_hz, f_offset_hz, v_km_s, weight
    )
    return Measurement(
        f_abs_hz=received_freq_hz(center_freq_hz, f_offset_hz),
        v_km_s=v_km_s,
        convention=convention,
        margin=margin,
        rms_khz=rms,
        carrier_hz=carrier_khz * 1000.0,
        age_days=float(mjd.mean() - seed.epoch_mjd),
    )


def merge_manual(previous: dict | None, fresh: dict) -> dict:
    """Ручные точки переживают повторное извлечение, автоматические заменяются.

    Порядок восстанавливается по `mjd`: индекс точки — её идентификатор
    в UI, и набор без сортировки читался бы как случайный.
    """
    manual = [
        i for i, src in enumerate(previous["source"]) if src == "manual"
    ] if previous else []
    if not manual:
        return fresh

    merged = {
        key: [*fresh[key], *(previous[key][i] for i in manual)] for key in fresh
    }
    order = sorted(range(len(merged["mjd"])), key=lambda i: merged["mjd"][i])
    return {key: [column[i] for i in order] for key, column in merged.items()}


@dataclass(frozen=True)
class Extraction:
    """Результат извлечения: точки, калибровка и диагностика.

    Пустой трек — **нормальное** состояние, а не ошибка (decisions/001):
    на корпусе так на 12 наблюдениях из 23. Исключений здесь нет.
    """

    points: TrackPoints
    calibration: Calibration

    # Диагностика, которая доезжает до UI. При пустом треке она не «нулевая»,
    # а отсутствующая: ноль читался бы как измеренное значение.
    convention: str | None = None
    margin: float | None = None
    rms_khz: float | None = None
    carrier_hz: float | None = None
    sgp4_errors: int = 0

    # Сырьё для стендов и golden-тестов.
    meta: WaterfallMeta | None = None
    shape: tuple[int, ...] = ()
    box: AxesBox | None = None
    ticks: np.ndarray = field(default_factory=lambda: np.array([]))
    lut_len: int = 0
    overlay_frac: float = 0.0
    width_limits_px: tuple[float, float] = (0.0, 0.0)
    ridge: Ridge | None = None
    v_km_s: np.ndarray = field(default_factory=lambda: np.array([]))
    age_days: float | None = None

    @property
    def reliable(self) -> bool:
        """Запас порядка единицы означает, что четыре конвенции неразличимы,
        то есть трек ненадёжен. Один ложный трек в корпусе (1527002) выдаёт
        себя именно так, и это штатная диагностика, а не молчание."""
        return self.margin is not None and self.margin >= 2.0

    def diagnostics(self) -> dict:
        """То, что доезжает до UI помимо самих точек.

        Форма блока одна на весь сервис и живёт в `Measurement`: после правки
        трека руками её собирает `PUT .../track` по тем же полям.
        """
        return Measurement(
            f_abs_hz=self.points.f_abs_hz,
            v_km_s=self.v_km_s,
            sgp4_errors=self.sgp4_errors,
            convention=self.convention,
            margin=self.margin,
            rms_khz=self.rms_khz,
            carrier_hz=self.carrier_hz,
            age_days=self.age_days,
        ).diagnostics(self.overlay_frac)


def extract_track(
    rgb: np.ndarray,
    meta: WaterfallMeta,
    obs: dict,
    *,
    snr_threshold: float = DEFAULT_SNR_THRESHOLD,
    bin_seconds: float = DEFAULT_BIN_SECONDS,
) -> Extraction:
    """Вся цепочка на одном наблюдении.

    `obs` — ответ Django API целиком, тот же, что замораживается в
    `od_session_observations.meta` (правило 10): доплер снимается по TLE,
    которое было у наблюдения в момент записи, и без снимка пересчёт
    по обновлённому TLE изменил бы смысл уже посчитанных `f_abs_hz`.
    """
    box = detect_axes_box(rgb)
    ticks = detect_time_ticks(rgb, box)
    lut = lut_from_colorbar(rgb, box)
    z, overlay = decode_intensity(rgb, box, lut)

    start, end = parse_iso(obs["start"]), parse_iso(obs["end"])
    t_bottom_mjd, sec_per_px = calibrate_time(
        ticks, box, meta.t_ref, (end - start).total_seconds()
    )

    limits = peak_width_limits_px(
        box.width, meta.nchan, meta.samp_rate_hz, meta.bw_99_hz
    )
    ridge = extract_ridge(
        z,
        bin_rows=max(round(bin_seconds / sec_per_px), 1),
        width_limits_px=limits,
        dc_cols=dc_mask(box.width, meta.samp_rate_hz, meta.nchan),
        snr_threshold=snr_threshold,
        chain_min_span_px=MIN_TRACK_SPAN_HZ * box.width / meta.samp_rate_hz,
    )

    common = {
        "calibration": Calibration.of(rgb.shape, box, meta, t_bottom_mjd, sec_per_px),
        "meta": meta,
        "shape": tuple(rgb.shape),
        "box": box,
        "ticks": ticks,
        "lut_len": len(lut),
        "overlay_frac": float(overlay.mean()),
        "width_limits_px": limits,
        "ridge": ridge,
    }
    if ridge.row_px.size == 0:
        return Extraction(points=TrackPoints(), **common)

    mjd = t_bottom_mjd + ridge.row_px * sec_per_px / 86400.0
    f_offset = freq_offset_hz(ridge.col_px, box.width, meta.samp_rate_hz, meta.nchan)

    m = measure_points(obs, meta.center_freq_hz, mjd, f_offset, ridge.weight)
    if m.sgp4_errors:
        return Extraction(
            points=TrackPoints(), sgp4_errors=m.sgp4_errors, **common
        )

    n = ridge.row_px.size
    return Extraction(
        points=TrackPoints(
            mjd=mjd,
            f_abs_hz=m.f_abs_hz,
            f_offset_hz=f_offset,
            snr=ridge.snr,
            weight=ridge.weight,
            enabled=np.ones(n, dtype=bool),
            source=("auto",) * n,
        ),
        convention=m.convention,
        margin=m.margin,
        rms_khz=m.rms_khz,
        carrier_hz=m.carrier_hz,
        v_km_s=m.v_km_s,
        age_days=m.age_days,
        **common,
    )


async def run_extraction(
    *,
    images: WaterfallImages,
    repo: SessionRepository,
    transaction: Transaction,
    track: ObservationTrack,
    snr_threshold: float = DEFAULT_SNR_THRESHOLD,
    bin_seconds: float = DEFAULT_BIN_SECONDS,
) -> None:
    """Извлечение по одному наблюдению сессии, от загрузки PNG до записи точек.

    Снимок ответа API уже заморожен в `track.meta` (правило 10), поэтому
    доплер снимается по тому TLE, которое было у наблюдения в момент записи,
    сколько бы раз задачу ни перезапускали.

    Непригодное наблюдение (`CalibrationError`: нет `satnogs:wf-dat`, не нашлась
    рамка или colorbar) — это `failed` с внятной причиной, а не падение воркера:
    для наблюдений до июля 2026 такое состояние **ожидаемо** (api.md, про 422).
    Пустой трек — не ошибка вовсе, а `ok` с нулём точек (decisions/001):
    на корпусе так на 12 наблюдениях из 23.

    Повторный запуск с другими параметрами (`POST .../reextract`) заменяет
    автоматические точки и **сохраняет ручные**: `track` прочитан до того,
    как статус `running` затёр блок, поэтому прежняя разметка ещё в памяти.
    """
    # В ветках отказа прежний блок передаётся обратно: неудачный повтор
    # извлечения не должен уносить с собой ручную разметку и калибровку.
    previous = {
        "calibration": track.calibration,
        "points": track.points,
        "diagnostics": track.diagnostics,
    }

    url = track.waterfall_url
    if not url:
        await repo.save_extraction(
            track.uuid, status="failed", error="у наблюдения нет водопада", **previous
        )
        await transaction.commit()
        return

    try:
        rgb, meta = await images.load(track.observation_id, url)
        result = extract_track(
            rgb,
            meta,
            track.meta,
            snr_threshold=snr_threshold,
            bin_seconds=bin_seconds,
        )
    except CalibrationError as exc:
        await repo.save_extraction(
            track.uuid, status="failed", error=str(exc), **previous
        )
        await transaction.commit()
        return

    # Пустой трек — это `ok` с нулём точек, а вот ненулевой код SGP4 означает,
    # что затравку нельзя прогнать на времена трека: пустота здесь от поломки,
    # а не от отсутствия сигнала, и подавать её как норму нельзя.
    points = merge_manual(track.points, result.points.to_columns())
    diagnostics = result.diagnostics()
    if len(points["mjd"]) != len(result.points):
        # Ручные точки пережили повтор, значит набор шире извлечённого.
        # RMS считается по нему же: иначе число описывало бы набор,
        # которого больше нет.
        m = measure_points(
            track.meta,
            result.calibration.center_freq_hz,
            np.asarray(points["mjd"]),
            np.asarray(points["f_offset_hz"]),
            np.asarray(points["weight"]),
        )
        points["f_abs_hz"] = m.f_abs_hz.tolist()
        diagnostics = m.diagnostics(result.overlay_frac)

    failed = result.sgp4_errors > 0
    await repo.save_extraction(
        track.uuid,
        status="failed" if failed else "ok",
        error=(
            f"SGP4 вернул коды ошибок на {result.sgp4_errors} точках"
            if failed
            else None
        ),
        calibration=result.calibration.to_dict(),
        points=points,
        diagnostics=diagnostics,
    )
    await transaction.commit()


def _score_conventions(
    center_freq_hz: float,
    f_offset_hz: np.ndarray,
    v_km_s: np.ndarray,
    weight: np.ndarray,
) -> tuple[str, float, float, float]:
    """Диагностика конвенции оси: победитель, запас до следующего, RMS и несущая.

    RMS и несущая возвращаются для **рабочей** формулы `received_freq_hz`,
    а не для победителя: формула в ядре одна. Победитель и запас нужны затем,
    чтобы расхождение было видно — если выигрывает не она или запас порядка
    единицы, трек ненадёжен.
    """
    fac = doppler_fac(v_km_s)
    scored = []
    for name, model in AXIS_MODELS.items():
        f_khz = model(center_freq_hz, f_offset_hz, v_km_s) / 1000.0
        carrier = profile_carrier(fac, f_khz, weight)
        scored.append((rms_khz(f_khz - fac * carrier), name, carrier))
    scored.sort()

    best_rms, best_name, _ = scored[0]
    production = next(s for s in scored if s[1] == PRODUCTION_CONVENTION)
    margin = scored[1][0] / best_rms if best_rms > 0 else float("inf")
    return best_name, margin, production[0], production[2]
