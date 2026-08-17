"""Разбор текстовых чанков PNG водопада.

Клиент сохраняет водопад через `matplotlib.savefig(metadata=...)`, поэтому
в чанках лежит точная калибровка и её не нужно угадывать (algorithms.md §1.1).

Сюда приходит уже разобранный `dict[str, str]` — вытаскивание чанков из байтов
это инфраструктура, а не алгоритм (правило 1).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass

from . import CalibrationError

WF_DAT = "satnogs:wf-dat"
WF_SIGNAL = "satnogs:wf-signal"


def parse_iso(text: str) -> dt.datetime:
    """Устойчивый разбор меток времени.

    Доли секунды бывают и не бывают, `Z` вместо смещения тоже. Оба старых
    инструмента падали на `strptime` с жёстким форматом (правило 4).
    """
    stamp = dt.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


@dataclass(frozen=True)
class WaterfallMeta:
    """Калибровка водопада из метаданных PNG.

    `deviation_hz`, `bw_99_hz` и `modulation` приходят из `satnogs:wf-signal`,
    которого может не быть: он не нужен для калибровки, только для настройки
    поиска гребня.
    """

    samp_rate_hz: int
    nchan: int
    nfft_per_row: int
    center_freq_hz: float
    t_ref: dt.datetime
    deviation_hz: float | None = None
    bw_99_hz: float | None = None
    modulation: str = ""

    @property
    def bin_hz(self) -> float:
        """Ширина канала. 56.25 Гц при полосе 57.6 кГц и 1024 каналах."""
        return self.samp_rate_hz / self.nchan

    @property
    def row_dt_s(self) -> float:
        """Время одной строки данных. 0.0889 с при типовых настройках.

        Рендер прореживает строки по времени, поэтому разрешение картинки
        определяется пикселем, а не строкой (algorithms.md §1.5).
        """
        return self.nfft_per_row * self.nchan / self.samp_rate_hz

    @classmethod
    def from_png_text(cls, chunks: dict[str, str]) -> "WaterfallMeta":
        """Метаданные из текстовых чанков.

        Отсутствие `satnogs:wf-dat` — **громкий отказ**, а не догадка о полосе.
        Эвристика `48e3` из старого инструмента (в комментарии честно
        помеченная «very bad heuristic») давала правдоподобный неверный
        результат, а поле `satnogs_rx_samp_rate` станции через API
        не отдаётся, так что взять полосу больше неоткуда.
        """
        raw = chunks.get(WF_DAT)
        if not raw:
            raise CalibrationError(
                f"нет {WF_DAT}: наблюдение непригодно, станция на клиенте "
                f"старше 2.2.x, полоса невосстановима"
            )
        wf = json.loads(raw)
        signal = json.loads(chunks.get(WF_SIGNAL) or "{}")
        return cls(
            samp_rate_hz=int(float(wf["samp_rate"])),
            nchan=int(wf["nchan"]),
            nfft_per_row=int(wf["nfft_per_row"]),
            center_freq_hz=float(wf["center_freq"]),
            t_ref=parse_iso(wf["timestamp"]),
            deviation_hz=signal.get("deviation_hz"),
            bw_99_hz=signal.get("bw_99_hz"),
            modulation=signal.get("modulation", ""),
        )
