"""Запасной путь трассировки на синтетической гребёнке.

Ловит ровно то, ради чего он написан: у 2-FSK в строке гребёнка линий,
сильнейшая меняется от строки к строке, и трек по argmax прыгает между ними
(algorithms.md §2). Проверяется и обратное — что одиночная несущая проходит
первым путём и запасной её не трогает.
"""

from __future__ import annotations

import numpy as np

from domain.waterfall.ridge import extract_ridge

ROWS, COLS = 60, 600
COMB_STEP_PX = 50  # шаг гребёнки = девиация; на боевых данных 50 px
TONE_WIDTH_PX = 2.0


def _waterfall(centres: np.ndarray, lines: int, seed: int = 0) -> np.ndarray:
    """Картинка с гребёнкой из `lines` линий вокруг заданного центра строки.

    Амплитуды линий скачут от строки к строке, поэтому argmax прыгает
    по гребёнке — это и есть воспроизводимый боевой отказ.
    """
    rng = np.random.default_rng(seed)
    j = np.arange(COLS)
    z = 0.05 * rng.standard_normal((ROWS, COLS))
    offsets = (np.arange(lines) - (lines - 1) / 2) * COMB_STEP_PX
    for r, centre in enumerate(centres):
        for off in offsets:
            amp = 0.5 + rng.random()
            z[r] += amp * np.exp(-0.5 * ((j - centre - off) / TONE_WIDTH_PX) ** 2)
    return z


def _extract(z: np.ndarray):
    return extract_ridge(
        z,
        bin_rows=1,
        width_limits_px=(1.0, 0.1 * COLS),
        dc_cols=np.zeros(COLS, dtype=bool),
        chain_min_points=8,
        chain_min_span_px=20.0,
    )


def test_comb_gives_one_line_and_a_monotone_track() -> None:
    centres = np.linspace(400.0, 200.0, ROWS)
    ridge = _extract(_waterfall(centres, lines=5))

    assert ridge.row_px.size >= 8, "гребёнка не должна оставаться без трека"
    # Выбрана одна линия: трек параллелен истинному центру, а смещение
    # постоянно и кратно шагу гребёнки. Какая именно линия — неважно,
    # постоянное смещение поглощается профилированной несущей.
    offset = ridge.col_px - np.interp(ridge.row_px, np.arange(ROWS), centres)
    assert offset.std() < 2.0, f"трек прыгает по гребёнке: разброс {offset.std():.1f} px"
    assert abs(np.median(offset)) < 2.5 * COMB_STEP_PX


def test_single_tone_is_taken_by_the_first_path() -> None:
    centres = np.linspace(400.0, 200.0, ROWS)
    ridge = _extract(_waterfall(centres, lines=1))

    assert ridge.row_px.size >= ROWS - 2  # пара строк уходит в отсев по 3σ
    residual = ridge.col_px - np.interp(ridge.row_px, np.arange(ROWS), centres)
    assert np.abs(residual).max() < 1.0


def test_stationary_interference_gives_nothing() -> None:
    """Помеха монотонна, кубике не противоречит и отсекается только размахом."""
    ridge = _extract(_waterfall(np.full(ROWS, 300.0), lines=1))
    assert ridge.row_px.size == 0
