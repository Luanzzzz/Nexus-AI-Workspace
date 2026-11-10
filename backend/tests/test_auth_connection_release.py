"""Login não segura a conexão do pool durante o Argon2."""

import asyncio
import time
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies.database import get_db
from app.core.security import hash_password
from app.core.tokens import create_access_token
from app.db.session import SessionLocal, database_url
from app.main import app
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import LoginRequest
from app.services import auth as auth_module
from app.services.auth import AuthService

_PASSWORD = "senha-ficticia-ok"


def _email() -> str:
    return f"pool-{uuid4().hex}@example.com"


async def _create_user(email: str) -> int:
    async with SessionLocal() as session:
        user = await UserRepository(session).create_user(
            name="Ana Silva",
            email=email,
            password_hash=hash_password(_PASSWORD),
        )
        await session.commit()
        return user.id


async def _delete_user(email: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(User).where(User.email == email))
        await session.commit()


@pytest_asyncio.fixture
async def stored_user() -> AsyncIterator[tuple[int, str]]:
    email = _email()
    user_id = await _create_user(email)
    try:
        yield user_id, email
    finally:
        await _delete_user(email)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticate_commits_read_before_password_verify(
    stored_user, monkeypatch
):
    user_id, email = stored_user
    order: list[str] = []

    async with SessionLocal() as session:
        original_commit = session.commit

        async def tracking_commit() -> None:
            order.append("commit")
            await original_commit()

        session.commit = tracking_commit  # type: ignore[method-assign]

        original_verify = auth_module._verify_blocking

        def tracking_verify(password: str, password_hash: str | None) -> bool:
            order.append("verify")
            return original_verify(password, password_hash)

        monkeypatch.setattr(auth_module, "_verify_blocking", tracking_verify)
        service = AuthService(session)
        user = await service.authenticate(LoginRequest(email=email, password=_PASSWORD))
        assert user.id == user_id
        assert order == ["commit", "verify"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_me_is_not_blocked_by_slow_login_hash(stored_user, monkeypatch):
    user_id, email = stored_user
    original_verify = auth_module._verify_blocking

    def slow_verify(password: str, password_hash: str | None) -> bool:
        time.sleep(0.4)
        return original_verify(password, password_hash)

    monkeypatch.setattr(auth_module, "_verify_blocking", slow_verify)
    token = create_access_token(user_id)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:

        async def login() -> httpx.Response:
            return await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": _PASSWORD},
            )

        async def me() -> httpx.Response:
            await asyncio.sleep(0.05)
            return await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )

        login_task = asyncio.create_task(login())
        started = asyncio.get_running_loop().time()
        me_response = await me()
        me_elapsed = asyncio.get_running_loop().time() - started
        login_response = await login_task

    assert me_response.status_code == 200
    assert me_elapsed < 0.25
    assert login_response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_me_with_pool_size_one_not_blocked_by_slow_login(
    stored_user, monkeypatch
):
    user_id, email = stored_user
    original_verify = auth_module._verify_blocking

    def slow_verify(password: str, password_hash: str | None) -> bool:
        time.sleep(0.4)
        return original_verify(password, password_hash)

    monkeypatch.setattr(auth_module, "_verify_blocking", slow_verify)
    tight_engine = create_async_engine(
        database_url,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
        pool_timeout=1,
    )
    TightSession = async_sessionmaker(bind=tight_engine, expire_on_commit=False)

    async def tight_db() -> AsyncIterator[AsyncSession]:
        async with TightSession() as session:
            yield session

    app.dependency_overrides[get_db] = tight_db
    token = create_access_token(user_id)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:

            async def login() -> httpx.Response:
                return await client.post(
                    "/api/v1/auth/login",
                    json={"email": email, "password": _PASSWORD},
                )

            async def me() -> httpx.Response:
                await asyncio.sleep(0.05)
                return await client.get(
                    "/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                )

            login_task = asyncio.create_task(login())
            started = asyncio.get_running_loop().time()
            me_response = await me()
            me_elapsed = asyncio.get_running_loop().time() - started
            login_response = await login_task
    finally:
        app.dependency_overrides.pop(get_db, None)
        await tight_engine.dispose()

    assert me_response.status_code == 200
    assert me_elapsed < 0.25
    assert login_response.status_code == 200
