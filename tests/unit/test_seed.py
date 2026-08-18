"""Затравка сессии: шаблоны орбит и ручная правка элементов (decisions/014).

Порт клавиши `t` и меню `c` из `rffit`. Проверяется не «работает вообще»,
а три вещи, каждая из которых ломается молча:

  - шаблон LEO зависит от площадки и времени, остальные три — нет;
  - правка накладывается **поверх** текущей затравки, а не заменяет её;
  - результат разбирается обратно через SGP4 без потерь.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from uuid import uuid4

import pytest

from application.commands.session.update_seed import _build
from application.dtos.session import (
    SeedElementsSchema,
    TleSchema,
    UpdateSeedRequest,
)
from application.services.fitting import iso_from_mjd, mjd_from_iso
from domain.exceptions import BadRequestError
from domain.models import ObservationTrack, OdSession, TleLines
from domain.od.elements import Elements
from domain.od.geometry import gmst
from domain.od.templates import TEMPLATE_NAMES, template
from domain.od.tle import validate_lines

STRF = Path(__file__).resolve().parents[3] / "strf"

STATION_LAT = 62.049
STATION_LNG = 34.06
EPOCH_MJD = 61038.5


def _seed_lines() -> TleLines:
    lines = [
        ln.rstrip("\n")
        for ln in (STRF / "l10.tle").read_text(errors="replace").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    for i in range(len(lines) - 1):
        if lines[i].startswith("1 ") and lines[i + 1].startswith("2 "):
            return TleLines(tle0="ЭТАЛОН", tle1=lines[i], tle2=lines[i + 1])
    raise AssertionError(f"в {STRF / 'l10.tle'} нет пары строк TLE")


SEED = _seed_lines()
SEED_ELEMENTS = Elements.from_tle(SEED.tle1, SEED.tle2)


def _session(*, with_times: bool = True) -> OdSession:
    meta = {"station_lat": STATION_LAT, "station_lng": STATION_LNG}
    if with_times:
        meta |= {
            "start": iso_from_mjd(EPOCH_MJD - 0.01).isoformat(),
            "end": iso_from_mjd(EPOCH_MJD + 0.01).isoformat(),
        }
    return OdSession(
        uuid=uuid4(),
        name="уточнение",
        norad_id=98423,
        owner_sub="sub",
        seed=SEED,
        seed_source="observation",
        status="draft",
        observations=[
            ObservationTrack(
                uuid=uuid4(),
                observation_id=1037258,
                meta=meta,
                extraction_status="done",
                extraction_error=None,
                calibration=None,
                points=None,
                diagnostics=None,
            )
        ],
    )


# --- шаблоны --------------------------------------------------------------


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_template_round_trips_through_sgp4(name: str) -> None:
    """Шаблон обязан пережить `to_lines` → `from_tle`: иначе оператор видит
    в UI одни числа, а фит стартует с других."""
    from domain.od.tle import to_lines

    made = template(
        name, epoch_mjd=EPOCH_MJD, lat_deg=STATION_LAT, lng_deg=STATION_LNG
    )
    line1, line2 = to_lines(made)
    back = Elements.from_tle(line1, line2)

    assert back.incl_deg == pytest.approx(made.incl_deg, abs=1e-4)
    assert back.ecc == pytest.approx(made.ecc, abs=1e-7)
    assert back.rev_per_day == pytest.approx(made.rev_per_day, abs=1e-7)
    assert back.epoch_mjd == pytest.approx(made.epoch_mjd, abs=1e-7)


def test_leo_template_follows_the_station() -> None:
    """`rffit.c:1104`: у LEO восходящий узел ставится под станцию, а средняя
    аномалия — под её широту. Три остальных шаблона — константы."""
    leo = template("leo", epoch_mjd=EPOCH_MJD, lat_deg=STATION_LAT, lng_deg=STATION_LNG)

    assert leo.raan_deg == pytest.approx((gmst(EPOCH_MJD) + STATION_LNG) % 360.0)
    assert leo.ma_deg == pytest.approx(STATION_LAT)
    assert leo.incl_deg == 90.0
    assert leo.rev_per_day == 14.0


def test_leo_template_moves_with_epoch_and_others_do_not() -> None:
    """Обратная сторона: если бы RAAN у LEO был константой, фит стартовал бы
    с чужого узла на любой другой день — и это не отличалось бы от опечатки."""
    other_mjd = EPOCH_MJD + 3.0
    args = {"lat_deg": STATION_LAT, "lng_deg": STATION_LNG}

    leo_a = template("leo", epoch_mjd=EPOCH_MJD, **args)
    leo_b = template("leo", epoch_mjd=other_mjd, **args)
    assert leo_a.raan_deg != pytest.approx(leo_b.raan_deg)

    for name in ("gto", "gso", "heo"):
        assert template(name, epoch_mjd=EPOCH_MJD, **args).raan_deg == 0.0


def test_unknown_template_is_refused() -> None:
    with pytest.raises(ValueError, match="неизвестный шаблон"):
        template("meo", epoch_mjd=EPOCH_MJD, lat_deg=0.0, lng_deg=0.0)


# --- правка элементов -----------------------------------------------------


def test_patch_touches_only_the_named_element() -> None:
    """Меню `c` правит один элемент из семи. Остальные шесть обязаны остаться
    ровно теми же — оператор их не вводил и не должен вводить."""
    lines, source = _build(
        _session(),
        UpdateSeedRequest(elements=SeedElementsSchema(eccentricity=0.0042)),
    )
    got = Elements.from_tle(lines.tle1, lines.tle2)

    assert source == "manual"
    assert got.ecc == pytest.approx(0.0042, abs=1e-7)
    for field in ("incl_deg", "raan_deg", "argp_deg", "ma_deg", "rev_per_day"):
        assert getattr(got, field) == pytest.approx(
            getattr(SEED_ELEMENTS, field), abs=1e-4
        ), f"{field} уехал, хотя его не правили"


def test_patch_can_move_the_epoch() -> None:
    """Пункт 8 меню `c`. Эпоха приходит в ISO, ядро считает в MJD (правило 2)."""
    target = iso_from_mjd(SEED_ELEMENTS.epoch_mjd + 2.0)
    lines, _ = _build(
        _session(), UpdateSeedRequest(elements=SeedElementsSchema(epoch=target))
    )
    got = Elements.from_tle(lines.tle1, lines.tle2)

    assert got.epoch_mjd == pytest.approx(mjd_from_iso(target), abs=1e-7)
    # Элементы при этом **не переносятся** на новую эпоху: меню `c` в эталоне
    # именно переписывает поле, а перенос — это отдельный `reepoch`.
    assert got.ma_deg == pytest.approx(SEED_ELEMENTS.ma_deg, abs=1e-4)


def test_patch_wraps_angles() -> None:
    lines, _ = _build(
        _session(), UpdateSeedRequest(elements=SeedElementsSchema(raan_deg=-30.0))
    )
    assert Elements.from_tle(lines.tle1, lines.tle2).raan_deg == pytest.approx(330.0)


# --- готовые строки -------------------------------------------------------


def test_explicit_tle_is_taken_as_is() -> None:
    lines, source = _build(
        _session(),
        UpdateSeedRequest(tle=TleSchema(tle0=SEED.tle0, tle1=SEED.tle1, tle2=SEED.tle2)),
    )
    assert source == "manual"
    assert lines.tle1 == SEED.tle1


def _broken(kind: str) -> tuple[str, str]:
    """Строки, битые ровно одним способом."""
    if kind == "мусор":
        return "1 мусор", "2 мусор"
    if kind == "длина":
        return SEED.tle1[:-1], SEED.tle2
    if kind == "контрольная сумма":
        wrong = "0" if SEED.tle1[68] != "0" else "1"
        return SEED.tle1[:68] + wrong, SEED.tle2
    if kind == "разные номера":
        return SEED.tle1, "2 99999" + SEED.tle2[7:]
    raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind", ["мусор", "длина", "контрольная сумма", "разные номера"]
)
def test_unparsable_tle_is_refused_here_not_later(kind: str) -> None:
    """Отказ обязан прийти в ответ на правку.

    `Satrec.twoline2rv` сам по себе не защищает: это разборщик по фиксированным
    колонкам, и на мусоре он возвращает нули с `error=2`, а не исключение.
    Без `validate_lines` такая затравка молча дожила бы до фита.
    """
    line1, line2 = _broken(kind)
    with pytest.raises(BadRequestError, match="не разбираются"):
        _build(
            _session(),
            UpdateSeedRequest(tle=TleSchema(tle0="", tle1=line1, tle2=line2)),
        )


def test_good_lines_pass_validation() -> None:
    """Иначе все проверки выше зеленели бы на валидаторе, который запрещает всё."""
    validate_lines(SEED.tle1, SEED.tle2)


def test_template_needs_observation_times() -> None:
    """Шаблон ставят до извлечения, но не до того, как известно **когда**."""
    with pytest.raises(BadRequestError, match="нет времени"):
        _build(_session(with_times=False), UpdateSeedRequest(template="leo"))


def test_template_seed_is_centred_on_the_set() -> None:
    lines, source = _build(_session(), UpdateSeedRequest(template="leo"))
    got = Elements.from_tle(lines.tle1, lines.tle2)

    assert source == "template"
    assert got.epoch_mjd == pytest.approx(EPOCH_MJD, abs=1e-6)
    assert got.raan_deg == pytest.approx((gmst(EPOCH_MJD) + STATION_LNG) % 360.0, abs=1e-3)


# --- форма запроса --------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"template": "leo", "elements": SeedElementsSchema(raan_deg=1.0)},
        {
            "tle": TleSchema(tle0="", tle1=SEED.tle1, tle2=SEED.tle2),
            "template": "gso",
        },
    ],
    ids=["ничего", "шаблон и элементы", "строки и шаблон"],
)
def test_exactly_one_way_is_required(kwargs: dict) -> None:
    """Два способа сразу — это вопрос «который победит», на который не должно
    быть ответа."""
    with pytest.raises(ValueError, match="ровно один"):
        UpdateSeedRequest(**kwargs)


def test_epoch_helpers_round_trip() -> None:
    """`iso_from_mjd`/`mjd_from_iso` стоят на пути затравки дважды, и их
    расхождение сдвинуло бы эпоху молча."""
    when = dt.datetime(2026, 1, 5, 9, 24, 33, tzinfo=dt.UTC)
    assert iso_from_mjd(mjd_from_iso(when)) == when
