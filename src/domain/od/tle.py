"""Сборка строк TLE и контрольная сумма.

Разбор идёт через `Elements.from_tle`, то есть через `Satrec.twoline2rv`;
второй разборщик здесь не заводится. Сборка — через `sgp4.exporter.export_tle`:
он уже делает 69 символов, контрольные суммы и alpha-5, и round-trip
на всех 35 файлах `.tle` из `strf/` сходится (algorithms.md §5).
"""

from __future__ import annotations

from sgp4.api import Satrec
from sgp4.exporter import export_tle

from .elements import Elements

TLE_LINE_LENGTH = 69


def checksum(line: str) -> int:
    """Контрольная сумма строки TLE: сумма цифр плюс число минусов, mod 10.

    Как в `format_tle` (`rffit.c:111`). Считается по первым 68 символам:
    69-й и есть эта сумма.
    """
    return (
        sum(int(c) for c in line[:68] if c.isdigit()) + line[:68].count("-")
    ) % 10


def validate_lines(line1: str, line2: str) -> None:
    """Проверка строк перед разбором. Не проходит — `ValueError`.

    Нужна там, где строки приходят от человека: затравка сессии. По остальным
    путям TLE приезжает из Django, который уже прогнал `validate_tle`.

    **`Satrec.twoline2rv` мусор не отвергает.** Это разборщик по фиксированным
    колонкам: на короткой или битой строке он не бросает исключение, а молча
    возвращает нули и ставит `sat.error`. Замер: `twoline2rv("1 мусор",
    "2 мусор")` даёт `satnum=0, inclo=0, ecco=0, no_kozai=0, error=2` — то есть
    затравку, с которой фит стартует в никуда и жалуется на что угодно, кроме
    настоящей причины.

    Проверяется то же, что в `network/base/tasks.py::validate_tle` монолита,
    минус диапазоны элементов: длина, номер строки, контрольная сумма
    и согласованность номера объекта. Плюс код ошибки самого SGP4 — его
    в монолите нет, а он ловит остальное.
    """
    for number, line in ((1, line1), (2, line2)):
        if len(line) != TLE_LINE_LENGTH:
            raise ValueError(
                f"строка {number} длиной {len(line)}, а нужно {TLE_LINE_LENGTH}"
            )
        if not line.startswith(f"{number} "):
            raise ValueError(f"строка {number} не начинается с «{number} »")
        if line[68] != str(checksum(line)):
            raise ValueError(
                f"контрольная сумма строки {number}: в строке {line[68]!r}, "
                f"посчитана {checksum(line)}"
            )

    if line1[2:7] != line2[2:7]:
        raise ValueError(
            f"номер объекта разный: {line1[2:7]!r} в первой строке, "
            f"{line2[2:7]!r} во второй"
        )

    sat = Satrec.twoline2rv(line1, line2)
    if sat.error:
        raise ValueError(f"SGP4 не принимает элементы: код {sat.error}")


def to_lines(
    elements: Elements,
    *,
    intldes: str = "",
    elnum: int = 0,
    revnum: int = 0,
    classification: str = "U",
) -> tuple[str, str]:
    """Две строки TLE по элементам.

    Международное обозначение, номер набора и номер витка — паспортные поля,
    которых в `Elements` нет: они не участвуют в движении. `sgp4init`
    их не заполняет, поэтому без явной передачи они уходят в строку пустыми
    (как в файлах `strf/`, где так и есть).

    `assert` на длину стоит здесь, а не у вызывающего: Django валидирует
    ровно 69 символов, и без проверки ошибка длины всплыла бы только
    в момент публикации, когда TLE уже посчитано и показано человеку.
    """
    sat = elements.to_satrec()
    sat.classification = classification
    sat.intldesg = intldes
    sat.elnum = elnum
    sat.revnum = revnum
    sat.ephtype = 0

    line1, line2 = export_tle(sat)
    assert len(line1) == TLE_LINE_LENGTH, f"строка 1 длиной {len(line1)}"
    assert len(line2) == TLE_LINE_LENGTH, f"строка 2 длиной {len(line2)}"
    return line1, line2
