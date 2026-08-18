"""Коды ответов (api.md).

`422` для наблюдения без `satnogs:wf-dat` — **ожидаемое** состояние для
истории до июля 2026 и станций на клиентах старше 2.2.x, а не поломка.
UI обязан объяснять причину.
"""

from dishka import AsyncContainer
from fastapi import FastAPI
from pydantic import BaseModel
from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse

from domain.exceptions import (
    BadRequestError,
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
)
from domain.waterfall import CalibrationError
from infrastructure.auth.keycloak import AuthorizationError

CODES: dict[type[Exception], int] = {
    CalibrationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    BadRequestError: status.HTTP_400_BAD_REQUEST,
    AuthorizationError: status.HTTP_401_UNAUTHORIZED,
    ForbiddenError: status.HTTP_403_FORBIDDEN,
    ConflictError: status.HTTP_409_CONFLICT,
}


class ExceptionSchema(BaseModel):
    detail: str


def setup_handlers(app: FastAPI, container: AsyncContainer) -> None:
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        code = CODES.get(type(exc), status.HTTP_400_BAD_REQUEST)
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    for exc_class in (*CODES, DomainError):
        app.add_exception_handler(exc_class, handle)
