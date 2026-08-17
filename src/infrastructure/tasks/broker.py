from logging import Logger

from dishka import AsyncContainer, make_async_container
from dishka.integrations.taskiq import TaskiqProvider, setup_dishka
from taskiq import SmartRetryMiddleware, TaskiqEvents, TaskiqState
from taskiq_aio_pika import AioPikaBroker

from core.configs import settings


def get_broker() -> AioPikaBroker:
    return AioPikaBroker(
        url=settings.rabbit.url,
        queue_name=settings.aio_pika_broker.QUEUE_NAME,
        exchange_name=settings.aio_pika_broker.EXCHANGE_NAME,
        max_priority=settings.aio_pika_broker.MAX_PRIORITY,
    ).with_middlewares(
        SmartRetryMiddleware(
            default_retry_count=3,
            default_delay=60,
            use_jitter=True,
            use_delay_exponent=True,
            max_delay_exponent=600,
        ),
    )


broker = get_broker()


def create_async_container() -> AsyncContainer:
    from core.containers import dishka_context, get_providers

    container = make_async_container(
        *get_providers(), TaskiqProvider(), context=dishka_context(settings)
    )
    setup_dishka(container=container, broker=broker)
    return container


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState) -> None:
    state.container = create_async_container()
    logger = await state.container.get(Logger)
    logger.info("Taskiq успешно запущен")


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state: TaskiqState) -> None:
    logger = await state.container.get(Logger)
    logger.info("Taskiq успешно завершил работу")
    await state.container.close()
