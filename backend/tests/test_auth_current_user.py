"""GET /api/v1/auth/me: usuário atual por JWT Bearer, conferido no banco.

Cada teste roda numa transação externa com SAVEPOINT, revertida no fim, em
nexus_ai_test. get_db é trocado por essa sessão; o cliente é assíncrono e as
requisições são sequenciais, então a AsyncSession nunca é usada por duas tarefas.
"""

import logging
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.dependencies.database import get_db
from app.core.config import settings
from app.core.tokens import create_access_token
from app.db.session import database_url, engine
from app.main import app
from app.models.user import User
from app.repositories.user import UserRepository

_URL = "/api/v1/auth/me"
_PASSWORD_HASH = "$argon2id$hash-ficticio-que-nao-pode-vazar"
_PUBLIC_FIELDS = {"id", "name", "email", "is_active", "created_at", "updated_at"}
_UNAUTHORIZED = {"detail": "Não autenticado."}


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


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            yield http_client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def sql_log() -> Iterator[list[str]]:
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)


async def _create_user(session: AsyncSession, *, name: str = "Ana Silva") -> User:
    user = await UserRepository(session).create_user(
        name=name,
        email=f"me-{uuid4().hex}@example.com",
        password_hash=_PASSWORD_HASH,
    )
    return user


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assert_generic_401(response: httpx.Response) -> None:
    assert response.status_code == 401
    assert response.json() == _UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"


def _assert_no_leaks(text: str, *extra: str) -> None:
    for forbidden in (
        _PASSWORD_HASH,
        "password_hash",
        "$argon2",
        settings.jwt_secret_key.get_secret_value(),
        *extra,
    ):
        assert forbidden not in text


def _token_with(**overrides: object) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": "1",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "token_type": "access",
    }
    payload.update(overrides)
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_me_returns_only_public_data_of_token_owner(
    client: httpx.AsyncClient, session: AsyncSession, caplog
):
    user = await _create_user(session)
    await session.flush()
    token = create_access_token(user.id)
    caplog.set_level(logging.DEBUG)

    response = await client.get(_URL, headers=_bearer(token))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == _PUBLIC_FIELDS
    assert body["id"] == user.id
    assert body["email"] == user.email
    assert body["name"] == user.name
    assert body["is_active"] is True
    assert "password" not in response.text
    _assert_no_leaks(response.text)
    _assert_no_leaks(caplog.text, token)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_me_never_returns_another_users_data(
    client: httpx.AsyncClient, session: AsyncSession
):
    user_a = await _create_user(session, name="Ana")
    user_b = await _create_user(session, name="Bruno")
    await session.flush()

    response_a = await client.get(_URL, headers=_bearer(create_access_token(user_a.id)))
    response_b = await client.get(_URL, headers=_bearer(create_access_token(user_b.id)))

    assert response_a.json()["id"] == user_a.id
    assert response_a.json()["email"] == user_a.email
    assert user_b.email not in response_a.text
    assert response_b.json()["id"] == user_b.id
    assert user_a.email not in response_b.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_me_does_not_write_to_database(
    client: httpx.AsyncClient, session: AsyncSession, sql_log: list[str]
):
    user = await _create_user(session)
    await session.flush()
    before = (user.updated_at, user.is_active)
    sql_log.clear()

    response = await client.get(_URL, headers=_bearer(create_access_token(user.id)))

    assert response.status_code == 200
    assert [s for s in sql_log if s.lstrip().upper().startswith("SELECT")] != []
    assert all(s.lstrip().upper().startswith("SELECT") for s in sql_log)
    assert (user.updated_at, user.is_active) == before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_me_rejects_user_deleted_after_token_issue(
    client: httpx.AsyncClient, session: AsyncSession, caplog
):
    user = await _create_user(session)
    await session.flush()
    token = create_access_token(user.id)
    assert (await client.get(_URL, headers=_bearer(token))).status_code == 200
    caplog.set_level(logging.DEBUG)

    await session.execute(delete(User).where(User.id == user.id))
    session.expire_all()
    response = await client.get(_URL, headers=_bearer(token))

    _assert_generic_401(response)
    _assert_no_leaks(response.text, token)
    _assert_no_leaks(caplog.text, token)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_me_rejects_user_deactivated_after_token_issue(
    client: httpx.AsyncClient, session: AsyncSession, caplog
):
    user = await _create_user(session)
    await session.flush()
    assert user.is_active is True
    token = create_access_token(user.id)
    assert (await client.get(_URL, headers=_bearer(token))).status_code == 200

    # Desativa direto no banco, sem passar pelo objeto já carregado.
    await session.execute(
        update(User).where(User.id == user.id).values(is_active=False)
    )
    session.expire_all()
    caplog.set_level(logging.DEBUG)
    response = await client.get(_URL, headers=_bearer(token))

    _assert_generic_401(response)
    assert user.email not in response.text
    _assert_no_leaks(response.text, token)
    _assert_no_leaks(caplog.text, token)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_me_rejects_valid_token_for_unknown_user_id(client: httpx.AsyncClient):
    response = await client.get(_URL, headers=_bearer(create_access_token(2**31 - 1)))

    _assert_generic_401(response)


_NO_SQL_CASES: dict[str, Callable[[], dict[str, str]]] = {
    "ausente": lambda: {},
    "basic": lambda: {"Authorization": "Basic dXNlcjpwYXNz"},
    "bearer-vazio": lambda: {"Authorization": "Bearer "},
    "so-esquema": lambda: {"Authorization": "Bearer"},
    "malformado": lambda: _bearer("isto-nao-e-um-jwt"),
    "assinatura-invalida": lambda: _bearer(
        jwt.encode({"sub": "1"}, "outra-chave-" * 4, algorithm="HS256")
    ),
    "expirado": lambda: _bearer(
        create_access_token(1, now=datetime.now(UTC) - timedelta(days=1))
    ),
    "sub-invalido": lambda: _bearer(_token_with(sub="abc")),
    "tipo-errado": lambda: _bearer(_token_with(token_type="refresh")),
}


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(_NO_SQL_CASES))
async def test_me_rejects_bad_credentials_without_touching_database(
    case: str,
    client: httpx.AsyncClient,
    sql_log: list[str],
    monkeypatch: pytest.MonkeyPatch,
    caplog,
):
    calls: list[int] = []

    async def spy(self: UserRepository, user_id: int) -> None:
        calls.append(user_id)

    monkeypatch.setattr(UserRepository, "get_by_id", spy)
    headers = _NO_SQL_CASES[case]()
    caplog.set_level(logging.DEBUG)

    response = await client.get(_URL, headers=headers)

    _assert_generic_401(response)
    assert calls == []
    assert sql_log == []
    _assert_no_leaks(response.text)
    token = headers.get("Authorization", "").removeprefix("Bearer ")
    _assert_no_leaks(caplog.text, *([token] if len(token) > 10 else []))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_me_database_unavailable_returns_controlled_500(
    caplog,
):
    # Porta 1: conexão recusada de verdade, sem mexer no banco de testes.
    broken_url = URL.create(
        drivername=database_url.drivername,
        username="usuario",
        password="segredo-do-banco",
        host="127.0.0.1",
        port=1,
        database="inexistente",
    )
    broken_engine = create_async_engine(broken_url)

    async def broken_get_db() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(broken_engine) as broken_session:
            yield broken_session

    app.dependency_overrides[get_db] = broken_get_db
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    token = create_access_token(1)
    caplog.set_level(logging.DEBUG)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as http_client:
            response = await http_client.get(_URL, headers=_bearer(token))
    finally:
        app.dependency_overrides.pop(get_db, None)
        await broken_engine.dispose()

    assert response.status_code == 500
    assert response.json() == {"detail": "Erro interno do servidor."}
    assert "WWW-Authenticate" not in response.headers
    for forbidden in ("segredo-do-banco", "127.0.0.1", "SELECT", "OperationalError"):
        assert forbidden not in response.text
    _assert_no_leaks(response.text, token)
    assert "segredo-do-banco" not in caplog.text
    _assert_no_leaks(caplog.text, token)


_COMMITTED_EMAILS: list[str] = []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_isolation_step1_explicit_commit_stays_inside_outer_transaction(
    client: httpx.AsyncClient, session: AsyncSession
):
    user = await _create_user(session)
    _COMMITTED_EMAILS.append(user.email)

    # Com create_savepoint, o commit só libera o SAVEPOINT; a transação externa
    # segue aberta. Sem isso, o dado seria persistido de verdade.
    await session.commit()

    response = await client.get(_URL, headers=_bearer(create_access_token(user.id)))
    assert response.status_code == 200
    async with engine.connect() as other:
        visible = await other.scalar(
            select(func.count()).select_from(User).where(User.email == user.email)
        )
    assert visible == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_isolation_step2_committed_data_is_gone_after_previous_test():
    # Depende do passo 1 (ordem do arquivo): ele já terminou e foi revertido.
    assert len(_COMMITTED_EMAILS) == 1
    async with engine.connect() as other:
        remaining = await other.scalar(
            select(func.count())
            .select_from(User)
            .where(User.email == _COMMITTED_EMAILS[0])
        )
    assert remaining == 0


def test_openapi_documents_me_with_bearer_security():
    schema = app.openapi()

    operation = schema["paths"]["/api/v1/auth/me"]["get"]
    assert operation["security"] == [{"HTTPBearer": []}]
    scheme = schema["components"]["securitySchemes"]["HTTPBearer"]
    assert scheme == {"type": "http", "scheme": "bearer"}
    ok = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok == {"$ref": "#/components/schemas/UserResponse"}
    user_schema = schema["components"]["schemas"]["UserResponse"]
    assert set(user_schema["properties"]) == _PUBLIC_FIELDS
