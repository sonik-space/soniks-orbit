from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.commands.identification.reject import RejectIdentificationInteractor
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

reject_identification_router = APIRouter(
    prefix="/identifications", tags=["Identification"]
)


@reject_identification_router.post(
    "/{identification_uuid}/reject",
    operation_id="rejectIdentification",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema},
        status.HTTP_409_CONFLICT: {"model": ExceptionSchema},
    },
)
@inject
async def reject_identification(
    identification_uuid: UUID,
    interactor: FromDishka[RejectIdentificationInteractor],
    user: FromDishka[CurrentUser],
) -> None:
    """Отклонение задания. Повторный перебор его больше не трогает."""
    await interactor(identification_uuid, user.sub)
