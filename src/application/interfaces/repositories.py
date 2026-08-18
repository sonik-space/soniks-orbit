"""Хранение сессий уточнения и прогонов фита.

Репозиторий заданий идентификации появится в фазе 6 вместе со сценарием.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from domain.models import (
    FitRun,
    ObservationTrack,
    OdSession,
    Publication,
    SessionSummary,
    TleLines,
)


class SessionRepository(Protocol):
    async def create(
        self,
        *,
        name: str,
        norad_id: int | None,
        owner_sub: str,
        seed: tuple[str, str, str],
        seed_source: str,
        observations: list[tuple[int, dict[str, Any]]],
    ) -> OdSession:
        """Создаёт сессию вместе с наблюдениями.

        `observations` — пары `(observation_id, снимок ответа API)`. Снимок
        замораживается целиком (правило 10).
        """
        ...

    async def get(self, session_uuid: UUID) -> OdSession | None: ...

    async def list_for_owner(self, owner_sub: str, limit: int) -> list[SessionSummary]:
        """Сессии одного человека, новые сверху. Точки не читаются: списку
        нужны только шапка сессии и число наблюдений."""
        ...

    async def get_observation(
        self, session_uuid: UUID, observation_id: int
    ) -> ObservationTrack | None: ...

    async def save_extraction(
        self,
        observation_uuid: UUID,
        *,
        status: str,
        error: str | None = None,
        calibration: dict | None = None,
        points: dict | None = None,
        diagnostics: dict | None = None,
    ) -> None: ...

    async def save_points(
        self, observation_uuid: UUID, *, points: dict, diagnostics: dict
    ) -> None:
        """Правка трека человеком: меняются точки и диагностика, всё остальное
        остаётся. Отдельно от `save_extraction`, которая пишет результат
        извлечения целиком и умолчаниями `None` стирает калибровку."""
        ...

    async def set_status(self, session_uuid: UUID, status: str) -> None:
        """`draft` → `fitted` после удачного прогона."""
        ...


class FitRunRepository(Protocol):
    """Прогоны фита. Отдельный протокол, а не рост `SessionRepository`:
    сценарий свой, и таблица своя."""

    async def create(
        self,
        *,
        session_uuid: UUID,
        author_sub: str,
        config: dict[str, Any],
        elements_in: dict[str, Any],
        elements_out: dict[str, Any],
        tle: TleLines,
        epoch_mjd: float,
        rms_khz: float,
        rms_pre_khz: float,
        n_points: int,
        per_observation: list[dict[str, Any]],
        residuals: dict[str, Any],
        prior_dominated: list[str],
        status: str,
    ) -> FitRun: ...

    async def get(self, fit_run_id: UUID) -> FitRun | None: ...

    async def list_for_session(self, session_uuid: UUID) -> list[FitRun]:
        """История прогонов, новые сверху."""
        ...

    async def latest(self, session_uuid: UUID) -> FitRun | None:
        """Последний прогон **любого** статуса: у неуспешного тоже есть
        элементы и невязки, и молчать о нём хуже, чем показать со статусом."""
        ...

    async def mark_published(
        self,
        fit_run_id: UUID,
        *,
        mode: str,
        published_tle_id: int | None,
        tle: TleLines,
    ) -> None:
        """Отметка публикации или предложения.

        Строки перезаписываются: при переносе эпохи в каталог уходит не то TLE,
        что лежало в прогоне, и хранить надо опубликованное — иначе провенанс
        указывает на строки, которых в каталоге нет.
        """
        ...

    async def list_published(self, since: datetime) -> list[Publication]:
        """Публикации и предложения свежее указанного момента, новые сверху."""
        ...
