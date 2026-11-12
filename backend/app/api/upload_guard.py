"""Guarda ASGI do upload: autentica o JWT e limita o corpo ANTES de lê-lo.

O Starlette grava o multipart em arquivo temporário (acima de 1 MiB) antes de
qualquer dependency do FastAPI rodar. Este middleware (só API pública do ASGI)
atua apenas em `POST /api/v1/workspaces/{id}/documents`, nesta ordem e antes de
consumir qualquer byte do corpo:

1. Content-Length declarado acima de MAX_UPLOAD_BYTES + folga -> 413.
2. Authorization Bearer validado SEM banco (mesma `decode_access_token` do
   get_current_user: assinatura, algoritmo, exp, claims) -> 401 idêntico ao de
   get_current_user. Nada é lido nem gravado em disco.
3. Rate limit por usuário (`enforce_upload_rate_limit`, janela deslizante), ainda
   sem corpo -> 429 + Retry-After.
4. Limite de uploads simultâneos por usuário (vaga adquirida aqui e devolvida
   num `finally` quando o app termina, inclusive em erro, desconexão e
   cancelamento) -> 429 + Retry-After: 1, ainda sem corpo.
5. O `receive` é envolvido e conta os bytes: ao passar do teto a leitura é
   abortada e a resposta é 413 (a resposta do app, se houver, é descartada).

Os limites de 3 e 4 são em memória e POR PROCESSO (ADR 0009): com vários workers
o teto efetivo é multiplicado; produção multi-worker precisa de store
compartilhado ou limite no proxy.

Usuário ativo, membership e papel continuam sendo checados no banco pelas
dependencies depois deste guarda. Um usuário autenticado sem membership ainda
pode fazer o servidor gravar até ~10 MiB por requisição até essa checagem.
"""

import re

from fastapi.security.utils import get_authorization_scheme_param
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.dependencies.auth import NOT_AUTHENTICATED_DETAIL
from app.api.exception_handlers import (
    document_too_large_response,
    rate_limited_response,
)
from app.core.config import settings
from app.core.rate_limit import upload_concurrency, upload_limiter
from app.core.tokens import AccessTokenClaims, InvalidTokenError, decode_access_token
from app.services.document_validation import MAX_UPLOAD_BYTES

# Folga para boundaries e cabeçalhos do multipart sobre o limite do arquivo.
MULTIPART_OVERHEAD = 64 * 1024
BODY_LIMIT = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD

# `[^/]+` (e não só dígitos): um id malformado também não pode escapar do guarda,
# pois o FastAPI lê o corpo antes de validar o path.
UPLOAD_RATE_WINDOW_SECONDS = 60

# Prefixo opcional (`root_path` do uvicorn --root-path, Mount, proxy): o path de
# rota é o que sobra depois dele. Fail-safe: qualquer prefixo antes do padrão
# ainda aplica o guarda, pois o app pode alcançar a rota (ver `_route_path`).
_UPLOAD_PATH = re.compile(r"^(?:/.*)?/api/v1/workspaces/[^/]+/documents$", re.DOTALL)


def _route_path(scope: Scope) -> str:
    """Path usado no roteamento: `scope["path"]` sem o `root_path`.

    O Starlette tem duas convenções: path COM o root_path (ASGI >= 2.4, uvicorn
    --root-path, Mount) e path SEM ele. Remove o prefixo só se presente e em
    fronteira de segmento; os dois casos resultam no mesmo path de rota.
    """
    path: str = scope["path"]
    root_path: str = scope.get("root_path", "").rstrip("/")
    if root_path and (path == root_path or path.startswith(root_path + "/")):
        return path[len(root_path) :] or "/"
    return path


class _BodyTooLargeError(Exception):
    """Corpo acumulado acima do teto; interrompe a leitura do multipart."""


def _unauthorized_response() -> JSONResponse:
    # Mesmo status, corpo e cabeçalho de get_current_user para credencial ruim.
    return JSONResponse(
        status_code=401,
        content={"detail": NOT_AUTHENTICATED_DETAIL},
        headers={"WWW-Authenticate": "Bearer"},
    )


def authenticate_bearer(scope: Scope) -> AccessTokenClaims | None:
    """Valida o Bearer JWT do cabeçalho sem tocar no banco; None se inválido."""
    raw = b""
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            raw = value
            break
    scheme, credentials = get_authorization_scheme_param(raw.decode("latin-1"))
    # Mesmas regras do HTTPBearer usado por get_current_user.
    if not scheme or not credentials or scheme.lower() != "bearer":
        return None
    try:
        return decode_access_token(credentials)
    except InvalidTokenError:
        return None


async def enforce_upload_rate_limit(user_id: int) -> Response | None:
    """Rate limit por usuário: roda após o JWT e antes de ler o corpo.

    Devolve 429 (Retry-After) se a janela estourou; None deixa passar.
    """
    if not settings.upload_limits_enabled:
        return None
    allowed, retry_after = upload_limiter.hit(
        f"upload:user:{user_id}",
        settings.upload_rate_limit_per_minute,
        UPLOAD_RATE_WINDOW_SECONDS,
    )
    if allowed:
        return None
    return rate_limited_response(retry_after)


def _declared_length_exceeds(scope: Scope) -> bool:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            text = value.decode("latin-1")
            return text.isascii() and text.isdigit() and int(text) > BODY_LIMIT
    return False


class UploadGuardMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not _UPLOAD_PATH.fullmatch(_route_path(scope))
        ):
            await self.app(scope, receive, send)
            return

        early: Response | None = None
        slot_key: str | None = None
        if _declared_length_exceeds(scope):
            early = document_too_large_response()
        else:
            claims = authenticate_bearer(scope)
            if claims is None:
                early = _unauthorized_response()
            else:
                early = await enforce_upload_rate_limit(claims.user_id)
                if early is None and settings.upload_limits_enabled:
                    key = f"upload:user:{claims.user_id}"
                    if upload_concurrency.acquire(
                        key, settings.upload_max_concurrent_per_user
                    ):
                        slot_key = key
                    else:
                        early = rate_limited_response(1)
        if early is not None:
            await early(scope, receive, send)
            return

        try:
            await self._run_bounded(scope, receive, send)
        finally:
            # Exatamente uma vez por vaga adquirida (sucesso, erro, desconexão
            # ou cancelamento); early-return acima nunca adquiriu vaga.
            if slot_key is not None:
                upload_concurrency.release(slot_key)

    async def _run_bounded(self, scope: Scope, receive: Receive, send: Send) -> None:
        received = 0
        exceeded = False
        started = False

        async def bounded_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > BODY_LIMIT:
                    exceeded = True
                    raise _BodyTooLargeError
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if exceeded and not started:
                # O FastAPI transforma o erro de leitura em 400: descarta e
                # deixa só o 413 abaixo.
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, guarded_send)
        except _BodyTooLargeError:
            pass
        except Exception:
            if not exceeded or started:
                raise
        if exceeded and not started:
            await document_too_large_response()(scope, receive, send)
