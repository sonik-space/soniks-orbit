from fastapi import APIRouter

from presentation.api.v1.routers.health_check import health_router
from presentation.api.v1.routers.session.by_uuid import session_by_uuid_router
from presentation.api.v1.routers.session.create import create_session_router
from presentation.api.v1.routers.session.track import track_router

api_v1_router = APIRouter(prefix="/api/v1")

for router in (
    health_router,
    create_session_router,
    session_by_uuid_router,
    track_router,
):
    api_v1_router.include_router(router)
