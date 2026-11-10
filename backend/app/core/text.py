"""Validação de texto de entrada."""

import unicodedata


def reject_control_characters(value: str) -> str:
    """Rejeita caracteres de controle Unicode (categoria Cc), inclusive NUL."""
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("não pode conter caracteres de controle")
    return value
