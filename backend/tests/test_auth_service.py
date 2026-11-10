"""Caso de uso de cadastro, sem passar pelo endpoint.

O serviço chama commit(). Nos testes de uma sessão, um SAVEPOINT na
transação externa absorve esse commit. Concorrência e a corrida de
unicidade usam SessionLocal de verdade, cada tarefa com a própria
sessão, e apagam a linha no final.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateEmailError
from app.core.security import verify_password
from app.db.session import SessionLocal, engine
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import UserRegister
from app.services import auth as auth_module
from app.services.auth import AuthService

_PASSWORD = "senha-ficticia-ok"


def _email() -> str:
    return f"svc-{uuid4().hex}@example.com"


@asynccontextmanager
async def _savepoint_session() -> AsyncIterator[AsyncSession]:
    # Não é uma factory nova do app: a conexão sai do engine que já existe.
    # create_savepoint faz o commit() do serviço liberar o SAVEPOINT.
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


async def _delete_user(email: str) -> None:
    async with SessionLocal() as session:
        user = await UserRepository(session).get_by_email(email)
        if user is not None:
            await session.delete(user)
            await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_stores_argon2id_hash_and_rejects_same_email():
    email = _email()

    async with _savepoint_session() as session:
        service = AuthService(session)
        user = await service.register(
            UserRegister(
                name="Ana Silva",
                email=email.upper(),
                password=_PASSWORD,
            ),
        )

        assert user.id is not None
        assert user.email == email
        assert user.is_active is True
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(_PASSWORD, user.password_hash)

        hash_calls = 0
        original_hash = auth_module.hash_password

        def counting_hash(password: str) -> str:
            nonlocal hash_calls
            hash_calls += 1
            return original_hash(password)

        auth_module.hash_password = counting_hash
        try:
            with pytest.raises(DuplicateEmailError):
                await service.register(
                    UserRegister(
                        name="Ana Silva",
                        email=email,
                        password=_PASSWORD,
                    ),
                )
        finally:
            auth_module.hash_password = original_hash
        assert hash_calls == 1

    async with SessionLocal() as session:
        # O rollback externo desfaz o commit do SAVEPOINT.
        assert await UserRepository(session).get_by_email(email) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_rolls_back_when_persistence_fails():
    email = _email()

    try:
        async with SessionLocal() as session:
            service = AuthService(session)
            create_user = service.users.create_user

            async def fail_after_flush(
                *,
                name: str,
                email: str,
                password_hash: str,
            ) -> User:
                await create_user(
                    name=name,
                    email=email,
                    password_hash=password_hash,
                )
                raise RuntimeError("falha de persistência")

            service.users.create_user = fail_after_flush
            with pytest.raises(RuntimeError, match="falha de persistência"):
                await service.register(
                    UserRegister(name="Ana Silva", email=email, password=_PASSWORD),
                )
            # Sem o rollback do serviço, este commit gravaria o flush pela metade.
            await session.commit()

        async with SessionLocal() as session:
            assert await UserRepository(session).get_by_email(email) is None
    finally:
        await _delete_user(email)


@pytest.mark.asyncio
async def test_register_rolls_back_when_initial_lookup_fails():
    class _FakeSession:
        rollbacks = 0

        async def rollback(self) -> None:
            self.rollbacks += 1

    session = _FakeSession()
    service = AuthService(session)  # type: ignore[arg-type]

    async def failing_lookup(email: str) -> User | None:
        del email
        raise RuntimeError("consulta falhou")

    service.users.get_by_email = failing_lookup  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="consulta falhou"):
        await service.register(
            UserRegister(name="Ana Silva", email=_email(), password=_PASSWORD)
        )
    assert session.rollbacks == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_does_not_hide_unrelated_integrity_error():
    email = _email()

    try:
        async with SessionLocal() as session:
            service = AuthService(session)

            async def other_constraint(
                *,
                name: str,
                email: str,
                password_hash: str,
            ) -> User:
                del name, email, password_hash
                raise IntegrityError(
                    "INSERT INTO users", {}, Exception("outra restrição")
                )

            service.users.create_user = other_constraint
            with pytest.raises(IntegrityError):
                await service.register(
                    UserRegister(name="Ana Silva", email=email, password=_PASSWORD),
                )
            await session.commit()

        async with SessionLocal() as session:
            assert await UserRepository(session).get_by_email(email) is None
    finally:
        await _delete_user(email)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_register_translates_unique_race_to_duplicate_email():
    email = _email()

    async with SessionLocal() as session:
        await UserRepository(session).create_user(
            name="Ana Silva",
            email=email,
            password_hash="hash-ja-pronto",
        )
        await session.commit()

    try:
        async with SessionLocal() as session:
            service = AuthService(session)

            async def miss(_email: str) -> User | None:
                return None

            # A consulta não vê a linha; o UNIQUE do banco pega a corrida.
            service.users.get_by_email = miss
            with pytest.raises(DuplicateEmailError):
                await service.register(
                    UserRegister(
                        name="Outra Pessoa",
                        email=email,
                        password=_PASSWORD,
                    ),
                )
    finally:
        await _delete_user(email)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_registers_confirm_at_most_one_user():
    email = _email()
    payload = UserRegister(name="Ana Silva", email=email, password=_PASSWORD)
    # As duas tarefas só entram no cadastro juntas, cada uma na sua sessão.
    barrier = asyncio.Barrier(2)

    async def attempt() -> str:
        async with SessionLocal() as session:
            service = AuthService(session)
            await barrier.wait()
            try:
                await service.register(payload)
            except DuplicateEmailError:
                return "duplicate"
            return "created"

    try:
        results = await asyncio.gather(attempt(), attempt())
        assert sorted(results) == ["created", "duplicate"]

        async with SessionLocal() as session:
            found = await UserRepository(session).get_by_email(email)
            assert found is not None
            assert found.password_hash.startswith("$argon2id$")
    finally:
        await _delete_user(email)
