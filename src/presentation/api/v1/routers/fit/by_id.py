from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.dtos.fit import FitRunResponse
from application.queries.fit.by_id import GetFitRunQuery
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

fit_by_id_router = APIRouter(prefix="/fits", tags=["Fit"])


@fit_by_id_router.get(
    "/{fit_run_id}",
    operation_id="getFit",
    response_model=FitRunResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema}},
)
@inject
async def get_fit(
    fit_run_id: UUID,
    query: FromDishka[GetFitRunQuery],
    _user: FromDishka[CurrentUser],
) -> FitRunResponse:
    """Тот же формат, что у `POST /sessions/{uuid}/fits`."""
    return await query(fit_run_id)
