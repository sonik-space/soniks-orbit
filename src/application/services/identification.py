"""Сшивка идентификации: трек наблюдения → кандидаты каталога, ранжированные по RMS.

Единственное место, где это происходит, — как `extraction.py` для извлечения
и `fitting.py` для фита (правило 8).

Элементы кандидатов **не двигаются**: победитель выбирается по RMS
скрининга, и это не экономия, а единственный способ вообще различить
объекты. Замер: полный фит с приорами поднимает всех кандидатов запуска
к RMS 0.020–0.025 кГц и роняет отрыв со ×177 до ×1.06 (на 1526877 — до ×1.00).
Причина в физике: объекты одного запуска делят плоскость и период
и различаются в основном фазой вдоль трассы, а приор на `argp + M` — 5°,
ровно та свобода, которая нужна, чтобы сдвинуть любого из них на ту же
доплеровскую кривую. Из одного прохода наблюдаемы примерно две величины
(domain.md), поэтому фит принципиально не различает объекты, отличающиеся
фазой. Фит — инструмент **уточнения**, и он начинается после подтверждения,
в созданной сессии.

Отсюда же следует, что победитель **предварителен**: соседние объекты стоят
близко, и повторный перебор по новому наблюдению может назвать другого.
Задание переписывается, пока человек его не решил.

Сегменты собирает `fitting.py::build_segments`, оценку кандидата считает
`domain/od/fit.py::screen` — второй реализации ни того, ни другого здесь нет.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from application.dtos.common import TleSchema
from application.dtos.identification import (
    CandidateResponse,
    IdentificationResponse,
    IdentificationSummaryResponse,
)
from application.services.fitting import build_segments
from domain.exceptions import NotFoundError
from domain.models import CatalogObject, Identification, ObservationTrack
from domain.od.fit import Segment, screen

# Отрыв лучшего кандидата от следующего. Замер по golden-водопадам:
# внутри запуска правильный объект даёт от ×13.8 до ×177, а единственный
# случай, где перебор ошибся (1524517, полоса 240 кГц — вне области
# применения раздела), выдал ×1.1. Величина порядка единицы означает
# «варианты неразличимы» ровно так же, как у `convention_margin`
# при выборе оси частот (algorithms.md §3).
#
# Значения живут константами модуля, а не в конфигурации: ручка в переменной
# окружения ослабляется без единой правки кода и без следа в документации
# (правило 11, тот же довод, что у порога публикации).
MIN_CANDIDATE_MARGIN = 3.0

@dataclass(frozen=True)
class Candidate:
    """Строка результата перебора.

    Строки TLE лежат здесь потому, что подтверждение кладёт затравкой
    в сессию именно их. Каталог обновляется каждые 4 часа, человек
    подтверждает позже — и затравкой обязана стать та строка, по которой
    считался RMS, иначе подтверждённое число невоспроизводимо (правило 10).
    """

    norad_id: int
    name: str
    intdes: str
    rms_khz: float
    carrier_hz: float
    same_launch: bool
    tle0: str
    tle1: str
    tle2: str

    def to_dict(self) -> dict:
        return asdict(self)


def is_screenable(track: ObservationTrack) -> bool:
    """Годится ли трек для перебора вообще.

    Условие ровно одно: точки есть. Их ставит человек, и он же отвечает
    за то, что отметил сигнал, а не помеху, — второго судьи здесь нет.

    Прежняя проверка `reliable` снята, и не потому, что мешала. Запас между
    конвенциями оси частот различал их через доплеровский **размах** трека:
    четыре модели расходятся только слагаемым с лучевой скоростью. У ручной
    разметки размах около нуля — коррекция при записи ведётся всегда, — и запас
    выходит 1.000 на всех 15 размеченных проходах. То есть проверка перестала
    что-либо измерять, а не стала строгой (decisions/015).
    """
    return track.n_points > 0


def launch_of(meta: dict) -> str:
    """Обозначение запуска объекта, под который планировалось наблюдение.

    Берётся из строки TLE замороженного снимка: отдельного эндпоинта для
    этого в сети нет (integration.md). Пустая строка означает «запуск
    неизвестен» — тогда перебор сразу идёт по всему каталогу.
    """
    line1 = ((meta.get("tle") or {}).get("tle1")) or ""
    return line1[9:17].strip()[:5]


def margin_of(rms_khz_ascending: list[float]) -> float:
    """Во сколько раз лучший кандидат лучше следующего.

    Принимает голые RMS, потому что зовётся и на разобранных кандидатах,
    и на блоке из JSONB, а число там одно и то же.

    Единственный кандидат неразличим ни с чем, поэтому отрыва у него нет,
    а не бесконечный: одиночный объект запуска не повод объявлять его ответом.
    """
    if len(rms_khz_ascending) < 2 or rms_khz_ascending[0] <= 0.0:
        return 0.0
    return rms_khz_ascending[1] / rms_khz_ascending[0]


def screen_track(
    track: ObservationTrack, objects: list[CatalogObject]
) -> list[Candidate]:
    """Ступень 1: перебор без движения элементов, сначала по запуску.

    Порядок из decisions/006, и замер объясняет, зачем он нужен помимо цены:
    внутри запуска отрыв правильного объекта выше на порядок (×177 против
    ×18.9 на эталоне 1527888). По всему каталогу перебор тоже сходится,
    но различимость заметно хуже, а на границе применимости — теряется.
    """
    segments, _ = build_segments([track])
    if not segments:
        return []

    launch = launch_of(track.meta)
    if launch:
        mates = [o for o in objects if o.launch == launch]
        candidates = _score(segments, mates, launch)
        if margin_of([c.rms_khz for c in candidates]) >= MIN_CANDIDATE_MARGIN:
            return candidates

    return _score(segments, objects, launch)


def _score(
    segments: list[Segment], objects: list[CatalogObject], launch: str
) -> list[Candidate]:
    key = segments[0].key
    scored: list[Candidate] = []
    for obj in objects:
        result = screen(obj.elements, segments)
        if result is None:
            # SGP4 не смог прогнать этот набор — объект сходит с орбиты
            # или элементы битые. Молчаливого нуля здесь быть не должно:
            # он выиграл бы ранжирование. Замер: таких около 500 из 2901.
            continue
        rms, carriers = result
        scored.append(
            Candidate(
                norad_id=obj.norad_id,
                name=obj.name,
                intdes=obj.intdes,
                rms_khz=rms,
                # Ядро считает в кГц, API отдаёт герцы (правило 2).
                carrier_hz=carriers[key] * 1000.0,
                same_launch=bool(launch) and obj.launch == launch,
                tle0=obj.tle.tle0,
                tle1=obj.tle.tle1,
                tle2=obj.tle.tle2,
            )
        )
    scored.sort(key=lambda c: c.rms_khz)
    return scored


def identification_response(identification: Identification) -> IdentificationResponse:
    return IdentificationResponse(
        uuid=identification.uuid,
        created_at=identification.created_at,
        observation_id=identification.observation_id,
        stage=identification.stage,
        margin=_margin(identification),
        candidates=[_candidate_schema(c) for c in identification.candidates],
        confirmed_norad_id=identification.confirmed_norad_id,
        confirmed_by_sub=identification.confirmed_by_sub,
        session_uuid=identification.session_uuid,
    )


def identification_summary(
    identification: Identification,
) -> IdentificationSummaryResponse:
    """Строка списка: кандидаты урезаны до лучшего.

    Полный перебор по каталогу — это тысячи строк на задание, а списку нужно
    решить, куда заходить. Тот же довод, по которому история прогонов фита
    отдаёт компактные строки без невязок.
    """
    candidates = identification.candidates
    return IdentificationSummaryResponse(
        uuid=identification.uuid,
        created_at=identification.created_at,
        observation_id=identification.observation_id,
        stage=identification.stage,
        margin=_margin(identification),
        n_candidates=len(candidates),
        best=_candidate_schema(candidates[0]) if candidates else None,
        confirmed_norad_id=identification.confirmed_norad_id,
        session_uuid=identification.session_uuid,
    )


def best_candidate(identification: Identification, norad_id: int | None = None) -> dict:
    """Кандидат, чьи строки идут затравкой в сессию.

    Берётся **сохранённый в задании** набор, а не свежий из каталога: каталог
    обновляется каждые 4 часа, человек подтверждает позже, и затравкой обязана
    стать та строка, по которой считался показанный ему RMS (правило 10).
    """
    for candidate in identification.candidates:
        if norad_id is None or candidate["norad_id"] == norad_id:
            return candidate
    raise NotFoundError(f"кандидата {norad_id} нет в задании {identification.uuid}")


def _margin(identification: Identification) -> float | None:
    """`None` — перебора не было. Ноль читался бы как «неразличимо»,
    а это разные состояния."""
    if not identification.candidates:
        return None
    return margin_of([c["rms_khz"] for c in identification.candidates])


def _candidate_schema(candidate: dict) -> CandidateResponse:
    return CandidateResponse(
        norad_id=candidate["norad_id"],
        name=candidate["name"],
        intdes=candidate["intdes"],
        rms_khz=candidate["rms_khz"],
        carrier_hz=candidate["carrier_hz"],
        same_launch=candidate["same_launch"],
        tle=TleSchema(
            tle0=candidate["tle0"], tle1=candidate["tle1"], tle2=candidate["tle2"]
        ),
    )
