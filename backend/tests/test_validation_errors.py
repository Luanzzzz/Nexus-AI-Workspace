"""O 422 público só devolve loc, type e msg."""

import json

from fastapi.testclient import TestClient

from app.api.exception_handlers import sanitize_validation_errors
from app.main import app

_CLIENT = TestClient(app)
_SECRET = "senha-secreta"


def test_sanitizer_drops_input_and_ctx_from_sensitive_string():
    errors = [
        {
            "loc": ("body",),
            "type": "model_attributes_type",
            "msg": "Invalid input",
            "input": json.dumps({"password": _SECRET}),
            "ctx": {"error": _SECRET},
        }
    ]

    public = sanitize_validation_errors(errors)

    assert public == [
        {"loc": ["body"], "type": "model_attributes_type", "msg": "Invalid input"}
    ]
    assert _SECRET not in json.dumps(public)


def test_sanitizer_drops_nested_structures():
    errors = [
        {
            "loc": ("body", "profile"),
            "type": "x",
            "msg": "m",
            "input": {"a": [{"credentials": {"token": _SECRET}}]},
            "ctx": {"nested": [{"secret": _SECRET}]},
        }
    ]

    assert _SECRET not in json.dumps(sanitize_validation_errors(errors))


def test_http_invalid_json_body_does_not_leak_credentials():
    response = _CLIENT.post(
        "/api/v1/auth/register",
        content=f'{{"password": "{_SECRET}",',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert _SECRET not in response.text
    for error in response.json()["detail"]:
        assert "input" not in error
        assert "ctx" not in error


def test_http_string_body_does_not_leak_credentials():
    response = _CLIENT.post(
        "/api/v1/auth/register",
        json=json.dumps({"password": _SECRET}),
    )

    assert response.status_code == 422
    assert _SECRET not in response.text


def test_http_nested_body_does_not_leak_credentials():
    response = _CLIENT.post(
        "/api/v1/auth/register",
        json={
            "name": {"inner": [{"password": _SECRET}]},
            "email": ["x", {"token": _SECRET}],
            "password": _SECRET,
        },
    )

    assert response.status_code == 422
    assert _SECRET not in response.text
