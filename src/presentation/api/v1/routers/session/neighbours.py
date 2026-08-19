from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.dtos.session import NeighboursResponse
from application.queries.session.neighbours import GetNeighbourCurvesQuery
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

neighbours_router = APIRouter(prefix="/sessions", tags=["Track"])


@neighbours_router.get(
    "/{session_uuid}/observations/{observation_id}/neighbours",
    operation_id="getNeighbours",
    response_model=NeighboursResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema}},
)
@inject
async def get_neighbours(
    session_uuid: UUID,
    observation_id: int,
    query: FromDishka[GetNeighbourCurvesQuery],
    _user: FromDishka[CurrentUser],
) -> NeighboursResponse:
    """Доплеровские кривые соседей по запуску поверх этого водопада.

    Упражнение 2 гайда, клавиша `p` в `rfplot`. Тому, кто размечает, нужно
    знать, какая линия чья: своя — почти вертикальная (запись ведётся
    с доплеровской коррекцией), а широкая S-кривая рядом — это чужой объект,
    который станция не ведёт. Наложение его **называет**.

    Пустой список — запуск неизвестен: обозначение берётся из строки TLE
    наблюдения, и у наблюдения без TLE его нет. Это штатное состояние.
    """
    return await query(session_uuid, observation_id)
