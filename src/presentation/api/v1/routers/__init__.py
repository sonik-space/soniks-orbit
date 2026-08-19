from fastapi import APIRouter

from presentation.api.v1.routers.fit.by_id import fit_by_id_router
from presentation.api.v1.routers.fit.create import create_fit_router
from presentation.api.v1.routers.fit.list import list_fits_router
from presentation.api.v1.routers.fit.publish import publish_router
from presentation.api.v1.routers.fit.reepoch import reepoch_router
from presentation.api.v1.routers.health_check import health_router
from presentation.api.v1.routers.identification.by_uuid import (
    identification_by_uuid_router,
)
from presentation.api.v1.routers.identification.confirm import (
    confirm_identification_router,
)
from presentation.api.v1.routers.identification.create import (
    create_identification_router,
)
from presentation.api.v1.routers.identification.list import list_identifications_router
from presentation.api.v1.routers.identification.reject import (
    reject_identification_router,
)
from presentation.api.v1.routers.identification.track import identification_track_router
from presentation.api.v1.routers.publication.list import list_publications_router
from presentation.api.v1.routers.session.by_uuid import session_by_uuid_router
from presentation.api.v1.routers.session.create import create_session_router
from presentation.api.v1.routers.session.list import list_sessions_router
from presentation.api.v1.routers.session.manage import manage_session_router
from presentation.api.v1.routers.session.track import track_router
from presentation.api.v1.routers.session.update_seed import update_seed_router
from presentation.api.v1.routers.session.update_track import update_track_router

api_v1_router = APIRouter(prefix="/api/v1")

for router in (
    health_router,
    create_session_router,
    list_sessions_router,
    session_by_uuid_router,
    manage_session_router,
    update_seed_router,
    track_router,
    update_track_router,
    create_fit_router,
    list_fits_router,
    fit_by_id_router,
    reepoch_router,
    publish_router,
    list_publications_router,
    create_identification_router,
    list_identifications_router,
    # `/{uuid}/track` объявлен раньше `/{uuid}`: иначе `track` съел бы
    # параметр пути и запрос водопада ушёл бы в чтение задания.
    identification_track_router,
    identification_by_uuid_router,
    confirm_identification_router,
    reject_identification_router,
):
    api_v1_router.include_router(router)
