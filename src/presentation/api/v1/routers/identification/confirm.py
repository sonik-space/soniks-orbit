from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.commands.identification.confirm import ConfirmIdentificationInteractor
from application.dtos.identification import (
    ConfirmIdentificationRequest,
    ConfirmIdentificationResponse,
)
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

confirm_identification_router = APIRouter(
    prefix="/identifications", tags=["Identification"]
)


@confirm_identification_router.post(
    "/{identification_uuid}/confirm",
    operation_id="confirmIdentification",
    response_model=ConfirmIdentificationResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema},
        status.HTTP_409_CONFLICT: {"model": ExceptionSchema},
    },
)
@inject
async def confirm_identification(
    identification_uuid: UUID,
    request: ConfirmIdentificationRequest,
    interactor: FromDishka[ConfirmIdentificationInteractor],
    user: FromDishka[CurrentUser],
) -> ConfirmIdentificationResponse:
    """Подтверждение кандидата: создаётся сессия с этим объектом как затравкой.

    Идентификация перетекает в уточнение (decisions/006). Наблюдение
    переезжает вместе с готовыми точками — второго извлечения не будет.
    """
    return await interactor(identification_uuid, request, user.sub)
