from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.commands.fit.create import RunFitInteractor
from application.dtos.fit import FitRunResponse, RunFitRequest
from application.services.fitting import fit_run_response
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

create_fit_router = APIRouter(prefix="/sessions", tags=["Fit"])


@create_fit_router.post(
    "/{session_uuid}/fits",
    operation_id="runFit",
    response_model=FitRunResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ExceptionSchema},
        status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema},
    },
)
@inject
async def run_fit(
    session_uuid: UUID,
    request: RunFitRequest,
    interactor: FromDishka[RunFitInteractor],
    user: FromDishka[CurrentUser],
) -> FitRunResponse:
    """Прогон фита. **Синхронный**, обычно менее секунды.

    Ни job id, ни опроса состояния: асинхронных поверхностей в сервисе
    две, а не три (architecture.md).

    `400` — меньше 20 включённых точек или меньше двух наблюдений.
    Несошедшийся прогон это не ошибка: он возвращается со статусом `failed`,
    но с последними элементами и невязками.
    """
    return fit_run_response(await interactor(session_uuid, request, user.sub))
