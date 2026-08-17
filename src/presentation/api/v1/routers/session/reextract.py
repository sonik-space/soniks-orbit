from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.commands.session.reextract import ReextractInteractor
from application.dtos.session import ReextractRequest
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

reextract_router = APIRouter(prefix="/sessions", tags=["Track"])


@reextract_router.post(
    "/{session_uuid}/observations/{observation_id}/reextract",
    operation_id="reextractTrack",
    status_code=status.HTTP_202_ACCEPTED,
    responses={status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema}},
)
@inject
async def reextract(
    session_uuid: UUID,
    observation_id: int,
    request: ReextractRequest,
    interactor: FromDishka[ReextractInteractor],
    _user: FromDishka[CurrentUser],
) -> None:
    """Перезапуск автоизвлечения с другими параметрами.

    Ручные точки сохраняются, автоматические заменяются.
    """
    await interactor(session_uuid, observation_id, request)
