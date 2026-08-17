from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.commands.session.create import CreateSessionInteractor
from application.dtos.session import CreateSessionRequest, SessionResponse
from application.queries.session.by_uuid import GetSessionQuery
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

create_session_router = APIRouter(prefix="/sessions", tags=["Sessions"])


@create_session_router.post(
    "",
    operation_id="createSession",
    response_model=SessionResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ExceptionSchema},
        status.HTTP_401_UNAUTHORIZED: {"model": ExceptionSchema},
    },
    status_code=status.HTTP_201_CREATED,
)
@inject
async def create_session(
    request: CreateSessionRequest,
    interactor: FromDishka[CreateSessionInteractor],
    query: FromDishka[GetSessionQuery],
    user: FromDishka[CurrentUser],
) -> SessionResponse:
    """Создаёт сессию и ставит извлечение треков в очередь."""
    session = await interactor(request, owner_sub=user.sub)
    return await query(session.uuid)
