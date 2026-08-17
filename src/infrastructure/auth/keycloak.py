"""Валидация Keycloak JWT.

Перенесено из `soniks-backend/src/presentation/api/auth/token.py` без ветки
админ-панели: своей админки у сервиса нет. Провайдер личности общий с монолитом
(`mozilla-django-oidc`) и с v2, поэтому валидация одинакова до и после
переезда, а `/api/me/` не нужен (decisions/008).

Прав на публикацию сервис не хранит: они проверяются на стороне СОНИКС
при вызове `POST /api/tles/` (integration.md). Отсюда нужен только `sub` —
владелец сессии.
"""

from __future__ import annotations

from logging import Logger
from typing import Any

import jwt
from starlette.requests import Request

from core.configs.auth import AuthSettings
from domain.exceptions import DomainError


class AuthorizationError(DomainError):
    """401."""


class PyJWKClientCache:
    """Ключи Keycloak кешируются: иначе на каждый запрос был бы поход в realm."""

    def __init__(self, settings: AuthSettings) -> None:
        self._jwk_client = jwt.PyJWKClient(
            settings.keycloak.url_jwk,
            cache_keys=True,
            lifespan=settings.keycloak.CACHING_OF_CERTIFICATES_IN_SECONDS,
            timeout=settings.keycloak.CERTIFICATE_REQUEST_TIMEOUT_IN_SECONDS,
        )

    def get_signing_key(self, token: str) -> jwt.PyJWK:
        return self._jwk_client.get_signing_key_from_jwt(token)


class CurrentUser:
    """`sub` из токена — владелец сессии (`owner_sub`)."""

    def __init__(
        self,
        logger: Logger,
        jwk_client: PyJWKClientCache,
        request: Request,
        auth_settings: AuthSettings,
    ) -> None:
        self._logger = logger
        self._jwk_client = jwk_client
        self._request = request
        self._settings = auth_settings

    @property
    def sub(self) -> str:
        payload = self._verify(self._extract())
        sub = payload.get("sub")
        if not sub:
            self._logger.error("В токене нет sub")
            raise AuthorizationError()
        return str(sub)

    def _extract(self) -> str:
        header = self._request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            self._logger.debug("Отсутствует или неверна схема заголовка авторизации")
            raise AuthorizationError()

        token = header.removeprefix("Bearer ").strip()
        if not token or len(token) > self._settings.jwt.MAX_JWT_TOKEN_LENGTH:
            raise AuthorizationError()
        return token

    def _verify(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(
                token,
                self._jwk_client.get_signing_key(token).key,
                algorithms=self._settings.jwt.ALGORITHM,
                audience=self._settings.jwt.AUDIENCE,
                options={
                    "verify_aud": True,
                    "verify_signature": True,
                    "require": ["exp", "iat"],
                },
                issuer=self._settings.jwt.ISSUER,
                leeway=self._settings.jwt.LEEWAY,
            )
        except jwt.PyJWTError as e:
            self._logger.error("Ошибка верификации JWT: %s", e)
            raise AuthorizationError()


class MockCurrentUser(CurrentUser):
    """Только для локального окружения: `AppSettings` запрещает `DISABLE_AUTH`
    везде, кроме local и unittest."""

    MOCK_SUB = "00000000-0000-0000-0000-000000000000"

    def __init__(self) -> None:
        pass

    @property
    def sub(self) -> str:
        return self.MOCK_SUB
