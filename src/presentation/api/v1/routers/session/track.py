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
    fit: str | None = None,
) -> TrackResponse:
    """Калибровка, точки, состояние извлечения и модельная кривая.

    Пустой набор точек при `status: ok` — **нормальное** состояние, а не
    ошибка (decisions/001): UI показывает его спокойно и с заметной кнопкой
    ручной разметки, иначе гибридная автоматизация не работает.

    `?fit=` накладывает любой прогон сессии, а не только последний: шаг 5
    гайда — это проверка конкретного TLE по наблюдению, которого в том фите
    могло и не быть.

    `?fit=seed` — кривая затравки, до всякого фита. Без неё первому прогону
    не с чем сравниться, а «было / стало» читается только числом RMS.

    Тип параметра — `str`, а не `UUID | Literal["seed"]`, хотя значений ровно
    два вида. Причина внешняя: `openapi-generator` разворачивает такой `anyOf`
    в пустой интерфейс и ломает `typecheck` фронта. Разбор строки делает
    `GetTrackQuery`, ошибочное значение — `404`, а не молчаливый последний
    прогон.
    """
    return await query(session_uuid, observation_id, fit)
