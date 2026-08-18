from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.commands.session.update_seed import UpdateSeedInteractor
from application.dtos.session import SessionResponse, UpdateSeedRequest
from application.queries.session.by_uuid import GetSessionQuery
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

update_seed_router = APIRouter(prefix="/sessions", tags=["Sessions"])


@update_seed_router.put(
    "/{session_uuid}/seed",
    operation_id="updateSeed",
    response_model=SessionResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ExceptionSchema},
        status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema},
    },
)
@inject
async def update_seed(
    session_uuid: UUID,
    request: UpdateSeedRequest,
    interactor: FromDishka[UpdateSeedInteractor],
    query: FromDishka[GetSessionQuery],
    _user: FromDishka[CurrentUser],
) -> SessionResponse:
    """Замена затравки сессии: готовые строки, правка элементов или шаблон.

    Прогоны фита не пересчитываются и не пересуживаются: каждый хранит свою
    затравку в `elements_in`, и порог публикации читает её (decisions/014).
    """
    await interactor(session_uuid, request)
    return await query(session_uuid)
