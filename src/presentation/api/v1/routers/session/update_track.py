from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.commands.session.update_track import UpdateTrackInteractor
from application.dtos.session import TrackResponse, UpdateTrackRequest
from application.queries.session.by_uuid import GetTrackQuery
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

update_track_router = APIRouter(prefix="/sessions", tags=["Track"])


@update_track_router.put(
    "/{session_uuid}/observations/{observation_id}/track",
    operation_id="updateTrack",
    response_model=TrackResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ExceptionSchema},
        status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema},
    },
)
@inject
async def update_track(
    session_uuid: UUID,
    observation_id: int,
    request: UpdateTrackRequest,
    interactor: FromDishka[UpdateTrackInteractor],
    query: FromDishka[GetTrackQuery],
    _user: FromDishka[CurrentUser],
) -> TrackResponse:
    """Полная замена набора точек.

    `f_abs_hz` от клиента **не принимается** — сервер считает его сам
    по замороженному TLE наблюдения (правило 9). Ручная точка приходит
    с `source: "manual"` и `f_offset_hz`.
    """
    await interactor(session_uuid, observation_id, request)
    return await query(session_uuid, observation_id)
