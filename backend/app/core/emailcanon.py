"""Canonicalização de email alinhada ao cadastro (EmailStr + lower)."""

from pydantic import EmailStr, TypeAdapter, ValidationError

_EMAIL_ADAPTER = TypeAdapter(EmailStr)


def canonicalize_email(value: str) -> str:
    """Mesma normalização do EmailStr de login/cadastro, em minúsculas.

    O EmailStr do Pydantic aceita addr-spec e o formato RFC 5322
    ``Nome <user@host>`` e devolve só o endereço. ``email_validator``
    isolado recusa o segundo formato; a chave de rate limit usa esta
    função para não divergir do schema.
    """
    normalized = _EMAIL_ADAPTER.validate_python(value)
    return str(normalized).lower()


def email_rate_limit_key(value: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return canonicalize_email(stripped)
    except ValidationError:
        return stripped.lower() or None
