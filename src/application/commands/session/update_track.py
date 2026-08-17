"""Полная замена набора точек трека.

Здесь заменяется ручная разметка из `soniks-waterfall-tabulation-helper`:
человек удаляет мусор и дорисовывает пропуски, а сервер пересчитывает
абсолютную частоту и диагностику.
"""

from __future__ import annotations

from uuid import UUID

import numpy as np

from application.dtos.session import UpdateTrackRequest
from application.interfaces.repositories import SessionRepository
from application.interfaces.transaction import Transaction
from application.services.extraction import measure_points
from domain.exceptions import BadRequestError, NotFoundError


class UpdateTrackInteractor:
    def __init__(self, repo: SessionRepository, transaction: Transaction) -> None:
        self._repo = repo
        self._transaction = transaction

    async def __call__(
        self, session_uuid: UUID, observation_id: int, request: UpdateTrackRequest
    ) -> None:
        track = await self._repo.get_observation(session_uuid, observation_id)
        if track is None:
            raise NotFoundError(
                f"наблюдения {observation_id} нет в сессии {session_uuid}"
            )
        if not track.calibration:
            raise BadRequestError(
                f"наблюдение {observation_id} ещё не откалибровано: "
                "центральная частота неизвестна, абсолютную частоту не посчитать"
            )

        p = request.points
        mjd = np.asarray(p.mjd, dtype=float)
        f_offset_hz = np.asarray(p.f_offset_hz, dtype=float)
        weight = np.asarray(p.weight, dtype=float)
        snr = p.snr if p.snr is not None else [0.0] * len(p.mjd)

        # Доплер снимается тем же кодом, что и при извлечении, по тому же
        # замороженному TLE (правила 9 и 10). Второй реализации нет.
        m = measure_points(
            track.meta, track.calibration["center_freq_hz"], mjd, f_offset_hz, weight
        )
        if m.sgp4_errors:
            raise BadRequestError(
                f"SGP4 вернул коды ошибок на {m.sgp4_errors} точках: "
                "затравку наблюдения нельзя прогнать на эти времена"
            )

        await self._repo.save_points(
            track.uuid,
            points={
                "mjd": p.mjd,
                "f_abs_hz": m.f_abs_hz.tolist(),
                "f_offset_hz": p.f_offset_hz,
                "snr": snr,
                "weight": p.weight,
                "enabled": p.enabled,
                "source": list(p.source),
            },
            diagnostics=m.diagnostics(
                (track.diagnostics or {}).get("overlay_frac", 0.0)
            ),
        )
        await self._transaction.commit()
