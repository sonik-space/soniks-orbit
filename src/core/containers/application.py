from dishka import Provider, Scope

from application.commands.fit.create import RunFitInteractor
from application.commands.session.create import CreateSessionInteractor
from application.commands.session.reextract import ReextractInteractor
from application.commands.session.update_track import UpdateTrackInteractor
from application.queries.fit.by_id import GetFitRunQuery
from application.queries.fit.list import ListFitRunsQuery
from application.queries.session.by_uuid import GetSessionQuery, GetTrackQuery
from application.queries.session.list import ListSessionsQuery


def application_provider() -> Provider:
    provider = Provider(scope=Scope.REQUEST)
    provider.provide_all(
        CreateSessionInteractor,
        UpdateTrackInteractor,
        ReextractInteractor,
        GetSessionQuery,
        GetTrackQuery,
        ListSessionsQuery,
        RunFitInteractor,
        GetFitRunQuery,
        ListFitRunsQuery,
    )
    return provider
