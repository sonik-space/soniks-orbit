"""Опубликованные и предложенные TLE за последние сутки-неделю.

Это и есть админ-вид, который decisions/007 требует **до** первой боевой
публикации. Он живёт здесь, а не в админке Django: в каталоге запись фита
неотличима от ручной, а провенанс — какой прогон, с каким RMS, по каким
наблюдениям и кто — есть только у сервиса.
"""

from __future__ import annotations

import datetime as dt

from application.dtos.publish import PublicationResponse
from application.interfaces.repositories import FitRunRepository


class ListPublicationsQuery:
    def __init__(self, fit_repo: FitRunRepository) -> None:
        self._fit_repo = fit_repo

    async def __call__(self, days: int) -> list[PublicationResponse]:
        since = dt.datetime.now(dt.UTC) - dt.timedelta(days=days)
        return [
            PublicationResponse(
                fit_run_id=row.fit_run_uuid,
                session_uuid=row.session_uuid,
                session_name=row.session_name,
                norad_id=row.norad_id,
                published_at=row.published_at,
                published_mode=row.published_mode,
                published_tle_id=row.published_tle_id,
                author_sub=row.author_sub,
                rms_khz=row.rms_khz,
                n_points=row.n_points,
            )
            for row in await self._fit_repo.list_published(since)
        ]
