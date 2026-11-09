"""Emissão e validação de access tokens JWT (HS256, PyJWT)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings

ACCESS_TOKEN_TYPE = "access"
REQUIRED_CLAIMS = ["sub", "iat", "exp", "iss", "aud", "token_type"]

# users.id é Integer (INT4 do PostgreSQL): o maior id possível é 2**31 - 1.
MAX_USER_ID = 2**31 - 1
MAX_SUBJECT_LENGTH = len(str(MAX_USER_ID))
# Maior timestamp que datetime representa (9999-12-31T23:59:59Z).
MAX_TIMESTAMP = 253_402_300_799


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
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise ValueError("user_id deve ser um inteiro")
    if not 0 < user_id <= MAX_USER_ID:
        raise ValueError("user_id deve ser um inteiro positivo válido")
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

    user_id = _parse_user_id(payload["sub"])
    issued_at, expires_at = _parse_timestamps(payload["iat"], payload["exp"])
    return AccessTokenClaims(
        user_id=user_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _parse_user_id(subject: object) -> int:
    """`sub` deve ser str só com dígitos ASCII, sem sinal, no limite de users.id."""
    if (
        not isinstance(subject, str)
        or not 0 < len(subject) <= MAX_SUBJECT_LENGTH
        or not subject.isascii()
        or not subject.isdigit()
    ):
        raise InvalidTokenError()
    user_id = int(subject)
    if not 0 < user_id <= MAX_USER_ID:
        raise InvalidTokenError()
    return user_id


def _parse_timestamps(iat: object, exp: object) -> tuple[datetime, datetime]:
    """`iat`/`exp` devem ser int (não bool/float/str), no intervalo suportado.

    O PyJWT aceita strings numéricas, floats e valores gigantes nessas claims;
    `create_access_token` só emite int, então só int é aceito aqui.
    """
    issued, expires = _checked_timestamp(iat), _checked_timestamp(exp)
    if expires <= issued:
        raise InvalidTokenError()
    try:
        return datetime.fromtimestamp(issued, UTC), datetime.fromtimestamp(expires, UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        raise InvalidTokenError() from None


def _checked_timestamp(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidTokenError()
    if not 0 < value <= MAX_TIMESTAMP:
        raise InvalidTokenError()
    return value
