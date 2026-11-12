"""Erros HTTP que não podem repetir dados sensíveis do pedido."""

import logging
from collections.abc import Mapping, Sequence

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import exception_log_text, request_id_ctx

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS_DETAIL = "Credenciais inválidas."
INTERNAL_ERROR_DETAIL = "Erro interno do servidor."
RATE_LIMITED_DETAIL = "Muitas tentativas. Tente novamente mais tarde."
REGISTER_PROCESSED_DETAIL = "Cadastro processado."
DUPLICATE_SLUG_DETAIL = "Slug indisponível."
WORKSPACE_NOT_FOUND_DETAIL = "Workspace não encontrado."
FORBIDDEN_DETAIL = "Permissão insuficiente."


def sanitize_validation_errors(errors: Sequence[object]) -> list[dict[str, object]]:
    # Lista de permissão: só loc, type e msg saem. input e ctx podem conter
    # o corpo bruto (string, JSON ou estrutura aninhada) com credenciais.
    public: list[dict[str, object]] = []
    for error in errors:
        if not isinstance(error, Mapping):
            continue
        loc = error.get("loc", ())
        public.append(
            {
                "loc": list(loc) if isinstance(loc, (list, tuple)) else loc,
                "type": error.get("type"),
                "msg": error.get("msg"),
            }
        )
    return public


async def request_validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    # O pedido entra na assinatura do FastAPI e fica fora do log:
    # exc.errors() colocaria a senha rejeitada em input.
    _ = request
    detail = jsonable_encoder(sanitize_validation_errors(exc.errors()))
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": detail},
    )


async def invalid_credentials_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    # Mesma resposta para inexistente, senha errada e inativo.
    _ = (request, exc)
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": INVALID_CREDENTIALS_DETAIL},
        headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
    )


def internal_error_response(request: Request, exc: Exception) -> JSONResponse:
    _ = request
    request_id = request_id_ctx.get("-")
    logger.error(
        "Erro interno request_id=%s type=%s\n%s",
        request_id,
        type(exc).__name__,
        exception_log_text(exc, environment=settings.environment),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": INTERNAL_ERROR_DETAIL},
        headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
    )


async def internal_error_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return internal_error_response(request, exc)


async def duplicate_slug_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    # Mensagem genérica: não ecoa o slug enviado.
    _ = (request, exc)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": DUPLICATE_SLUG_DETAIL},
    )


UNSUPPORTED_DOCUMENT_DETAIL = "Tipo de arquivo não suportado."
INVALID_DOCUMENT_DETAIL = "Arquivo inválido."
DOCUMENT_TOO_LARGE_DETAIL = "Arquivo excede o tamanho máximo de 10 MiB."


async def unsupported_document_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    _ = (request, exc)
    return JSONResponse(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        content={"detail": UNSUPPORTED_DOCUMENT_DETAIL},
    )


async def invalid_document_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    _ = (request, exc)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": INVALID_DOCUMENT_DETAIL},
    )


def document_too_large_response() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        content={"detail": DOCUMENT_TOO_LARGE_DETAIL},
    )


async def document_too_large_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    _ = (request, exc)
    return document_too_large_response()


async def workspace_not_found_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    _ = (request, exc)
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": WORKSPACE_NOT_FOUND_DETAIL},
    )


async def permission_denied_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    _ = (request, exc)
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": FORBIDDEN_DETAIL},
    )
