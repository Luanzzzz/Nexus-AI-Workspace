"""X-Request-ID só ecoa valores curtos e seguros."""

from fastapi.testclient import TestClient

from app.api.middleware import sanitize_request_id
from app.main import app

_CLIENT = TestClient(app)


def test_sanitize_request_id_rejects_oversized_and_spaces():
    assert len(sanitize_request_id("a" * 65)) == 32
    assert sanitize_request_id("id with spaces") != "id with spaces"
    assert sanitize_request_id("abc-DEF_01") == "abc-DEF_01"


def test_http_ignores_giant_request_id():
    response = _CLIENT.get("/api/v1/health", headers={"X-Request-ID": "x" * 4000})
    assert response.status_code == 200
    echoed = response.headers["X-Request-ID"]
    assert echoed != "x" * 4000
    assert len(echoed) <= 64
