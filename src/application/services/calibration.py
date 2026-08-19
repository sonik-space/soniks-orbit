"""Калибровка водопада и снятие доплера по размеченным человеком точкам.

Автоматического поиска трека здесь нет и не должно быть. Точки ставит только
человек: замер по размеченному корпусу из 15 проходов GEOSCAN 1 показал, что
искомый сигнал — широкая пакетная посылка у нуля смещения, а всё, что находил
построчный поиск гребня, было нескорректированной помехой. Подробности —
`docs/decisions/015-manual-only-track.md`.

Отсюда две обязанности модуля, и обе служат ручной разметке:

  - **калибровка** — рамка осей, деления времени и отображение
    пиксель ↔ (время, смещение). Без неё клик по картинке не превратить
    в измерение;
  - **снятие доплера** — `f_abs_hz`, RMS и диагностика конвенции по набору
    точек, откуда бы он ни пришёл.

Правило 8 в силе: если эта последовательность появилась ещё где-то, это ошибка.
Golden-тесты зовут отсюда, а не держат свою копию.

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
)
from domain.waterfall.metadata import WaterfallMeta, parse_iso

# Как смещение на водопаде связано с принятой частотой.
#
# Две независимые двоичные неизвестные: велась ли доплеровская коррекция при
# записи и в какую сторону растёт ось частот. Ни та, ни другая из метаданных
# не выводится, поэтому обе **измеряются** по самим данным.
#
# Замер по разметке человека на 15 станциях: коэффициент регрессии смещения
# на предсказанный доплер равен нулю на **всех** станциях, то есть коррекция
# при записи ведётся всегда и является свойством сети, а не настройкой станции
# (decisions/015). `f_abs_hz` считается одной формулой, а перебор остаётся
# диагностикой: запас порядка единицы означает, что варианты неразличимы,
# то есть разметке верить нельзя (algorithms.md §3).
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
        # Область данных — внутренность рамки.
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
    # ponytail: `source` теперь всегда "manual" — автоматических точек больше
    # нет. Поле оставлено, потому что оно лежит в JSONB уже размеченных
    # наблюдений; выпиливать его — отдельная миграция, а не побочный эффект.
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
    """Снятие доплера и оценка набора точек.

    Живёт здесь, а не в двух местах, ровно по правилу 9: две реализации
    снятия доплер-коррекции обязательно разойдутся, и расхождение вылезет
    как необъяснимый вклад в невязки.
    """

    f_abs_hz: np.ndarray
    v_km_s: np.ndarray
    sgp4_errors: int = 0
    convention: str | None = None
    margin: float | None = None
    rms_khz: float | None = None
    carrier_hz: float | None = None
    age_days: float | None = None

    def diagnostics(self) -> dict:
        """То, что доезжает до UI помимо самих точек.

        При пустом треке числовые поля **отсутствуют**, а не равны нулю:
        ноль читался бы как измеренное значение. Пустой трек — штатное
        состояние свежего наблюдения: его ещё не разметили.
        """
        margin = self.margin
        return {
            "rms_khz": self.rms_khz,
            "carrier_hz": self.carrier_hz,
            "convention": self.convention,
            "margin": None if margin == float("inf") else margin,
            # Запас порядка единицы означает, что четыре конвенции неразличимы,
            # то есть неверна сама абсолютная частота точек.
            "reliable": margin is not None and margin >= 2.0,
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


@dataclass(frozen=True)
class Calibrated:
    """Результат разбора картинки: отображение пиксель ↔ данные и сырьё
    для golden-тестов. Точек здесь нет — их ставит человек."""

    calibration: Calibration
    meta: WaterfallMeta
    shape: tuple[int, ...]
    box: AxesBox
    ticks: np.ndarray


def calibrate_observation(rgb: np.ndarray, meta: WaterfallMeta, obs: dict) -> Calibrated:
    """Разбор картинки одного наблюдения: рамка, деления, оси.

    Дальше водопад показывается человеку как есть, и всё, что на нём есть,
    определяет он сам.
    """
    box = detect_axes_box(rgb)
    ticks = detect_time_ticks(rgb, box)

    start, end = parse_iso(obs["start"]), parse_iso(obs["end"])
    t_bottom_mjd, sec_per_px = calibrate_time(
        ticks, box, meta.t_ref, (end - start).total_seconds()
    )

    return Calibrated(
        calibration=Calibration.of(rgb.shape, box, meta, t_bottom_mjd, sec_per_px),
        meta=meta,
        shape=tuple(rgb.shape),
        box=box,
        ticks=ticks,
    )


async def run_calibration(
    *,
    images: WaterfallImages,
    repo: SessionRepository,
    transaction: Transaction,
    track: ObservationTrack,
) -> None:
    """Калибровка одного наблюдения сессии: от загрузки PNG до записи осей.

    Точки не трогаются вовсе. Наблюдение приезжает в сессию с пустым треком
    и ждёт человека — это норма, а не ошибка.

    Непригодное наблюдение (`CalibrationError`: нет `satnogs:wf-dat`, не нашлась
    рамка или colorbar) — это `failed` с внятной причиной, а не падение воркера:
    для наблюдений до июля 2026 такое состояние **ожидаемо** (api.md, про 422).
    """
    # В ветках отказа прежний блок передаётся обратно: неудачная калибровка
    # не должна уносить с собой уже поставленные точки.
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
        result = calibrate_observation(rgb, meta, track.meta)
    except CalibrationError as exc:
        await repo.save_extraction(
            track.uuid, status="failed", error=str(exc), **previous
        )
        await transaction.commit()
        return

    await repo.save_extraction(
        track.uuid,
        status="ok",
        error=None,
        calibration=result.calibration.to_dict(),
        points=track.points,
        diagnostics=track.diagnostics,
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
    единицы, разметке верить нельзя.
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
