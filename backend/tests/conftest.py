"""Fixtures compartilhadas do pytest."""

import pytest

from app.db.session import database_url

TEST_DATABASE_NAME = "nexus_ai_test"


def _protection_failure_message(configured_database: str | None) -> str:
    return (
        "Proteção do banco de testes: testes de integração só podem acessar "
        f"{TEST_DATABASE_NAME}. Banco configurado: {configured_database!r}. "
        "Defina POSTGRES_DB=nexus_ai_test antes de executar o pytest."
    )


@pytest.fixture(autouse=True)
def protect_test_database(request: pytest.FixtureRequest) -> None:
    """Falha o teste de integração antes de qualquer SQL se o banco não for o de teste.

    O pytest classifica pytest.fail() no setup como ERROR. A falha é aplicada na
    chamada do teste para aparecer como FAILED, ainda sem executar o corpo original.
    """
    if request.node.get_closest_marker("integration") is None:
        return

    configured_database = database_url.database
    if configured_database == TEST_DATABASE_NAME:
        return

    message = _protection_failure_message(configured_database)

    def blocked_test(*args: object, **kwargs: object) -> None:
        pytest.fail(message, pytrace=False)

    request.node.obj = blocked_test
