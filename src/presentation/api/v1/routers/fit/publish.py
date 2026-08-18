from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.commands.fit.publish import PublishInteractor
from application.dtos.publish import PublishRequest, PublishResponse
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

publish_router = APIRouter(prefix="/fits", tags=["Fit"])


@publish_router.post(
    "/{fit_run_id}/publish",
    operation_id="publishFit",
    response_model=PublishResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ExceptionSchema},
        status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema},
        status.HTTP_409_CONFLICT: {"model": ExceptionSchema},
    },
)
@inject
async def publish_fit(
    fit_run_id: UUID,
    request: PublishRequest,
    interactor: FromDishka[PublishInteractor],
    user: FromDishka[CurrentUser],
) -> PublishResponse:
    """Запись TLE в каталог СОНИКС.

    `409` — не пройден порог качества, в теле сказано, какое именно условие
    (decisions/007). Проверяется **до** обращения к каталогу.

    Токен вызывающего идёт в сеть как есть: права проверяет СОНИКС, своей
    модели прав сервис не держит. Нет прав на этот спутник — `mode`
    в ответе становится `propose`, а `published_tle_id` остаётся `null`.
    """
    return await interactor(fit_run_id, request, user.token)
