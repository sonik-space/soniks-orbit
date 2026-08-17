"""Калибровка водопада и извлечение доплеровского гребня.

Чистые функции над `np.ndarray`: ни PIL, ни HTTP. Декодирование PNG —
инфраструктура, а не алгоритм (правило 1), поэтому картинка приходит сюда
уже массивом.

Фаза 1 переносит эти функции в `domain/waterfall/{metadata,axes,colormap,ridge}.py`
перемещением, без переписывания.

Формулы — algorithms.md §1-2. Единицы: частоты в Гц, время в секундах
от начала оси, MJD появляется только на выходе.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import median_filter
from scipy.spatial import cKDTree

# Признак линии осей: чёрные и ненасыщенные. Наивный поиск «тёмных пикселей»
# не работает — нижний конец любой colormap тоже тёмный (algorithms.md §1.3).
SPINE_MAX_LEVEL = 90
SPINE_MAX_CHROMA = 20
SPINE_COVERAGE = 0.6

# Расстояние в RGB, дальше которого пиксель считается оверлеем, а не данными.
OVERLAY_DISTANCE = 30.0

COLORBAR_WIDTH_PX = (10, 60)


class CalibrationError(RuntimeError):
    """Картинка не поддаётся калибровке.

    Отдельный тип, потому что это ожидаемое состояние (наблюдение непригодно),
    а не поломка сервиса: в API ему соответствует 422, а в UI — объяснение,
    а не сообщение об ошибке.
    """


@dataclass(frozen=True)
class AxesBox:
    """Рамка области графика и colorbar в пикселях, включительно."""

    left: int
    right: int
    top: int
    bottom: int
    cb_left: int
    cb_right: int

    @property
    def width(self) -> int:
        return self.right - self.left - 1

    @property
    def height(self) -> int:
        return self.bottom - self.top - 1


def spine_mask(rgb: np.ndarray) -> np.ndarray:
    """Маска ахроматичных тёмных пикселей — линий осей и делений."""
    mx = rgb.max(axis=2).astype(np.int16)
    mn = rgb.min(axis=2).astype(np.int16)
    return (mx < SPINE_MAX_LEVEL) & ((mx - mn) < SPINE_MAX_CHROMA)


def _run_centers(frac: np.ndarray, threshold: float = SPINE_COVERAGE) -> np.ndarray:
    """Центры непрерывных серий, где доля выше порога.

    Линия толщиной в 1-2 пикселя даёт серию, а не одиночный индекс, поэтому
    брать надо центр, иначе рамка съедет на полпикселя.
    """
    hit = frac > threshold
    if not hit.any():
        return np.array([], dtype=float)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], hit.view(np.int8), [0]))))
    starts, ends = edges[0::2], edges[1::2]
    return (starts + ends - 1) / 2.0


def detect_axes_box(rgb: np.ndarray) -> AxesBox:
    """Рамка осей и colorbar.

    Хардкодить координаты нельзя: `bbox_inches="tight"` в клиенте плюс
    оверлеи с `clip_on=False` двигают область графика от картинки к картинке
    (замерено 823×1603, 832×1603, 841×1676). Старый tabulation-helper
    хардкодил `(66,1553)-(686,13)` и на этом ошибался (правило 4).

    Пара границ графика — **соседняя** пара вертикальных линий с наибольшим
    разносом. Именно соседняя: на боевом водопаде колонки идут
    `[81, 681, 743, 763]`, и наибольший разнос по всем парам дал бы
    `(81, 763)`, то есть график вместе с colorbar. Соседние разносы
    `600 / 62 / 20` выбирают `(81, 681)` верно.
    """
    h, w = rgb.shape[:2]
    spine = spine_mask(rgb)

    cols = _run_centers(spine.sum(axis=0) / h)
    rows = _run_centers(spine.sum(axis=1) / w)
    if cols.size < 2 or rows.size < 2:
        raise CalibrationError(
            f"рамка осей не найдена: вертикальных линий {cols.size}, "
            f"горизонтальных {rows.size}"
        )

    gaps = np.diff(cols)
    k = int(np.argmax(gaps))
    left, right = int(round(cols[k])), int(round(cols[k + 1]))

    top, bottom = int(round(rows[0])), int(round(rows[-1]))

    cb_left = cb_right = -1
    right_cols = cols[k + 2 :]
    for a, b in zip(right_cols[:-1], right_cols[1:]):
        if COLORBAR_WIDTH_PX[0] <= (b - a) <= COLORBAR_WIDTH_PX[1]:
            cb_left, cb_right = int(round(a)), int(round(b))
            break
    if cb_left < 0:
        raise CalibrationError(
            "colorbar не найден правее области графика — без него неоткуда "
            "взять таблицу цветов, а угадывать colormap нельзя"
        )

    box = AxesBox(left, right, top, bottom, cb_left, cb_right)

    if box.width < 0.3 * w or box.height < 0.3 * h:
        raise CalibrationError(
            f"область графика {box.width}×{box.height} слишком мала "
            f"для картинки {w}×{h}"
        )
    interior = rgb[box.top + 1 : box.bottom, box.left + 1 : box.right]
    if (interior.min(axis=2) > 240).mean() > 0.9:
        raise CalibrationError("внутренность рамки почти белая — рендер не удался")
    return box


def detect_time_ticks(rgb: np.ndarray, box: AxesBox, reach: int = 5) -> np.ndarray:
    """Строки делений оси времени, в координатах изображения.

    Клиент ставит их `MinuteLocator(interval=INTERVAL_IN_MINUTES)`, то есть
    строго на целых минутах. Это единственный способ привязать ось времени:
    границы оси — метки первой и последней строки данных, а `tabs[0]`
    в метаданные PNG не попадает (algorithms.md §1.4).

    Полоса поиска узкая и вплотную к рамке. Деление у matplotlib длиной
    3.5 пункта, при 100 dpi это ~5 px, и стоит оно прямо у оси. Если брать
    полосу шире, доля размывается ниже порога (замер: при reach=10 деление
    даёт 0.4 и не находится ни одно), а ещё левее начинаются подписи времени,
    которые тоже чёрные и ахроматичные.
    """
    band = spine_mask(rgb)[:, max(box.left - reach, 0) : box.left]
    if band.size == 0:
        return np.array([], dtype=float)
    return _run_centers(band.mean(axis=1), threshold=0.5)


def tick_step_px(ticks: np.ndarray) -> float:
    """Шаг делений, выведенный из данных.

    Шаг **не** считается равным минуте: при длинном проходе `MinuteLocator`
    выбирает другой интервал. Медиана, а не среднее, чтобы одно случайно
    склеившееся деление не сдвинуло масштаб.
    """
    if ticks.size < 2:
        raise CalibrationError(f"делений оси времени {ticks.size}, нужно хотя бы два")
    return float(np.median(np.diff(ticks)))


def lut_from_colorbar(rgb: np.ndarray, box: AxesBox) -> np.ndarray:
    """Таблица цветов из самого изображения, индекс 0 — минимум мощности.

    Ключевая находка: colorbar на картинке — это точная таблица, поэтому
    не нужно знать ни имя colormap, ни параметры `PowerNorm`. Хардкодить
    colormap нельзя категорически: в исходнике клиента стоит `jet`, а замер
    на боевом водопаде давал viridis.

    Поиску гребня нужен только **монотонный** прокси мощности, и он
    получается по построению — по положению в таблице.
    """
    strip = rgb[box.top + 1 : box.bottom, box.cb_left + 1 : box.cb_right]
    if strip.size == 0:
        raise CalibrationError("colorbar пуст")
    lut = strip.mean(axis=1)[::-1].astype(float)  # снизу вверх = от минимума
    if len(np.unique(lut.round(0), axis=0)) < 16:
        raise CalibrationError(
            f"в colorbar всего {len(np.unique(lut.round(0), axis=0))} различных "
            f"цветов — на таблицу не похоже"
        )
    return lut


def decode_intensity(
    rgb: np.ndarray, box: AxesBox, lut: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Монотонный прокси мощности в [0,1] и маска оверлеев.

    Расстояние до ближайшей записи таблицы бесплатно детектирует оверлеи —
    маркеры декодированных кадров, аннотацию девиации, кривые мешающих
    спутников: их цвета в таблице нет.
    """
    interior = rgb[box.top + 1 : box.bottom, box.left + 1 : box.right].astype(float)
    h, w = interior.shape[:2]
    dist, idx = cKDTree(lut).query(interior.reshape(-1, 3))
    z = (idx / (len(lut) - 1)).reshape(h, w)
    overlay = (dist > OVERLAY_DISTANCE).reshape(h, w)
    z = np.where(overlay, np.nan, z)
    return z[::-1], overlay[::-1]  # origin='lower': время снизу вверх


def freq_offset_hz(j_px: np.ndarray, width_px: int, samp_rate: int, nchan: int):
    """Смещение частоты по столбцу области графика, Гц.

    `extent` задаёт внешние края нарисованного массива, а его границы —
    координаты центров первого и последнего канала, поэтому доля `u`
    переводится сперва в индекс канала, и только потом в частоту
    (algorithms.md §1.5).

    Ось несимметрична: клиент строит сетку с `endpoint=False`, поэтому
    верхний канал это `samp_rate/2 − bin_hz`, а не `+samp_rate/2`.
    Наивное симметричное `±samp_rate/2` дало бы постоянные +28 Гц.
    """
    bin_hz = samp_rate / nchan
    u = (np.asarray(j_px, dtype=float) + 0.5) / width_px
    return -samp_rate / 2.0 + (u * nchan - 0.5) * bin_hz


def dc_mask(width_px: int, samp_rate: int, nchan: int, pad_px: int = 2) -> np.ndarray:
    """Столбцы, попадающие на три занулённых клиентом DC-канала.

    Клиент заменяет каналы `nchan//2 ± 1` полусуммой соседей, то есть данные
    там **синтетические**. Существенно потому, что при хорошем опорном TLE
    остаток доплера проходит через нулевое смещение именно вблизи TCA —
    в самой информативной точке. Разрыв в треке лучше синтетической точки.
    """
    j = np.arange(width_px)
    centre = width_px * (0.5 + 0.5 / nchan)  # столбец нулевого смещения
    half = 1.5 * width_px / nchan + pad_px
    return np.abs(j - centre) <= half


@dataclass(frozen=True)
class Ridge:
    """Извлечённый гребень: индексы строк и субпиксельные столбцы."""

    row_px: np.ndarray  # центр бина по строкам области графика, снизу вверх
    col_px: np.ndarray  # субпиксельный столбец
    snr: np.ndarray
    weight: np.ndarray


def peak_width_limits_px(
    width_px: int, nchan: int, samp_rate: int, bw_99_hz: float | None
) -> tuple[float, float]:
    """Допустимая ширина пика по половине высоты, пиксели.

    **Отличается от algorithms.md §2, и вот почему.** Там записано
    `w_exp = bw_99_hz / samp_rate · Wp` и допуск `[0.3, 4.0]·w_exp`.
    Замер на наблюдении 1527888 показал, что так не работает: `bw_99_hz`
    это занятая полоса **всего** сигнала (2-FSK с девиацией 4801.6 Гц даёт
    14062 Гц, то есть 146 px), а гребень — это **одна** из двух тонов,
    и её реальная ширина 1..7 px. Нижняя граница `0.3·146 = 44 px`
    отбрасывала все строки до единой.

    Правильные масштабы разные: снизу ширину ограничивает разрешение
    рендера (`Wp/nchan` ≈ 0.6 px, размазанное билинейной интерполяцией),
    сверху — смысл теста, то есть отсев широкополосных сигналов, для которых
    понятие гребня не определено. `bw_99_hz` остаётся верхней оценкой, но
    вместе с потолком в 10% полосы.
    """
    floor = max(1.0, width_px / nchan)
    ceiling = 0.1 * width_px
    if bw_99_hz:
        ceiling = min(ceiling, bw_99_hz / samp_rate * width_px)
    return floor, max(ceiling, 4.0 * floor)


def extract_ridge(
    z: np.ndarray,
    *,
    bin_rows: int,
    width_limits_px: tuple[float, float],
    dc_cols: np.ndarray,
    snr_threshold: float = 4.0,
    background_px: int = 101,
) -> Ridge:
    """Поиск гребня построчно с робастной трассировкой.

    Биннинг по времени поднимает SNR до поиска пика; фон вдоль частоты
    снимается медианным фильтром, шум оценивается по MAD.

    **Известное ограничение — частотная манипуляция.** У 2-FSK в каждой строке
    два тона, разнесённых на удвоенную девиацию (при 9600 бод это 10..14 кГц,
    то есть 100..145 пикселей), и сильнейший из них меняется от строки
    к строке. Трек по argmax прыгает между тонами: замер на наблюдениях
    1526701, 1526580, 1526872 и 1527845 дал ранговую корреляцию −0.36..+0.27,
    то есть трека нет вовсе, хотя сигнал сильный (до 1997 декодированных
    кадров). Правильный ответ — несущая как середина пары; это задача фазы 1,
    см. roadmap. Сейчас такие проходы честно возвращают пустой трек,
    а не неверный.

    Субпиксель берётся **центроидом, а не параболой по трём точкам**:
    билинейный ресемплинг при рендере размазывает пик примерно на `Wp/nchan`
    пикселя и делает плечи асимметричными, и центроид деградирует мягче.
    """
    h, w = z.shape
    nbin = max(h // bin_rows, 1)
    trimmed = z[: nbin * bin_rows].reshape(nbin, bin_rows, w)
    with np.errstate(invalid="ignore"):
        band = np.nanmean(trimmed, axis=1)

    rows, cols, snrs = [], [], []
    for r in range(nbin):
        line = band[r].copy()
        line[dc_cols] = np.nan
        if np.isnan(line).all():
            continue
        filled = np.where(np.isnan(line), np.nanmedian(line), line)

        bg = median_filter(filled, size=background_px, mode="nearest")
        resid = filled - bg
        sigma = 1.4826 * np.median(np.abs(resid))
        if sigma <= 0:
            continue
        snr = resid / sigma

        peak = int(np.nanargmax(np.where(np.isnan(line), -np.inf, snr)))
        if snr[peak] < snr_threshold:
            continue

        # Окно по половине высоты вокруг пика.
        #
        # Пробовалось окно на всю полосу сигнала (`signal_span_px`), чтобы у
        # 2-FSK усреднять оба тона и получать несущую как их середину. Замер:
        # покрытие выросло с 3 до 5 наблюдений из 12, но на эталонном 1527888
        # RMS ухудшился с 0.025 до 0.633 кГц — широкое окно втягивает шум и
        # соседние сигналы там, где несущая одиночная и чистая. Ухудшать
        # проверенный случай ради непроверенных нельзя, поэтому окно узкое.
        half = snr > 0.5 * snr[peak]
        lo = peak
        while lo > 0 and half[lo - 1]:
            lo -= 1
        hi = peak
        while hi < w - 1 and half[hi + 1]:
            hi += 1
        if not (width_limits_px[0] <= hi - lo + 1 <= width_limits_px[1]):
            continue

        window = np.arange(lo, hi + 1)
        weights = snr[lo : hi + 1]
        rows.append((r + 0.5) * bin_rows - 0.5)
        cols.append(float(np.sum(window * weights) / np.sum(weights)))
        snrs.append(float(snr[peak]))

    row_px = np.array(rows)
    col_px = np.array(cols)
    snr_arr = np.array(snrs)
    return _trace(row_px, col_px, snr_arr)


MIN_MONOTONICITY = 0.9


def _trace(
    row_px: np.ndarray,
    col_px: np.ndarray,
    snr: np.ndarray,
    sigma_clip: float = 3.0,
    min_monotonicity: float = MIN_MONOTONICITY,
) -> Ridge:
    """Отсев выбросов подгонкой кубики по времени плюс проверка монотонности.

    Доплеровская кривая гладкая **и строго монотонная**: лучевая скорость
    за проход растёт от −7 до +7 км/с не меняя направления, поэтому частота
    только убывает. Стационарная помеха — вертикальная линия — тоже гладкая,
    и одна кубика её не отсекает: постоянная функция ложится на кубику
    идеально. Проверка монотонности нужна отдельно.

    Замер: без неё на наблюдениях 1524589, 1518535 и 1526434 трассировка
    цеплялась за помеху, корреляция извлечённого трека с предсказанным
    доплером выходила R² ≈ 0, а RMS — 7..17 кГц. Это выглядело как провал
    извлечения, хотя извлекалось просто не то.

    # ponytail: ранговая корреляция вместо динамического программирования
    #           по кандидатам. Потолок — проход с двумя спутниками в полосе
    #           вернёт один трек. Апгрейд до DP (цена = -snr +
    #           λ·max(0, f_j − f_prev) плюс цена пропуска), если такие проходы
    #           реально встретятся. Человек их и так может поправить руками.
    """
    empty = Ridge(*(np.array([]) for _ in range(4)))
    if row_px.size < 8:
        return Ridge(row_px, col_px, snr, np.minimum(1.0, snr / 10.0))

    keep = np.ones(row_px.size, dtype=bool)
    for _ in range(3):
        if keep.sum() < 5:
            break
        coef = np.polyfit(row_px[keep], col_px[keep], 3)
        resid = col_px - np.polyval(coef, row_px)
        scale = 1.4826 * np.median(np.abs(resid[keep] - np.median(resid[keep])))
        if scale <= 0:
            break
        new = np.abs(resid) < sigma_clip * scale
        if (new == keep).all():
            break
        keep = new

    if keep.sum() < 8:
        return empty

    rho = _rank_correlation(row_px[keep], col_px[keep])
    if abs(rho) < min_monotonicity:
        return empty

    return Ridge(
        row_px[keep], col_px[keep], snr[keep], np.minimum(1.0, snr[keep] / 10.0)
    )


def _rank_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Коэффициент Спирмена. Для доплеровской кривой ≈ ±1, для помехи ≈ 0."""
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    rx -= rx.mean()
    ry -= ry.mean()
    denom = np.sqrt((rx**2).sum() * (ry**2).sum())
    return 0.0 if denom == 0 else float((rx * ry).sum() / denom)
