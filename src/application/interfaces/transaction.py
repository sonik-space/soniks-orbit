"""Фиксация изменений без знания о SQLAlchemy.

Интерфейс с одной реализацией заводится здесь не «на будущее», а потому что
без него `application/` пришлось бы импортировать `sqlalchemy` (правило 8).
"""

from __future__ import annotations

from typing import Protocol


class Transaction(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def flush(self) -> None: ...
