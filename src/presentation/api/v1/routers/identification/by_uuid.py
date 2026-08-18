from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.dtos.identification import IdentificationResponse
from application.queries.identification.by_uuid import GetIdentificationQuery
from infrastructure.auth.keycloak import CurrentUser
from presentation.api.exceptions import ExceptionSchema

identification_by_uuid_router = APIRouter(
    prefix="/identifications", tags=["Identification"]
)


@identification_by_uuid_router.get(
    "/{identification_uuid}",
    operation_id="getIdentification",
    response_model=IdentificationResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ExceptionSchema}},
)
@inject
async def get_identification(
    identification_uuid: UUID,
    query: FromDishka[GetIdentificationQuery],
    _user: FromDishka[CurrentUser],
) -> IdentificationResponse:
    """Задание с ранжированными кандидатами.

    `margin` порядка единицы означает, что кандидаты неразличимы, то есть
    перебор ничего не решил: UI обязан подавать такое задание как
    «не определено», а не как список кандидатов.
    """
    return await query(identification_uuid)
