from pydantic import BaseModel


class JWTSettings(BaseModel):
    MAX_JWT_TOKEN_LENGTH: int = 8192

    ALGORITHM: list[str] = ["RS256"]
    AUDIENCE: list[str] = ["account"]
    LEEWAY: int = 10
    ISSUER: str = ""


class KeycloakSettings(BaseModel):
    """Keycloak общий с монолитом (`mozilla-django-oidc`) и с v2, поэтому
    сервис валидирует JWT сам, одинаково до и после переезда (decisions/008)."""

    BASE_URL: str = ""
    REALM: str = ""
    CLIENT_ID: str = ""
    CACHING_OF_CERTIFICATES_IN_SECONDS: int = 60 * 60
    CERTIFICATE_REQUEST_TIMEOUT_IN_SECONDS: int = 10

    @property
    def url_jwk(self) -> str:
        return f"{self.BASE_URL}/realms/{self.REALM}/protocol/openid-connect/certs"


class AuthSettings(BaseModel):
    jwt: JWTSettings = JWTSettings()
    keycloak: KeycloakSettings = KeycloakSettings()
