"""Guarda ASGI do upload: autentica o JWT e limita o corpo ANTES de lê-lo.

O Starlette grava o multipart em arquivo temporário (acima de 1 MiB) antes de
qualquer dependency do FastAPI rodar. Este middleware (só API pública do ASGI)
atua apenas em `POST /api/v1/workspaces/{id}/documents`, nesta ordem e antes de
consumir qualquer byte do corpo:

1. Content-Length declarado acima de MAX_UPLOAD_BYTES + folga -> 413.
2. Authorization Bearer validado SEM banco (mesma `decode_access_token` do
   get_current_user: assinatura, algoritmo, exp, claims) -> 401 idêntico ao de
   get_current_user. Nada é lido nem gravado em disco.
3. Hook de rate limit por usuário (`enforce_upload_rate_limit`), ainda sem corpo.
4. O `receive` é envolvido e conta os bytes: ao passar do teto a leitura é
   abortada e a resposta é 413 (a resposta do app, se houver, é descartada).

Usuário ativo, membership e papel continuam sendo checados no banco pelas
dependencies depois deste guarda. Um usuário autenticado sem membership ainda
pode fazer o servidor gravar até ~10 MiB por requisição até essa checagem.
"""

import re

from fastapi.security.utils import get_authorization_scheme_param
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.dependencies.auth import NOT_AUTHENTICATED_DETAIL
from app.api.exception_handlers import document_too_large_response
from app.core.tokens import AccessTokenClaims, InvalidTokenError, decode_access_token
from app.services.document_validation import MAX_UPLOAD_BYTES

# Folga para boundaries e cabeçalhos do multipart sobre o limite do arquivo.
MULTIPART_OVERHEAD = 64 * 1024
BODY_LIMIT = MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD

# `[^/]+` (e não só dígitos): um id malformado também não pode escapar do guarda,
# pois o FastAPI lê o corpo antes de validar o path.
_UPLOAD_PATH = re.compile(r"^/api/v1/workspaces/[^/]+/documents$")


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


async def enforce_upload_rate_limit(user_id: int, scope: Scope) -> Response | None:
    """Gancho do limite por usuário: roda após o JWT e antes de ler o corpo.

    Devolva uma Response (ex.: 429) para encerrar a requisição; None deixa
    passar. Ainda não implementado.
    """
    _ = (user_id, scope)
    return None


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
            or not _UPLOAD_PATH.fullmatch(scope["path"])
        ):
            await self.app(scope, receive, send)
            return

        early: Response | None = None
        if _declared_length_exceeds(scope):
            early = document_too_large_response()
        else:
            claims = authenticate_bearer(scope)
            if claims is None:
                early = _unauthorized_response()
            else:
                scope.setdefault("state", {})["upload_user_id"] = claims.user_id
                early = await enforce_upload_rate_limit(claims.user_id, scope)
        if early is not None:
            await early(scope, receive, send)
            return

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
