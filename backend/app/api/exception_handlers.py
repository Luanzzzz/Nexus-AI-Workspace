"""Erros HTTP que não podem repetir dados sensíveis do pedido."""

from collections.abc import Mapping, Sequence

from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Campos que o 422 público não pode devolver, nem dentro de input aninhado.
_SENSITIVE_FIELDS = frozenset({"password", "password_hash"})


def _location_is_sensitive(loc: object) -> bool:
    if not isinstance(loc, (list, tuple)):
        return False
    return any(isinstance(part, str) and part in _SENSITIVE_FIELDS for part in loc)


def _redact(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _redact(item)
            for key, item in value.items()
            if str(key) not in _SENSITIVE_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def sanitize_validation_errors(errors: Sequence[object]) -> list[dict[str, object]]:
    # loc, type e msg ficam. input de senha ou hash sai por completo.
    public: list[dict[str, object]] = []
    for error in errors:
        if not isinstance(error, Mapping):
            continue
        loc = error.get("loc", ())
        item: dict[str, object] = {
            "loc": list(loc) if isinstance(loc, (list, tuple)) else loc,
            "type": error.get("type"),
            "msg": error.get("msg"),
        }
        ctx = error.get("ctx")
        if isinstance(ctx, Mapping):
            item["ctx"] = _redact(dict(ctx))
        if "input" in error and not _location_is_sensitive(loc):
            item["input"] = _redact(error.get("input"))
        public.append(item)
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
