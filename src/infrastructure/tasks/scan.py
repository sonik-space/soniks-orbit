"""Почасовой сканер: наблюдения неопознанных объектов уходят в идентификацию.

Автомат, а не кнопка: вариант «только по кнопке» отвергнут в decisions/006,
потому что теряется заявленное «в автомате с коррекцией человека».

Порядок проверок дёшево→дорого, как в `scripts/phase0/scan_observations.py`.
Замер на боевом потоке: за двое суток ~500 наблюдений, из них 2.4% у объектов
с `unknown=True` — порядка шести заданий в сутки. Флаг `waterfall_status`
в фильтр **не идёт**: он проставляется человеком и на боевых данных стоит
у 5 наблюдений из 500, то есть как признак «есть сигнал» бесполезен.
Признаком служит наше извлечение (decisions/006).
"""

import datetime as dt
from logging import getLogger

from dishka.integrations.taskiq import FromDishka, inject

from application.interfaces.network_api import NetworkApi
from application.interfaces.repositories import IdentificationRepository
from application.interfaces.tasks import IdentificationQueue
from core.configs import settings
from infrastructure.tasks.broker import broker

logger = getLogger(settings.logging.TASKIQ_NAME)

# Окно поиска. С перекрытием: наблюдение появляется в API не мгновенно,
# а повтор по уже разобранному отсекается уникальностью `observation_id`.
SCAN_WINDOW_HOURS = 26

# Метаданные `satnogs:wf-dat` пишет только клиент 2.2.x (algorithms.md §1.8).
# Версия видна прямо в списке наблюдений, поэтому 14% потока отсеиваются
# **не скачивая PNG**.
USABLE_CLIENT_PREFIX = "2.2."


@broker.task(
    task_name="Scan for identification",
    retry_on_error=True,
    schedule=[{"cron": "0 * * * *"}],
)
@inject(patch_module=True)
async def scan_task(
    api: FromDishka[NetworkApi],
    repo: FromDishka[IdentificationRepository],
    queue: FromDishka[IdentificationQueue],
) -> None:
    unknown = {
        satellite["norad"]
        for satellite in await api.list_unknown_satellites()
        if satellite.get("norad") and satellite.get("status") == "alive"
    }
    logger.info("Неопознанных живых объектов в каталоге: %d", len(unknown))

    now = dt.datetime.now(dt.UTC)
    window_start = now - dt.timedelta(hours=SCAN_WINDOW_HOURS)

    fresh: list[int] = []
    async for observation in api.iter_observations(
        start=window_start.isoformat(), end=now.isoformat()
    ):
        if observation.get("norad_cat_id") not in unknown:
            continue
        if not observation.get("waterfall"):
            continue
        if not str(observation.get("client_version") or "").startswith(
            USABLE_CLIENT_PREFIX
        ):
            continue
        fresh.append(observation["id"])

    known = await repo.known_observation_ids(fresh)
    queued = [oid for oid in fresh if oid not in known]
    for observation_id in queued:
        await queue.enqueue(observation_id)

    logger.info(
        "Сканирование: подходящих наблюдений %d, уже разобрано %d, поставлено %d",
        len(fresh),
        len(known),
        len(queued),
    )
