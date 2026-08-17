from dishka import Provider, Scope

from application.commands.session.create import CreateSessionInteractor
from application.queries.session.by_uuid import GetSessionQuery, GetTrackQuery


def application_provider() -> Provider:
    provider = Provider(scope=Scope.REQUEST)
    provider.provide_all(CreateSessionInteractor, GetSessionQuery, GetTrackQuery)
    return provider
