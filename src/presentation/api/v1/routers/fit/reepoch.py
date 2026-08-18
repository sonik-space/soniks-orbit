from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.commands.fit.reepoch import ReepochInteractor
from application.dtos.publish import EpochRequest, ReepochResponse
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

reepoch_router = APIRouter(prefix="/fits", tags=["Fit"])


@reepoch_router.post(
    "/{fit_run_id}/reepoch",
    operation_id="reepochFit",
    response_model=ReepochResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ExceptionSchema},
        status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema},
    },
)
@inject
async def reepoch_fit(
    fit_run_id: UUID,
    request: EpochRequest,
    interactor: FromDishka[ReepochInteractor],
    _user: FromDishka[CurrentUser],
) -> ReepochResponse:
    """Предпросмотр строк TLE на другую эпоху. Ничего не сохраняет.

    Ровно одно поле из трёх: `epoch_iso`, `epoch_yyddd` или
    `epoch: "latest_observation"`.
    """
    return await interactor(fit_run_id, request)
