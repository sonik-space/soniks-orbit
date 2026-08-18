from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter
from starlette import status

from application.commands.identification.create import CreateIdentificationInteractor
from application.dtos.identification import CreateIdentificationRequest
from infrastructure.auth.keycloak import CurrentUser

create_identification_router = APIRouter(
    prefix="/identifications", tags=["Identification"]
)


@create_identification_router.post(
    "",
    operation_id="createIdentification",
    status_code=status.HTTP_202_ACCEPTED,
)
@inject
async def create_identification(
    request: CreateIdentificationRequest,
    interactor: FromDishka[CreateIdentificationInteractor],
    _user: FromDishka[CurrentUser],
) -> None:
    """Ручной запуск перебора по одному наблюдению.

    Кнопка не заменяет автомат: основной путь — почасовой сканер, а этот
    вызов ставит ту же задачу в ту же очередь (decisions/006).
    """
    await interactor(request)
