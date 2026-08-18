"""Публикация TLE в каталог СОНИКС.

**Операция с радиусом поражения (правило 11).** Опубликованное TLE выигрывает
`select_latest_tle` и начинает управлять наведением **всей сети** по этому
спутнику, а публичный фид `/api/latesttles/` отдаёт его наружу.

Источник записи в каталоге — `Manual`, и он **первый** в `TLE_SOURCE_PRIORITY`:
свежий фит перебивает даже свежий Space-Track. Взамен в монолите не правятся
ни список приоритетов, ни окно свежести (decisions/007, 010), но и вся защита
каталога держится ровно на пороге ниже.

**Пороговые значения — константы модуля, а не конфигурация.** Значение
в переменной окружения можно ослабить, не тронув decisions/007, а правило 11
требует обратного: пороги меняются только вместе с правкой того файла.
"""

from __future__ import annotations

from uuid import UUID

from application.dtos.common import TleSchema
from application.dtos.publish import PublishRequest, PublishResponse
from application.interfaces.network_api import NetworkApi
from application.interfaces.repositories import FitRunRepository, SessionRepository
from application.interfaces.transaction import Transaction
from application.services.fitting import elements_from_dict, iso_from_mjd
from application.services.publishing import reepoch_run
from core.configs.app import AppSettings
from domain.exceptions import ConflictError, ForbiddenError, NotFoundError
from domain.models import FitRun
from domain.od.elements import Elements
from domain.od.reepoch import separation_km

MAX_RMS_KHZ = 1.0
MIN_POINTS = 100
MIN_OBSERVATIONS = 2
MAX_SEPARATION_KM = 50.0
# Шаг 7 гайда: «проверяем, что эксцентриситет не ноль». `classel` зажимает
# отрицательный эксцентриситет ровно в ноль (`reepoch.py`, как и `rv2el`
# в эталоне), и круговая орбита на месте эллиптической — это не уточнение,
# а потерянный элемент.
MIN_ECC = 1e-6


class PublishInteractor:
    def __init__(
        self,
        repo: SessionRepository,
        fit_repo: FitRunRepository,
        network: NetworkApi,
        transaction: Transaction,
        app: AppSettings,
    ) -> None:
        self._repo = repo
        self._fit_repo = fit_repo
        self._network = network
        self._transaction = transaction
        self._app = app

    async def __call__(
        self, fit_run_id: UUID, request: PublishRequest, access_token: str
    ) -> PublishResponse:
        run = await self._fit_repo.get(fit_run_id)
        if run is None:
            raise NotFoundError(f"прогон фита {fit_run_id} не найден")

        session = await self._repo.get(run.session_uuid)
        if session is None:
            raise NotFoundError(f"сессия {run.session_uuid} не найдена")

        # Порог — **до** обращения к Django, а не после (decisions/007).
        check_quality(run)

        epoch_mjd, lines = reepoch_run(run, session, request.reepoch_to)

        published_tle_id: int | None = None
        mode = request.mode
        if mode == "publish":
            if session.norad_id is None:
                raise ConflictError("у сессии нет номера объекта: публиковать некуда")
            try:
                published_tle_id = await self._network.publish_tle(
                    norad_id=session.norad_id,
                    lines=lines,
                    url=f"{self._app.UI_BASE_URL.rstrip('/')}"
                    f"/orbit/{session.uuid}?fit={run.uuid}",
                    access_token=access_token,
                )
            except ForbiddenError:
                # «Не владеешь спутником — `mode` принудительно становится
                # `propose`» (api.md). Отказ по правам это не ошибка сценария:
                # посчитанное TLE остаётся предложением, а не пропадает.
                mode = "propose"

        await self._fit_repo.mark_published(
            fit_run_id, mode=mode, published_tle_id=published_tle_id, tle=lines
        )
        if published_tle_id is not None:
            await self._repo.set_status(session.uuid, "published")
        await self._transaction.commit()

        return PublishResponse(
            mode=mode,
            published_tle_id=published_tle_id,
            epoch=iso_from_mjd(epoch_mjd),
            tle=TleSchema(tle0=lines.tle0, tle1=lines.tle1, tle2=lines.tle2),
        )


def check_quality(run: FitRun) -> None:
    """Порог качества. Не пройден — `409` с указанием, какое именно условие.

    Условие про статус прогона в таблице decisions/007 **добавлено**, а не
    было там изначально: у прогона со статусом `failed` элементы и невязки
    есть, и RMS у него может пройти по числу, но `least_squares` до этих
    элементов не сошёлся, и публиковать их нельзя. Ужесточение порога,
    а не ослабление, — но записано в decisions/007 вместе с этим кодом.

    Сессии здесь больше нет. С фазы 7 затравку сессии можно менять
    (`PUT /sessions/{uuid}/seed`), а расхождение обязано считаться от той
    затравки, **из которой этот прогон фитили**: иначе одна правка затравки
    пересуживает всю историю прогонов по элементам, которых они не видели.
    Она лежит в самом прогоне — `elements_in` (правило 10).
    """
    if run.status != "ok":
        raise ConflictError(
            f"прогон не сошёлся (статус {run.status}): публиковать его нельзя"
        )
    if run.rms_khz > MAX_RMS_KHZ:
        raise ConflictError(
            f"RMS {run.rms_khz:.3f} кГц больше порога {MAX_RMS_KHZ} кГц"
        )
    if run.n_points < MIN_POINTS:
        raise ConflictError(f"точек {run.n_points}, нужно хотя бы {MIN_POINTS}")

    n_observations = len(run.config.get("observation_ids") or [])
    if n_observations < MIN_OBSERVATIONS:
        raise ConflictError(
            f"наблюдений {n_observations}, нужно хотя бы {MIN_OBSERVATIONS}"
        )

    fitted = Elements.from_tle(run.tle.tle1, run.tle.tle2)
    if fitted.ecc <= MIN_ECC:
        raise ConflictError(
            f"эксцентриситет {fitted.ecc:.2e} схлопнулся в ноль: "
            f"нужно больше {MIN_ECC:.0e}"
        )

    # Расхождение с затравкой на эпохе прогона: фит, уехавший на сотни
    # километров, это не уточнение орбиты, а другой объект или развалившийся
    # оптимизатор. Сравнивается **положение**, а не элементы: при `e ≈ 0`
    # `argp` и `M` вырождены (algorithms.md §5).
    seed = elements_from_dict(run.elements_in)
    separation = separation_km(seed, fitted, run.epoch_mjd)
    if separation > MAX_SEPARATION_KM:
        raise ConflictError(
            f"расхождение с затравкой на эпохе {separation:.1f} км "
            f"больше порога {MAX_SEPARATION_KM} км"
        )
