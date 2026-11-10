"""Rate limit de login e cadastro."""

from typing import Any

from fastapi import HTTPException, Request, status

from app.api.exception_handlers import RATE_LIMITED_DETAIL
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.request_context import client_ip


def _reject(retry_after: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=RATE_LIMITED_DETAIL,
        headers={
            "Retry-After": str(retry_after),
            "Cache-Control": "no-store",
        },
    )


def _check(key: str, limit: int) -> None:
    allowed, retry_after = limiter.hit(
        key,
        limit,
        settings.auth_rate_limit_window_seconds,
    )
    if not allowed:
        _reject(retry_after)


async def _json_email(request: Request) -> str | None:
    try:
        payload: Any = await request.json()
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    email = payload.get("email")
    if not isinstance(email, str):
        return None
    return email.strip().lower() or None


async def login_rate_limit(request: Request) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    ip = client_ip(request)
    _check(f"login:ip:{ip}", settings.auth_login_per_ip_limit)
    email = await _json_email(request)
    if email is not None:
        _check(f"login:email:{email}", settings.auth_login_per_email_limit)


async def register_rate_limit(request: Request) -> None:
    if not settings.auth_rate_limit_enabled:
        return
    ip = client_ip(request)
    _check(f"register:ip:{ip}", settings.auth_register_per_ip_limit)
