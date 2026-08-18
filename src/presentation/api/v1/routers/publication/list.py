from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Query

from application.dtos.publish import PublicationResponse
from application.queries.publication.list import ListPublicationsQuery
from infrastructure.auth.keycloak import CurrentUser

list_publications_router = APIRouter(prefix="/publications", tags=["Publication"])


@list_publications_router.get(
    "",
    operation_id="listPublications",
    response_model=list[PublicationResponse],
)
@inject
async def list_publications(
    query: FromDishka[ListPublicationsQuery],
    _user: FromDishka[CurrentUser],
    days: int = Query(default=7, ge=1, le=90),
) -> list[PublicationResponse]:
    """Опубликованные и предложенные TLE за последние `days` суток, новые сверху.

    Админ-вид, который нужен **до** первой боевой публикации (decisions/007).
    В каталоге СОНИКС запись фита неотличима от ручной, поэтому провенанс
    смотрят здесь.
    """
    return await query(days)
