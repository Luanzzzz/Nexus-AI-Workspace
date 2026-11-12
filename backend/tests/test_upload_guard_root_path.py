"""O guarda de upload também vale com `root_path` e sob app montado (R01).

Sem integração com o banco: o app interno é um stub que conta bytes lidos.
"""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.api.upload_guard import BODY_LIMIT, UploadGuardMiddleware
from app.core.tokens import create_access_token

UPLOAD = "/api/v1/workspaces/1/documents"


class _Stub:
    def __init__(self) -> None:
        self.read = 0
        self.entered = 0

    async def __call__(self, scope, receive, send):
        self.entered += 1
        while True:
            message = await receive()
            self.read += len(message.get("body", b""))
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


def _bearer() -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(1)}"}


def _chunks(total: int, size: int = 64 * 1024):
    for _ in range(total // size):
        yield b"x" * size


def _served_with_root_path(stub: _Stub) -> TestClient:
    return TestClient(UploadGuardMiddleware(stub), root_path="/prefix")


def _mounted(stub: _Stub) -> TestClient:
    # Guarda sobre o stub, montado sob um app pai.
    parent = Starlette(routes=[Mount("/sub", app=UploadGuardMiddleware(stub))])
    return TestClient(parent)


@pytest.mark.parametrize("factory", [_served_with_root_path, _mounted])
def test_anonymous_post_gets_401_without_reading_body(factory):
    stub = _Stub()
    client = factory(stub)
    prefix = "/prefix" if factory is _served_with_root_path else "/sub"
    response = client.post(prefix + UPLOAD, content=_chunks(1024 * 1024))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert stub.entered == 0
    assert stub.read == 0


@pytest.mark.parametrize("factory", [_served_with_root_path, _mounted])
def test_oversized_chunked_body_with_valid_jwt_gets_bounded_413(factory):
    stub = _Stub()
    client = factory(stub)
    prefix = "/prefix" if factory is _served_with_root_path else "/sub"
    response = client.post(
        prefix + UPLOAD, content=_chunks(30 * 1024 * 1024), headers=_bearer()
    )

    assert response.status_code == 413
    assert stub.read <= BODY_LIMIT + 64 * 1024


@pytest.mark.asyncio
async def test_root_path_set_but_path_without_prefix_is_guarded():
    # Segunda convenção do Starlette: root_path informado, path sem o prefixo.
    stub = _Stub()
    sent: list[dict] = []
    read = 0

    async def receive():
        nonlocal read
        read += 1
        return {"type": "http.request", "body": b"x", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": UPLOAD,
        "root_path": "/gw",
        "headers": [],
    }
    await UploadGuardMiddleware(stub)(scope, receive, send)
    assert sent[0]["status"] == 401
    assert stub.entered == 0 and read == 0


@pytest.mark.parametrize("factory", [_served_with_root_path, _mounted])
def test_non_upload_routes_are_untouched(factory):
    stub = _Stub()
    client = factory(stub)
    prefix = "/prefix" if factory is _served_with_root_path else "/sub"
    for method, path in (
        ("POST", "/api/v1/workspaces"),
        ("POST", "/api/v1/workspaces/1/documents/2"),
        ("GET", UPLOAD),
    ):
        response = client.request(method, prefix + path, content=b"x")
        assert response.status_code == 201, (method, path)
    assert stub.entered == 3


@pytest.mark.asyncio
async def test_direct_asgi_with_root_path_and_prefixed_path():
    # uvicorn --root-path: scope["path"] inclui o root_path.
    stub = _Stub()
    transport = httpx.ASGITransport(
        app=UploadGuardMiddleware(stub), root_path="/gw", raise_app_exceptions=False
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.post("/gw" + UPLOAD, content=b"x")
    assert response.status_code == 401
    assert stub.entered == 0
