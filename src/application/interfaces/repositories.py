"""Хранение сессий уточнения.

Фазе 2 нужны только сессии и их наблюдения; репозитории прогонов фита
и заданий идентификации появятся в фазах 4 и 6 вместе с их сценариями.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from domain.models import ObservationTrack, OdSession


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
