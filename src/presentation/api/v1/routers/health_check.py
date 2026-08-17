from fastapi import APIRouter
from pydantic import BaseModel

health_router = APIRouter(prefix="/health", tags=["Health"])


class HealthResponse(BaseModel):
    status: str


@health_router.get("/", operation_id="healthCheck", include_in_schema=False)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")
