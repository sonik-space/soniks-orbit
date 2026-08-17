from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Query

from application.dtos.session import SessionSummaryResponse
from application.queries.session.list import ListSessionsQuery
from infrastructure.auth.keycloak import CurrentUser

list_sessions_router = APIRouter(prefix="/sessions", tags=["Sessions"])


@list_sessions_router.get(
    "",
    operation_id="listSessions",
    response_model=list[SessionSummaryResponse],
)
@inject
async def list_sessions(
    query: FromDishka[ListSessionsQuery],
    user: FromDishka[CurrentUser],
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SessionSummaryResponse]:
    """Сессии вызывающего, новые сверху."""
    return await query(user.sub, limit)
