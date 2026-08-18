"""Состав сессии: добавление и удаление наблюдений, удаление сессии.

Три эндпоинта, объявленные в `api.md` с фазы 2. Роутер один: пути соседние,
а разносить по файлам ради одного обработчика в каждом смысла нет.
"""

from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.commands.session.manage import (
    AddObservationsInteractor,
    DeleteSessionInteractor,
    RemoveObservationInteractor,
)
from application.dtos.session import AddObservationsRequest, SessionResponse
from application.queries.session.by_uuid import GetSessionQuery
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

manage_session_router = APIRouter(prefix="/sessions", tags=["Sessions"])

_NOT_FOUND = {status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema}}
_NOT_FOUND_OR_CONFLICT = _NOT_FOUND | {
    status.HTTP_409_CONFLICT: {"model": ExceptionSchema}
}


@manage_session_router.post(
    "/{session_uuid}/observations",
    operation_id="addObservations",
    response_model=SessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_NOT_FOUND,
)
@inject
async def add_observations(
    session_uuid: UUID,
    request: AddObservationsRequest,
    interactor: FromDishka[AddObservationsInteractor],
    query: FromDishka[GetSessionQuery],
    _user: FromDishka[CurrentUser],
) -> SessionResponse:
    """Дописать наблюдения в сессию — шаг 2 гайда.

    `202`: снимки заморожены и сессия обновлена, но извлечение точек только
    поставлено в очередь. Уже входящие в сессию наблюдения пропускаются.
    """
    await interactor(session_uuid, request)
    return await query(session_uuid)


@manage_session_router.delete(
    "/{session_uuid}/observations/{observation_id}",
    operation_id="removeObservation",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_NOT_FOUND_OR_CONFLICT,
)
@inject
async def remove_observation(
    session_uuid: UUID,
    observation_id: int,
    interactor: FromDishka[RemoveObservationInteractor],
    _user: FromDishka[CurrentUser],
) -> None:
    """Убрать наблюдение из сессии.

    Прогоны фита не трогаются: каждый хранит свой список наблюдений и свои
    невязки, и переписывать их задним числом нельзя (правило 10).
    """
    await interactor(session_uuid, observation_id)


@manage_session_router.delete(
    "/{session_uuid}",
    operation_id="deleteSession",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_NOT_FOUND_OR_CONFLICT,
)
@inject
async def delete_session(
    session_uuid: UUID,
    interactor: FromDishka[DeleteSessionInteractor],
    _user: FromDishka[CurrentUser],
) -> None:
    """Удалить сессию вместе с наблюдениями и прогонами.

    `409`, если сессия опубликована: на неё ссылается `Tle.url` в каталоге
    СОНИКС, и это единственный признак происхождения записи.
    """
    await interactor(session_uuid)
