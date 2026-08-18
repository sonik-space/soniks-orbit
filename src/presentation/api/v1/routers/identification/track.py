from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.dtos.identification import IdentificationTrackResponse
from application.queries.identification.track import GetIdentificationTrackQuery
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

identification_track_router = APIRouter(
    prefix="/identifications", tags=["Identification"]
)


@identification_track_router.get(
    "/{identification_uuid}/track",
    operation_id="getIdentificationTrack",
    response_model=IdentificationTrackResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema}},
)
@inject
async def get_identification_track(
    identification_uuid: UUID,
    query: FromDishka[GetIdentificationTrackQuery],
    _user: FromDishka[CurrentUser],
) -> IdentificationTrackResponse:
    """Водопад задания: калибровка, точки и кривая лучшего кандидата.

    Форма та же, что у трека наблюдения сессии: панель водопада на фронте
    одна и та же, а сессии у задания ещё нет. Кривую считает сервер —
    фронт эфемерид не вычисляет (правило 9).
    """
    return await query(identification_uuid)
