"""Ошибки сервиса. Коды ответов — в `presentation/api/exceptions.py` (api.md).

Один файл вместо структуры по агрегатам, как в `soniks-backend`:
на четырёх сущностях та даёт только навигационные издержки (architecture.md).
"""

from __future__ import annotations


class DomainError(Exception):
    """Общий предок, чтобы обработчик ловил одним `except`."""


class NotFoundError(DomainError):
    """404."""


class BadRequestError(DomainError):
    """400: меньше 20 включённых точек, меньше 2 наблюдений для фита и т.п."""
