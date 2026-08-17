from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from logging import Logger

from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.configs import Settings
from core.containers import dishka_context, get_providers
from infrastructure.tasks.broker import broker
from presentation.api.exceptions import setup_handlers
from presentation.api.v1.routers import api_v1_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    container: AsyncContainer = app.state.dishka_container
    logger = await container.get(Logger)

    if not broker.is_worker_process:
        await broker.startup()
    try:
        logger.info("Приложение успешно запущено")
        yield
    finally:
        logger.info("Завершаем работу приложения...")
        if not broker.is_worker_process:
            try:
                await broker.shutdown()
            except Exception as e:  # noqa: BLE001 - остановка не должна ронять выход
                logger.error("Ошибка при остановке брокера: %s", e)
        await container.close()


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(
        title="soniks-orbit",
        debug=settings.app.DEBUG,
        lifespan=lifespan,
        docs_url=settings.app.docs_url,
        redoc_url=settings.app.redoc_url,
        openapi_url=settings.app.openapi_url,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors.ALLOW_ORIGINS,
        allow_credentials=settings.cors.ALLOW_CREDENTIALS,
        allow_methods=settings.cors.ALLOW_METHODS,
        allow_headers=settings.cors.ALLOW_HEADERS,
    )
    app.include_router(api_v1_router)

    container = make_async_container(*get_providers(), context=dishka_context(settings))
    setup_dishka(container, app)
    setup_handlers(app, container)

    return app
