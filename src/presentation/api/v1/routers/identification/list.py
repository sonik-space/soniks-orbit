from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Query

from application.dtos.identification import IdentificationSummaryResponse
from application.queries.identification.list import ListIdentificationsQuery
from infrastructure.auth.keycloak import CurrentUser

list_identifications_router = APIRouter(
    prefix="/identifications", tags=["Identification"]
)


@list_identifications_router.get(
    "",
    operation_id="listIdentifications",
    response_model=list[IdentificationSummaryResponse],
)
@inject
async def list_identifications(
    query: FromDishka[ListIdentificationsQuery],
    _user: FromDishka[CurrentUser],
    stage: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[IdentificationSummaryResponse]:
    """Задания идентификации, новые сверху.

    Параметр называется `stage`, а не `status`: так называется колонка,
    и заводить второе имя тому же полю незачем. Кандидаты в строке урезаны
    до лучшего — полный перебор по каталогу это тысячи строк на задание.
    """
    return await query(stage, limit)
