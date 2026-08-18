from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.dtos.session import TrackResponse
from application.queries.session.by_uuid import GetTrackQuery
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

track_router = APIRouter(prefix="/sessions", tags=["Track"])


@track_router.get(
    "/{session_uuid}/observations/{observation_id}/track",
    operation_id="getTrack",
    response_model=TrackResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema}},
)
@inject
async def get_track(
    session_uuid: UUID,
    observation_id: int,
    query: FromDishka[GetTrackQuery],
    _user: FromDishka[CurrentUser],
    fit: UUID | None = None,
) -> TrackResponse:
    """Калибровка, точки, состояние извлечения и модельная кривая.

    Пустой набор точек при `status: ok` — **нормальное** состояние, а не
    ошибка (decisions/001): UI показывает его спокойно и с заметной кнопкой
    ручной разметки, иначе гибридная автоматизация не работает.

    `?fit=` накладывает любой прогон сессии, а не только последний: шаг 5
    гайда — это проверка конкретного TLE по наблюдению, которого в том фите
    могло и не быть.
    """
    return await query(session_uuid, observation_id, fit)
