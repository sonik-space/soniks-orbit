from dishka import Provider, Scope

from application.commands.fit.create import RunFitInteractor
from application.commands.fit.publish import PublishInteractor
from application.commands.fit.reepoch import ReepochInteractor
from application.commands.identification.confirm import (
    ConfirmIdentificationInteractor,
)
from application.commands.identification.create import CreateIdentificationInteractor
from application.commands.identification.reject import RejectIdentificationInteractor
from application.commands.session.create import CreateSessionInteractor
from application.commands.session.manage import (
    AddObservationsInteractor,
    DeleteSessionInteractor,
    RemoveObservationInteractor,
)
from application.commands.session.reextract import ReextractInteractor
from application.commands.session.update_seed import UpdateSeedInteractor
from application.commands.session.update_track import UpdateTrackInteractor
from application.queries.fit.by_id import GetFitRunQuery
from application.queries.fit.list import ListFitRunsQuery
from application.queries.identification.by_uuid import GetIdentificationQuery
from application.queries.identification.list import ListIdentificationsQuery
from application.queries.identification.track import GetIdentificationTrackQuery
from application.queries.publication.list import ListPublicationsQuery
from application.queries.session.by_uuid import GetSessionQuery, GetTrackQuery
from application.queries.session.list import ListSessionsQuery


def application_provider() -> Provider:
    provider = Provider(scope=Scope.REQUEST)
    provider.provide_all(
        CreateSessionInteractor,
        AddObservationsInteractor,
        RemoveObservationInteractor,
        DeleteSessionInteractor,
        UpdateSeedInteractor,
        UpdateTrackInteractor,
        ReextractInteractor,
        GetSessionQuery,
        GetTrackQuery,
        ListSessionsQuery,
        RunFitInteractor,
        ReepochInteractor,
        PublishInteractor,
        GetFitRunQuery,
        ListFitRunsQuery,
        ListPublicationsQuery,
        CreateIdentificationInteractor,
        ConfirmIdentificationInteractor,
        RejectIdentificationInteractor,
        ListIdentificationsQuery,
        GetIdentificationQuery,
        GetIdentificationTrackQuery,
    )
    return provider
