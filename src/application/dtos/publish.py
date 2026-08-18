"""Формы переноса эпохи и публикации (api.md).

Отдельный модуль, а не рост `dtos/fit.py`: сценарий третий, и общее у них —
`TleSchema` из `dtos/common.py`.

Единицы (правило 2): эпоха наружу — ISO 8601 UTC. Форма `yyddd` принимается
на входе, потому что так её показывает сама строка TLE и так её диктует
оператор, но внутри она сразу становится MJD.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from application.dtos.common import TleSchema


class EpochRequest(BaseModel):
    """Куда переносить эпоху. Ровно одно поле из трёх.

    Три формы, потому что оператор приходит с разными источниками: ISO —
    из интерфейса, `yyddd` — переписанное из чужой строки TLE,
    `latest_observation` — «на конец последнего прохода», самый частый выбор
    и единственный, который сервис может посчитать сам.
    """

    epoch_iso: datetime | None = None
    epoch_yyddd: str | None = Field(default=None, pattern=r"^\d{5}\.\d+$")
    epoch: Literal["latest_observation"] | None = None

    @model_validator(mode="after")
    def exactly_one(self) -> EpochRequest:
        given = [f for f in (self.epoch_iso, self.epoch_yyddd, self.epoch) if f]
        if len(given) != 1:
            raise ValueError("нужно ровно одно поле: epoch_iso, epoch_yyddd или epoch")
        return self


class ReepochResponse(BaseModel):
    """`epoch` рядом со строками не для красоты: при `latest_observation`
    момент выбирает сервер, и без него оператор не видит, куда попал."""

    epoch: datetime
    tle: TleSchema


class PublishRequest(BaseModel):
    """`reepoch_to` необязателен: без него публикуется эпоха самого прогона.

    `mode`: `publish` — записать в каталог СОНИКС, `propose` — оставить
    предложением. Не владеешь спутником — `publish` возвращается
    предложением, а не отказом (decisions/007).
    """

    mode: Literal["publish", "propose"] = "publish"
    reepoch_to: EpochRequest | None = None


class PublishResponse(BaseModel):
    """`mode` возвращается, потому что он мог смениться на `propose`,
    а `published_tle_id` при этом `null`."""

    mode: Literal["publish", "propose"]
    published_tle_id: int | None
    epoch: datetime
    tle: TleSchema


class PublicationResponse(BaseModel):
    """Строка админ-вида «опубликованные за 7 дней» (decisions/007).

    Живёт здесь, а не в Django: в каталоге публикация фита неотличима
    от ручной строки, а весь провенанс — прогон, наблюдения, RMS — лежит
    только у нас.
    """

    fit_run_id: UUID
    session_uuid: UUID
    session_name: str
    norad_id: int | None
    published_at: datetime
    published_mode: str
    published_tle_id: int | None
    author_sub: str
    rms_khz: float
    n_points: int
