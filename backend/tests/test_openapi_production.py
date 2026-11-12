"""OpenAPI desligado em production; debug não devolve traceback ao cliente."""

from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app.api.dependencies.database import get_db
from app.core.config import settings
from app.main import create_app
from app.schemas.user import LoginRequest
from app.services.auth import AuthService


def test_production_hides_openapi(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "debug", False)
    prod_app = create_app()
    client = TestClient(prod_app)

    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_debug_true_does_not_put_traceback_on_client(monkeypatch):
    async def fail(self: AuthService, credentials: LoginRequest):
        raise RuntimeError("traceback-secreto-nao-pode-sair")

    async def fake_db() -> AsyncIterator[object]:
        yield object()

    monkeypatch.setattr(AuthService, "authenticate", fail)
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "debug", True)
    debug_app = create_app()
    debug_app.dependency_overrides[get_db] = fake_db
    client = TestClient(debug_app, raise_server_exceptions=True)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": "senha-ficticia-ok"},
    )

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert "traceback-secreto-nao-pode-sair" not in response.text
    assert "RuntimeError" not in response.text


def test_workspace_and_document_routes_document_error_responses():
    from app.main import app

    paths = app.openapi()["paths"]
    base = "/api/v1/workspaces"
    detail = base + "/{workspace_id}"
    docs = detail + "/documents"
    item = docs + "/{document_id}"
    expected = {
        (base, "post"): {"401", "409", "422"},
        (base, "get"): {"401"},
        (detail, "get"): {"401", "404", "422"},
        (docs, "post"): {"401", "403", "404", "413", "415", "422", "429"},
        (docs, "get"): {"401", "404", "422"},
        (item, "get"): {"401", "404", "422"},
        (item, "delete"): {"401", "403", "404", "422"},
    }
    for (path, method), codes in expected.items():
        assert codes <= set(paths[path][method]["responses"]), (path, method)
