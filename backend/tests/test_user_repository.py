"""Consultas e persistência de UserRepository.

As linhas são só flush. O rollback desfaz o que o teste inseriu,
no mesmo padrão da Fase 1.5. O repositório não dá commit.
"""

from uuid import uuid4

import pytest

from app.db.session import SessionLocal
from app.models.user import User
from app.repositories.user import UserRepository

_PASSWORD_HASH = "hash-ja-pronto"


def _email() -> str:
    return f"repo-{uuid4().hex}@example.com"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_email_returns_existing_user_and_reuses_session():
    email = _email()

    async with SessionLocal() as session:
        session.add(
            User(email=email, name="Pessoa", password_hash=_PASSWORD_HASH),
        )
        await session.flush()

        repository = UserRepository(session)
        # A sessão do construtor é a mesma nas duas consultas.
        assert repository.session is session
        found = await repository.get_by_email(email)
        missing = await repository.get_by_email(f"ausente-{uuid4().hex}@example.com")
        again = await repository.get_by_email(email)

        assert repository.session is session
        assert isinstance(found, User)
        assert found.email == email
        assert again is found
        assert missing is None
        # A consulta não confirma a transação que o flush abriu.
        assert session.in_transaction()

        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_email_returns_none_when_email_does_not_exist():
    async with SessionLocal() as session:
        repository = UserRepository(session)
        found = await repository.get_by_email(f"ninguem-{uuid4().hex}@example.com")

        assert found is None
        assert session.in_transaction()
        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_email_does_not_commit_or_lowercase():
    email = _email()
    mixed_case = email.upper()

    async with SessionLocal() as session:
        session.add(
            User(email=email, name="Pessoa", password_hash=_PASSWORD_HASH),
        )
        await session.flush()
        repository = UserRepository(session)

        # A caixa diferente não é a mesma linha: o repositório não canonicaliza.
        assert await repository.get_by_email(mixed_case) is None
        assert await repository.get_by_email(email) is not None
        await session.rollback()

    async with SessionLocal() as session:
        # Se a consulta tivesse dado commit, o rollback acima não apagaria a linha.
        assert await UserRepository(session).get_by_email(email) is None
        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_user_flushes_id_without_commit():
    email = _email()

    async with SessionLocal() as session:
        repository = UserRepository(session)
        user = await repository.create_user(
            name="Pessoa",
            email=email,
            password_hash=_PASSWORD_HASH,
        )

        assert user.id is not None
        assert user.email == email
        assert user.password_hash == _PASSWORD_HASH
        assert not user.password_hash.startswith("$argon2")
        # O cliente não envia is_active; o default do model é True.
        assert user.is_active is True
        assert session.in_transaction()
        await session.rollback()

    async with SessionLocal() as session:
        assert await UserRepository(session).get_by_email(email) is None
        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_id_returns_user_or_none_without_commit():
    async with SessionLocal() as session:
        repository = UserRepository(session)
        user = await repository.create_user(
            name="Pessoa", email=_email(), password_hash=_PASSWORD_HASH
        )
        user.is_active = False
        await session.flush()

        found = await repository.get_by_id(user.id)
        # Inativo também é devolvido: a regra de acesso não pertence ao repositório.
        assert found is user
        assert await repository.get_by_id(2**31 - 1) is None
        assert session.in_transaction()
        user_id = user.id
        await session.rollback()

    async with SessionLocal() as session:
        assert await UserRepository(session).get_by_id(user_id) is None
        await session.rollback()
