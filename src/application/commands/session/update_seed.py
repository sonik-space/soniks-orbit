"""Замена затравки сессии.

Три способа из `rffit`, сведённые в один эндпоинт: готовые строки (клавиша
`g` — загрузить объект из каталога), правка отдельных элементов (меню `c`)
и грубый шаблон (клавиша `t`).

Затравка перестала быть неизменяемой (decisions/014). Это безопасно ровно
потому, что порог публикации с фазы 7 читает `elements_in` прогона, а не
текущую затравку сессии: правка не пересуживает историю задним числом.
"""

from __future__ import annotations

import datetime as dt
from uuid import UUID

from application.dtos.session import SeedElementsSchema, UpdateSeedRequest
from application.interfaces.repositories import SessionRepository
from application.interfaces.transaction import Transaction
from application.services.fitting import mjd_from_iso
from domain.exceptions import BadRequestError, NotFoundError
from domain.models import OdSession, TleLines
from domain.od.elements import Elements
from domain.od.templates import template
from domain.od.tle import to_lines, validate_lines


class UpdateSeedInteractor:
    def __init__(
        self, repo: SessionRepository, transaction: Transaction
    ) -> None:
        self._repo = repo
        self._transaction = transaction

    async def __call__(
        self, session_uuid: UUID, request: UpdateSeedRequest
    ) -> OdSession:
        session = await self._repo.get(session_uuid)
        if session is None:
            raise NotFoundError(f"сессия {session_uuid} не найдена")

        seed, seed_source = _build(session, request)
        await self._repo.set_seed(session_uuid, seed=seed, seed_source=seed_source)
        await self._transaction.commit()

        session = await self._repo.get(session_uuid)
        assert session is not None, "сессия исчезла между записью и чтением"
        return session


def _build(session: OdSession, request: UpdateSeedRequest) -> tuple[TleLines, str]:
    """Строки затравки и её источник. Ровно одна ветка — форма это проверила."""
    if request.tle is not None:
        lines = TleLines(request.tle.tle0, request.tle.tle1, request.tle.tle2)
        # Разбор здесь, а не при фите: строку, которую SGP4 не читает, надо
        # отвергнуть в ответ на правку, а не через полминуты в чужом сценарии.
        _parsed(lines)
        return lines, "manual"

    if request.template is not None:
        mjd, lat, lng = _mid_pass(session)
        elements = template(
            request.template, epoch_mjd=mjd, lat_deg=lat, lng_deg=lng
        )
        return _lines(elements, session, intldes="13900A"), "template"

    return _lines(
        _patched(session, request.elements), session, name=request.elements.name
    ), "manual"


def _parsed(lines: TleLines) -> Elements:
    try:
        validate_lines(lines.tle1, lines.tle2)
    except ValueError as error:
        raise BadRequestError(f"строки TLE не разбираются: {error}") from error
    return Elements.from_tle(lines.tle1, lines.tle2)


def _patched(session: OdSession, patch: SeedElementsSchema) -> Elements:
    """Текущая затравка с наложенными правками. Незаданное не трогается:
    оператор правит один элемент, а не переписывает все семь."""
    current = _parsed(session.seed)
    epoch = current.epoch_mjd if patch.epoch is None else mjd_from_iso(patch.epoch)

    return Elements(
        incl_deg=_or(patch.inclination_deg, current.incl_deg),
        raan_deg=_or(patch.raan_deg, current.raan_deg) % 360.0,
        ecc=_or(patch.eccentricity, current.ecc),
        argp_deg=_or(patch.argp_deg, current.argp_deg) % 360.0,
        ma_deg=_or(patch.mean_anomaly_deg, current.ma_deg) % 360.0,
        rev_per_day=_or(patch.mean_motion_rev_day, current.rev_per_day),
        bstar=_or(patch.bstar, current.bstar),
        epoch_mjd=epoch,
        satno=int(_or(patch.satno, current.satno)),
    )


def _lines(
    elements: Elements,
    session: OdSession,
    *,
    name: str | None = None,
    intldes: str | None = None,
) -> TleLines:
    """Строки TLE затравки.

    Обозначение и имя переносятся из текущей затравки: в `Elements` их нет,
    в движении они не участвуют, но без них затравка теряет паспортные поля —
    та же причина, что в `fitting.to_tle`.
    """
    if intldes is None:
        intldes = session.seed.tle1[9:17].strip()
    line1, line2 = to_lines(elements, intldes=intldes)
    return TleLines(
        tle0=session.seed.tle0 if name is None else name, tle1=line1, tle2=line2
    )


def _mid_pass(session: OdSession) -> tuple[float, float, float]:
    """Середина набора и площадка первого наблюдения — то, что нужно шаблону.

    Эталон берёт `compute_mean_mjd` по выделенным точкам (`rffit.c:70`).
    Здесь — по границам проходов из замороженных снимков: шаблон ставят
    до всякого извлечения, когда точек может не быть вовсе.
    """
    bounds = [
        mjd_from_iso(dt.datetime.fromisoformat(value))
        for track in session.observations
        for key in ("start", "end")
        if (value := track.meta.get(key))
    ]
    if not bounds:
        raise BadRequestError(
            "у наблюдений сессии нет времени: шаблонную затравку не на что поставить"
        )

    first = session.observations[0].meta
    return (
        0.5 * (min(bounds) + max(bounds)),
        float(first["station_lat"]),
        float(first["station_lng"]),
    )


def _or(value: float | None, fallback: float) -> float:
    return fallback if value is None else value
