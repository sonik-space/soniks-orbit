"""Golden-тесты гоняют ту же цепочку, что и замер фазы 0.

Сшивка «PNG → калибровка → гребень → доплер → RMS» пока живёт в
`scripts/phase0/end_to_end.py`; в фазе 2 она переедет в
`application/services/extraction.py` (правило 8), и тогда путь ниже меняется
на обычный импорт. Третьей копии цепочки не заводим: тест обязан проверять
ровно то, что считает боевой код.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "phase0"))
