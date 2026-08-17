from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter

from application.dtos.fit import FitRunSummaryResponse
from application.queries.fit.list import ListFitRunsQuery
from infrastructure.auth.keycloak import CurrentUser

list_fits_router = APIRouter(prefix="/sessions", tags=["Fit"])


@list_fits_router.get(
    "/{session_uuid}/fits",
    operation_id="listFits",
    response_model=list[FitRunSummaryResponse],
)
@inject
async def list_fits(
    session_uuid: UUID,
    query: FromDishka[ListFitRunsQuery],
    _user: FromDishka[CurrentUser],
) -> list[FitRunSummaryResponse]:
    """История прогонов, новые сверху.

    Строки компактные: без невязок и поточечных блоков. Полное тело —
    из `GET /fits/{fit_run_id}`.
    """
    return await query(session_uuid)
