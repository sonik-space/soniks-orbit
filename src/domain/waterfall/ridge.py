"""Поиск доплеровского гребня и робастная трассировка.

Формулы — algorithms.md §2.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import median_filter


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


def _centroid_at(
    snr: np.ndarray, peak: int, width_limits_px: tuple[float, float]
) -> float | None:
    """Субпиксельный центр пика по окну выше половины его высоты.

    Пробовалось окно на всю полосу сигнала (`signal_span_px`), чтобы у 2-FSK
    усреднять оба тона и получать несущую как их середину. Замер: покрытие
    выросло с 3 до 5 наблюдений из 12, но на эталонном 1527888 RMS ухудшился
    с 0.025 до 0.633 кГц — широкое окно втягивает шум и соседние сигналы там,
    где несущая одиночная и чистая. Ухудшать проверенный случай ради
    непроверенных нельзя, поэтому окно узкое.

    Субпиксель берётся **центроидом, а не параболой по трём точкам**:
    билинейный ресемплинг при рендере размазывает пик примерно на `Wp/nchan`
    пикселя и делает плечи асимметричными, и центроид деградирует мягче.

    `None` означает, что ширина не прошла тест: это не пик гребня.
    """
    w = snr.size
    half = snr > 0.5 * snr[peak]
    lo = peak
    while lo > 0 and half[lo - 1]:
        lo -= 1
    hi = peak
    while hi < w - 1 and half[hi + 1]:
        hi += 1
    if not (width_limits_px[0] <= hi - lo + 1 <= width_limits_px[1]):
        return None
    window = np.arange(lo, hi + 1)
    weights = snr[lo : hi + 1]
    return float(np.sum(window * weights) / np.sum(weights))


def extract_ridge(
    z: np.ndarray,
    *,
    bin_rows: int,
    width_limits_px: tuple[float, float],
    dc_cols: np.ndarray,
    snr_threshold: float = 4.0,
    background_px: int = 101,
    chain_tol_px: float = 10.0,
    chain_min_points: int = 20,
    chain_min_span_px: float = 0.0,
    chain_slope_penalty: float = 8.0,
) -> Ridge:
    """Поиск гребня построчно с робастной трассировкой.

    Биннинг по времени поднимает SNR до поиска пика; фон вдоль частоты
    снимается медианным фильтром, шум оценивается по MAD.

    **Два пути, строго в этом порядке.** Сначала трек по сильнейшему пику
    строки — ровно тот, которым получены 0.025 кГц на эталонном наблюдении
    1527888. Если он прошёл трассировку, возвращается он, и никакая правка
    ниже на него не влияет: это структурная гарантия, а не обещание проверить.

    Запасной путь включается, только когда первый вернул пусто, то есть
    на частотной манипуляции. Замер: у 2-FSK строка содержит не два тона,
    как было записано в roadmap, а **гребёнку из пяти и более линий с шагом
    в девиацию** (при 4.4 кГц девиации и 96 Гц на пиксель это 50 px;
    на 1526893 видны линии 192/241/292/341/392). Сильнейшая линия меняется
    от строки к строке, поэтому argmax прыгает по гребёнке, ранговая
    корреляция выходит −0.36..+0.27, и трассировка честно возвращает пусто.
    Разрешается это выбором одной линии — см. `_dp_track`.
    """
    h, w = z.shape
    nbin = max(h // bin_rows, 1)
    trimmed = z[: nbin * bin_rows].reshape(nbin, bin_rows, w)
    with warnings.catch_warnings():
        # Бин целиком под оверлеем — штатная ситуация, строка просто
        # пропускается ниже. `np.errstate` эту жалобу не ловит: nanmean
        # ругается через warnings, а не через флаги плавающей точки.
        warnings.simplefilter("ignore", RuntimeWarning)
        band = np.nanmean(trimmed, axis=1)

    rows, cols, snrs = [], [], []
    candidates: dict[float, list[tuple[float, float]]] = {}
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
        snr = np.where(np.isnan(line), -np.inf, resid / sigma)

        peak = int(np.argmax(snr))
        if snr[peak] < snr_threshold:
            continue
        row_px = (r + 0.5) * bin_rows - 0.5

        # Первый путь: сильнейший пик строки и больше ничего.
        centre = _centroid_at(snr, peak, width_limits_px)
        if centre is not None:
            rows.append(row_px)
            cols.append(centre)
            snrs.append(float(snr[peak]))

        # Второй путь: все локальные максимумы выше порога — линии гребёнки
        # плюс шум. Собираются всегда, используются только при отказе первого.
        inner = np.flatnonzero(
            (snr[1:-1] >= snr_threshold)
            & (snr[1:-1] >= snr[:-2])
            & (snr[1:-1] >= snr[2:])
        ) + 1
        row_cands: list[tuple[float, float]] = []
        for j in inner:
            c = _centroid_at(snr, int(j), width_limits_px)
            if c is None:
                continue
            if row_cands and abs(c - row_cands[-1][0]) < 1e-6:
                # Пик с выемкой даёт два максимума с одним центроидом.
                if snr[j] > row_cands[-1][1]:
                    row_cands[-1] = (c, float(snr[j]))
                continue
            row_cands.append((c, float(snr[j])))
        if row_cands:
            candidates[row_px] = row_cands

    ridge = _trace(np.array(rows), np.array(cols), np.array(snrs))
    if ridge.row_px.size:
        return ridge

    # Порядок путей задан замером: сначала глобально оптимальный, потом
    # привязанный к сильнейшей строке. Первый даёт заметно лучшие треки
    # (на 1526877 — 0.13 против 1.67 кГц), но вырождается там, где сигнал
    # занимает лишь часть прохода: длинная слабая помеха на всю картинку
    # для него дешевле короткого сильного сигнала. Тогда её отсекает порог
    # по размаху, и очередь доходит до второго.
    if len(candidates) >= chain_min_points:
        for track in (
            _dp_track(candidates, chain_slope_penalty),
            _chain_from_anchor(candidates, chain_tol_px),
        ):
            accepted = _accept(track, chain_min_points, chain_min_span_px)
            if accepted.row_px.size:
                return accepted
    return _EMPTY


_EMPTY = Ridge(*(np.array([]) for _ in range(4)))

Track = tuple[np.ndarray, np.ndarray, np.ndarray]


def _accept(track: Track, min_points: int, min_span_px: float) -> Ridge:
    """Трассировка запасного трека с двумя дополнительными порогами.

    Пороги свои и жёсткие, потому что путь запасной и цеплять он может
    что угодно:

    - **по числу точек** — короткий трек из трёх случайных максимумов
      проходит и кубику, и монотонность, после чего RMS считается по мусору;
    - **по размаху частоты** — стационарная помеха монотонна не хуже сигнала,
      поэтому проверка монотонности её не ловит. Замер: на 1518535 и 1524589
      (обе — станции без единого декодированного кадра, обе названы
      в algorithms.md §2 как раз в этом качестве) запасной путь дал размах
      0.67 и 0.80 кГц, тогда как настоящий доплеровский трек за проход
      проходит 6..21 кГц. Порог приходит от вызывающего в пикселях, потому
      что герцы на пиксель знает только он.
    """
    ridge = _trace(*track)
    if ridge.row_px.size < min_points or np.ptp(ridge.col_px) < min_span_px:
        return _EMPTY
    return ridge


def _dp_track(
    candidates: dict[float, list[tuple[float, float]]], slope_penalty: float
) -> Track:
    """Глобально оптимальный путь по кандидатам, цена `−snr + λ·|Δf|`.

    Ровно тот апгрейд, который был записан в `_trace` как отложенный:
    условие «если реально встретятся проходы, где argmax прыгает» выполнилось
    на 8 наблюдениях из 23. Жадный выбор ошибается необратимо — уйдя
    на соседнюю линию гребёнки, он на неё и остаётся; Витерби платит
    за переход дважды, туда и обратно, и потому линию не меняет.

    Какая именно линия выбрана, для фита неважно: постоянное смещение
    целиком поглощается профилированной несущей `F_k` (ошибка поглощения
    ≈ 0.13 Гц против 25 Гц RMS эталона). Важно только, чтобы линия
    не менялась по ходу прохода.

    Штраф за наклон задан в единицах SNR на пиксель. Замер: результат
    не меняется на всём отрезке λ = 4..25, то есть настройка не на грани.
    """
    rows = sorted(candidates)
    cost = np.array([])
    cols_prev = np.array([])
    back: list[np.ndarray | None] = []
    for row in rows:
        cols = np.array([c for c, _ in candidates[row]])
        gain = -np.array([s for _, s in candidates[row]])
        if cost.size == 0:
            cost, back = gain, [None]
        else:
            step = cost[:, None] + slope_penalty * np.abs(cols_prev[:, None] - cols)
            src = step.argmin(axis=0)
            back.append(src)
            cost = step[src, np.arange(cols.size)] + gain
        cols_prev = cols

    k = int(cost.argmin())
    picked = []
    for i in reversed(range(len(rows))):
        picked.append((rows[i], *candidates[rows[i]][k]))
        if back[i] is not None:
            k = int(back[i][k])
    picked.reverse()
    return (
        np.array([p[0] for p in picked]),
        np.array([p[1] for p in picked]),
        np.array([p[2] for p in picked]),
    )


def _chain_from_anchor(
    candidates: dict[float, list[tuple[float, float]]], tol_px: float
) -> Track:
    """Цепочка по непрерывности от самой сильной строки в обе стороны.

    Доплер за секунду сдвигает частоту на 2..3 пикселя, а линии гребёнки
    разнесены на девиацию, то есть на ~50 пикселей. Между этими масштабами
    и стоит допуск: ближайший к предыдущему выбору кандидат — та же линия,
    а не соседняя.

    Берётся, когда путь по Витерби отвергнут: он оптимизирует весь проход
    целиком и потому предпочитает длинную помеху короткому сигналу, а эта
    цепочка стартует там, где сигнал заведомо есть.
    """
    rows = sorted(candidates)
    anchor = max(rows, key=lambda r: max(s for _, s in candidates[r]))
    picked = {anchor: max(candidates[anchor], key=lambda t: t[1])}

    for step in (1, -1):
        last = picked[anchor][0]
        i = rows.index(anchor) + step
        while 0 <= i < len(rows):
            best = min(candidates[rows[i]], key=lambda t: abs(t[0] - last))
            if abs(best[0] - last) <= tol_px:
                picked[rows[i]] = best
                last = best[0]
            i += step

    keys = sorted(picked)
    return (
        np.array(keys),
        np.array([picked[r][0] for r in keys]),
        np.array([picked[r][1] for r in keys]),
    )


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
