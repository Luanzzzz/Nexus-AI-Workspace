"""Autenticação de credenciais no AuthService, sem passar pelo endpoint.

Cada teste usa uma transação externa revertida no fim, em nexus_ai_test.
O authenticate não chama commit(); nada precisa ser apagado depois.
"""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.exceptions import CredentialVerificationError, InvalidCredentialsError
from app.db.session import engine
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import LoginRequest
from app.services import auth as auth_module
from app.services.auth import AuthService

_PASSWORD = "senha-ficticia-ok"


def _email() -> str:
    return f"login-{uuid4().hex}@example.com"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        db_session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield db_session
        finally:
            await db_session.close()
            await transaction.rollback()


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    is_active: bool = True,
    password_hash: str | None = None,
) -> User:
    user = await UserRepository(session).create_user(
        name="Ana Silva",
        email=email,
        password_hash=password_hash or security.hash_password(_PASSWORD),
    )
    user.is_active = is_active
    await session.flush()
    return user


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticate_returns_user_on_success(session: AsyncSession):
    email = _email()
    created = await _create_user(session, email=email)

    user = await AuthService(session).authenticate(
        LoginRequest(email=email, password=_PASSWORD),
    )

    assert user.id == created.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticate_accepts_email_with_different_case(session: AsyncSession):
    email = _email()
    created = await _create_user(session, email=email)

    user = await AuthService(session).authenticate(
        LoginRequest(email=email.upper(), password=_PASSWORD),
    )

    assert user.id == created.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticate_rejects_wrong_password(session: AsyncSession):
    email = _email()
    await _create_user(session, email=email)

    with pytest.raises(InvalidCredentialsError):
        await AuthService(session).authenticate(
            LoginRequest(email=email, password="senha-errada"),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticate_rejects_unknown_email(session: AsyncSession):
    with pytest.raises(InvalidCredentialsError):
        await AuthService(session).authenticate(
            LoginRequest(email=_email(), password=_PASSWORD),
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticate_rejects_inactive_user_after_verifying_password(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    email = _email()
    created = await _create_user(session, email=email, is_active=False)
    calls: list[str] = []
    real_verify = auth_module.verify_password

    def spy(password: str, hashed: str) -> bool:
        calls.append(hashed)
        return real_verify(password, hashed)

    monkeypatch.setattr(auth_module, "verify_password", spy)

    with pytest.raises(InvalidCredentialsError):
        await AuthService(session).authenticate(
            LoginRequest(email=email, password=_PASSWORD),
        )

    assert calls == [created.password_hash]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_all_rejections_share_same_message(session: AsyncSession):
    email = _email()
    await _create_user(session, email=email)
    inactive = _email()
    await _create_user(session, email=inactive, is_active=False)
    service = AuthService(session)
    messages = set()

    for login in (
        LoginRequest(email=email, password="senha-errada"),
        LoginRequest(email=_email(), password=_PASSWORD),
        LoginRequest(email=inactive, password=_PASSWORD),
    ):
        with pytest.raises(InvalidCredentialsError) as info:
            await service.authenticate(login)
        messages.add(str(info.value))

    assert messages == {"Credenciais inválidas."}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_email_verifies_against_dummy_argon2id_hash(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[tuple[str, str]] = []
    real_verify = auth_module.verify_password

    def spy(password: str, hashed: str) -> bool:
        calls.append((password, hashed))
        return real_verify(password, hashed)

    monkeypatch.setattr(auth_module, "verify_password", spy)

    with pytest.raises(InvalidCredentialsError):
        await AuthService(session).authenticate(
            LoginRequest(email=_email(), password=_PASSWORD),
        )

    assert len(calls) == 1
    password, hashed = calls[0]
    assert password == _PASSWORD
    assert hashed.startswith("$argon2id$")
    assert hashed == auth_module._dummy_password_hash()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_corrupted_hash_is_internal_failure_without_leak(
    session: AsyncSession,
):
    email = _email()
    corrupted = "hash-corrompido-ficticio"
    await _create_user(session, email=email, password_hash=corrupted)

    with pytest.raises(CredentialVerificationError) as info:
        await AuthService(session).authenticate(
            LoginRequest(email=email, password=_PASSWORD),
        )

    assert not isinstance(info.value, InvalidCredentialsError)
    assert corrupted not in str(info.value)
    assert _PASSWORD not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True


@pytest.mark.asyncio
async def test_authenticate_does_not_commit():
    class _FakeSession:
        commits = 0

        async def commit(self) -> None:
            self.commits += 1

    fake = _FakeSession()
    service = AuthService(fake)  # type: ignore[arg-type]

    async def lookup(email: str) -> User | None:
        del email
        return None

    service.users.get_by_email = lookup  # type: ignore[method-assign]

    with pytest.raises(InvalidCredentialsError):
        await service.authenticate(LoginRequest(email=_email(), password=_PASSWORD))
    assert fake.commits == 0
