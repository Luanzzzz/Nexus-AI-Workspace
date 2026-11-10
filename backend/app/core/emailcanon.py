"""Canonicalização de email alinhada ao cadastro (EmailStr + lower)."""

from email_validator import EmailNotValidError, validate_email


def canonicalize_email(value: str) -> str:
    """Normaliza como o schema de cadastro/login (IDNA/NFC + minúsculas)."""
    result = validate_email(value, check_deliverability=False)
    return str(result.normalized).lower()


def email_rate_limit_key(value: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return canonicalize_email(stripped)
    except EmailNotValidError:
        return stripped.lower() or None
