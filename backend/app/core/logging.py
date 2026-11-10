"""Logging da API: rastreio por request id, sem dados sensíveis."""

from __future__ import annotations

import logging
import re
import traceback
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_REDACTED = "[redacted]"

_PATTERNS = (
    re.compile(r"\$argon2(?:id|i|d)\$[^\s'\"\\,\]]+", re.IGNORECASE),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    re.compile(r"\[parameters:[^\]]*\]", re.IGNORECASE),
    re.compile(
        r"password_hash['\"]?\s*[:=]\s*['\"][^'\"]+['\"]",
        re.IGNORECASE,
    ),
    re.compile(r"postgres(?:ql)?(?:\+\w+)?://[^\s'\"\\]+", re.IGNORECASE),
    re.compile(r"postgresql://[^\s'\"\\]+", re.IGNORECASE),
    re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    ),
    re.compile(
        r"\b(?:password|passwd|secret|jwt_secret_key)\b\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
)


def redact_text(text: str) -> str:
    redacted = text
    for pattern in _PATTERNS:
        redacted = pattern.sub(_REDACTED, redacted)
    return redacted


def _frames_without_source(exc: BaseException) -> str:
    lines = [f"type={type(exc).__name__}"]
    for frame in traceback.extract_tb(exc.__traceback__):
        lines.append(f"  {frame.filename}:{frame.lineno} in {frame.name}")
    return "\n".join(lines)


def exception_log_text(exc: BaseException, *, environment: str) -> str:
    """Texto do 500 interno.

    Fora de development: só tipos e frames (arquivo, linha, função), sem
    mensagem, sem locals e sem texto de __cause__/__context__. Em
    development o traceback completo ainda passa por redact_text.
    """
    if environment == "development":
        return redact_text("".join(traceback.format_exception(exc)))
    chunks: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chunks.append(_frames_without_source(current))
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__context__ is not None and not current.__suppress_context__:
            current = current.__context__
        else:
            break
    return redact_text("\n".join(chunks))


class RedactingFilter(logging.Filter):
    """Remove hash, JWT, email, senha e parâmetros SQL das mensagens."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        record.msg = redact_text(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: redact_text(value) if isinstance(value, str) else value
                    for key, value in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact_text(arg) if isinstance(arg, str) else arg
                    for arg in record.args
                )
        return True


def configure_logging() -> None:
    redactor = RedactingFilter()
    root = logging.getLogger()
    if not any(isinstance(item, RedactingFilter) for item in root.filters):
        root.addFilter(redactor)
    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "sqlalchemy.engine",
        "sqlalchemy.engine.Engine",
    ):
        logger = logging.getLogger(name)
        if not any(isinstance(item, RedactingFilter) for item in logger.filters):
            logger.addFilter(redactor)
