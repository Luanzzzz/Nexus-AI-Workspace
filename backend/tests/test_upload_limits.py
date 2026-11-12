"""Rate limit e teto de uploads simultâneos por usuário (F04, middleware ASGI).

O app interno é um stub: estes testes não tocam no banco. O corpo é um gerador
que conta quanto foi puxado; um 429 tem que sair sem consumir nenhum byte.
"""

import asyncio

import httpx
import pytest

from app.api.upload_guard import UploadGuardMiddleware
from app.core.config import settings
from app.core.rate_limit import upload_concurrency
from app.core.tokens import create_access_token

pytestmark = pytest.mark.asyncio

_RATE_LIMITED = {"detail": "Muitas tentativas. Tente novamente mais tarde."}


class _Body:
    def __init__(self) -> None:
        self.chunks = 0

    async def __aiter__(self):
        self.chunks += 1
        yield b"conteudo"


class _StubApp:
    """App interno: lê o corpo, opcionalmente espera/falha, responde 201."""

    def __init__(self) -> None:
        self.entered = 0
        self.gate: asyncio.Event | None = None
        self.fail = False
        self.only_marked = False

    async def __call__(self, scope, receive, send):
        self.entered += 1
        while True:
            message = await receive()
            if not message.get("more_body"):
                break
        blocking = any(name == b"x-block" for name, _ in scope["headers"])
        if self.gate is not None and (blocking or not self.only_marked):
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("falha do app")
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


@pytest.fixture
def stub():
    return _StubApp()


@pytest.fixture
def client(stub):
    transport = httpx.ASGITransport(
        app=UploadGuardMiddleware(stub), raise_app_exceptions=False
    )
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.fixture
def limits_on(monkeypatch):
    monkeypatch.setattr(settings, "upload_limits_enabled", True)
    monkeypatch.setattr(settings, "upload_rate_limit_per_minute", 3)
    monkeypatch.setattr(settings, "upload_max_concurrent_per_user", 2)


def _post(client, user_id: int, body: _Body | None = None, extra=None):
    return client.post(
        "/api/v1/workspaces/1/documents",
        content=body or _Body(),
        headers={
            "Authorization": f"Bearer {create_access_token(user_id)}",
            "Content-Type": "multipart/form-data; boundary=b",
            **(extra or {}),
        },
    )


async def _until(predicate, timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def test_rate_limit_blocks_after_limit_without_reading_body(
    client, stub, limits_on, monkeypatch
):
    monkeypatch.setattr(settings, "upload_max_concurrent_per_user", 50)
    async with client:
        for _ in range(3):
            assert (await _post(client, 1)).status_code == 201
        body = _Body()
        blocked = await _post(client, 1, body)

        assert blocked.status_code == 429
        assert blocked.json() == _RATE_LIMITED
        assert int(blocked.headers["Retry-After"]) >= 1
        assert blocked.headers["Cache-Control"] == "no-store"
        assert body.chunks == 0
        assert stub.entered == 3
        # Outro usuário não é afetado.
        assert (await _post(client, 2)).status_code == 201


async def test_rate_limit_respects_disable_switch(client, limits_on, monkeypatch):
    monkeypatch.setattr(settings, "upload_limits_enabled", False)
    async with client:
        for _ in range(6):
            assert (await _post(client, 1)).status_code == 201


async def test_invalid_jwt_does_not_consume_rate_limit(client, limits_on):
    async with client:
        for _ in range(5):
            response = await client.post(
                "/api/v1/workspaces/1/documents",
                content=b"x",
                headers={"Authorization": "Bearer lixo"},
            )
            assert response.status_code == 401
        assert (await _post(client, 1)).status_code == 201


async def test_concurrent_cap_blocks_third_upload_without_reading_body(
    client, stub, limits_on, monkeypatch
):
    monkeypatch.setattr(settings, "upload_rate_limit_per_minute", 100)
    stub.gate = asyncio.Event()
    async with client:
        first = asyncio.create_task(_post(client, 1))
        second = asyncio.create_task(_post(client, 1))
        await _until(lambda: stub.entered == 2)

        body = _Body()
        third = await asyncio.wait_for(_post(client, 1, body), 3)
        assert third.status_code == 429
        assert third.json() == _RATE_LIMITED
        assert third.headers["Retry-After"] == "1"
        assert body.chunks == 0
        assert stub.entered == 2

        # Outro usuário tem as próprias vagas.
        other = asyncio.create_task(_post(client, 2))
        await _until(lambda: stub.entered == 3)

        stub.gate.set()
        assert (await first).status_code == 201
        assert (await second).status_code == 201
        assert (await other).status_code == 201
        assert upload_concurrency.active("upload:user:1") == 0
        assert upload_concurrency.active("upload:user:2") == 0
        # Vagas liberadas: novo upload do mesmo usuário passa.
        assert (await _post(client, 1)).status_code == 201


async def test_slots_released_when_downstream_fails(
    client, stub, limits_on, monkeypatch
):
    monkeypatch.setattr(settings, "upload_rate_limit_per_minute", 100)
    stub.fail = True
    async with client:
        for _ in range(4):  # mais que o teto: vagas vazariam se não liberasse
            assert (await _post(client, 1)).status_code == 500
        assert upload_concurrency.active("upload:user:1") == 0
        stub.fail = False
        assert (await _post(client, 1)).status_code == 201


async def test_slots_released_on_cancellation(client, stub, limits_on, monkeypatch):
    monkeypatch.setattr(settings, "upload_rate_limit_per_minute", 100)
    stub.gate = asyncio.Event()
    async with client:
        tasks = [asyncio.create_task(_post(client, 1)) for _ in range(2)]
        await _until(lambda: stub.entered == 2)
        assert upload_concurrency.active("upload:user:1") == 2
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _until(lambda: upload_concurrency.active("upload:user:1") == 0)

        stub.gate.set()
        assert (await _post(client, 1)).status_code == 201


@pytest.mark.integration
async def test_real_app_is_wired_with_upload_limits(limits_on, monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "upload_rate_limit_per_minute", 1)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as real:
        first = await real.post(
            "/api/v1/workspaces/1/documents",
            files={"file": ("a.txt", b"x", "text/plain")},
            headers={"Authorization": f"Bearer {create_access_token(2_000_000_001)}"},
        )
        body = _Body()
        second = await _post(real, 2_000_000_001, body)

    assert first.status_code == 401  # usuário inexistente: passou pelo guarda
    assert second.status_code == 429
    assert body.chunks == 0


async def test_each_slot_is_released_exactly_once(client, stub, limits_on, monkeypatch):
    monkeypatch.setattr(settings, "upload_rate_limit_per_minute", 100)
    stub.gate = asyncio.Event()
    stub.only_marked = True
    async with client:
        held = asyncio.create_task(_post(client, 1, extra={"x-block": "1"}))
        await _until(lambda: stub.entered == 1)
        # Um upload que termina sozinho não pode liberar a vaga do outro.
        assert (await _post(client, 1)).status_code == 201
        assert upload_concurrency.active("upload:user:1") == 1
        stub.gate.set()
        assert (await held).status_code == 201
        assert upload_concurrency.active("upload:user:1") == 0
