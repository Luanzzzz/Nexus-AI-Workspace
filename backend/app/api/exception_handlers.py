"""Erros HTTP que não podem repetir dados sensíveis do pedido."""

import logging
from collections.abc import Mapping, Sequence

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS_DETAIL = "Credenciais inválidas."
INTERNAL_ERROR_DETAIL = "Erro interno do servidor."


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
        headers={"WWW-Authenticate": "Bearer"},
    )


async def internal_error_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    # Só o nome da classe vai ao log: sem email, senha, hash, token ou SQL.
    _ = request
    logger.error("Erro interno na requisição: %s", type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": INTERNAL_ERROR_DETAIL},
    )
