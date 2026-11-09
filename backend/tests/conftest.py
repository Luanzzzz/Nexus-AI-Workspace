"""Configuração compartilhada do pytest."""

import os
import secrets

import pytest

# Segredo forte e efêmero, definido antes de qualquer import de app.core.config
# (que instancia Settings no import). Variável de ambiente tem prioridade sobre o .env.
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(32)

from app.db.session import database_url  # noqa: E402

TEST_DATABASE_NAME = "nexus_ai_test"


def _protection_failure_message(configured_database: str | None) -> str:
    return (
        "Proteção do banco de testes: testes de integração só podem acessar "
        f"{TEST_DATABASE_NAME}. Banco configurado: {configured_database!r}. "
        "Defina POSTGRES_DB=nexus_ai_test antes de executar o pytest."
    )


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Interrompe o setup antes das fixtures se o banco não for o de teste."""
    if item.get_closest_marker("integration") is None:
        return

    configured_database = database_url.database
    if configured_database == TEST_DATABASE_NAME:
        return

    pytest.fail(
        _protection_failure_message(configured_database),
        pytrace=False,
    )
