from fastapi import APIRouter

from presentation.api.v1.routers.health_check import health_router
from presentation.api.v1.routers.session.by_uuid import session_by_uuid_router
from presentation.api.v1.routers.session.create import create_session_router
from presentation.api.v1.routers.session.list import list_sessions_router
from presentation.api.v1.routers.session.reextract import reextract_router
from presentation.api.v1.routers.session.track import track_router
from presentation.api.v1.routers.session.update_track import update_track_router

api_v1_router = APIRouter(prefix="/api/v1")

for router in (
    health_router,
    create_session_router,
    list_sessions_router,
    session_by_uuid_router,
    track_router,
    update_track_router,
    reextract_router,
):
    api_v1_router.include_router(router)
