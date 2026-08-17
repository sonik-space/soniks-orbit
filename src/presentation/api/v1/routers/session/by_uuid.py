from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.dtos.session import SessionResponse
from application.queries.session.by_uuid import GetSessionQuery
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

session_by_uuid_router = APIRouter(prefix="/sessions", tags=["Sessions"])


@session_by_uuid_router.get(
    "/{session_uuid}",
    operation_id="getSession",
    response_model=SessionResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema}},
)
@inject
async def get_session(
    session_uuid: UUID,
    query: FromDishka[GetSessionQuery],
    _user: FromDishka[CurrentUser],
) -> SessionResponse:
    return await query(session_uuid)
