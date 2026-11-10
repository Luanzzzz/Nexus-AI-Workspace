"""Middleware de request id e de erros internos sem relançar a exceção."""

from __future__ import annotations

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api.exception_handlers import internal_error_response
from app.core.logging import request_id_ctx

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def sanitize_request_id(raw: str | None) -> str:
    if raw is not None and _REQUEST_ID_RE.fullmatch(raw):
        return raw
    return uuid.uuid4().hex


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = sanitize_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = request_id_ctx.set(request_id)
        try:
            try:
                response = await call_next(request)
            except Exception as exc:
                response = internal_error_response(request, exc)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            request_id_ctx.reset(token)
