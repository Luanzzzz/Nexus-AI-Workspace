"""Emissão e validação de access tokens JWT (HS256, PyJWT)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings

ACCESS_TOKEN_TYPE = "access"
REQUIRED_CLAIMS = ["sub", "iat", "exp", "iss", "aud", "token_type"]


class InvalidTokenError(Exception):
    """Token ausente de requisitos, expirado, adulterado ou malformado.

    A mensagem é genérica de propósito: não revela o motivo da falha.
    """

    def __init__(self) -> None:
        super().__init__("Token inválido")


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: int
    issued_at: datetime
    expires_at: datetime


def create_access_token(user_id: int, *, now: datetime | None = None) -> str:
    """Emite um access token assinado; `exp` é calculado pelo backend em UTC."""
    issued_at = now if now is not None else datetime.now(UTC)
    if issued_at.tzinfo is None:
        raise ValueError("now deve ter timezone")
    issued_at = issued_at.astimezone(UTC)
    expires_at = issued_at + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "token_type": ACCESS_TOKEN_TYPE,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> AccessTokenClaims:
    """Valida assinatura, claims e tipo; qualquer falha vira InvalidTokenError."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": REQUIRED_CLAIMS},
        )
    except jwt.PyJWTError:
        raise InvalidTokenError() from None

    if payload.get("token_type") != ACCESS_TOKEN_TYPE:
        raise InvalidTokenError()

    subject = payload["sub"]
    if not isinstance(subject, str) or not subject.isascii() or not subject.isdigit():
        raise InvalidTokenError()
    user_id = int(subject)
    if user_id <= 0:
        raise InvalidTokenError()

    return AccessTokenClaims(
        user_id=user_id,
        issued_at=datetime.fromtimestamp(payload["iat"], UTC),
        expires_at=datetime.fromtimestamp(payload["exp"], UTC),
    )
