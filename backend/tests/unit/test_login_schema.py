import pytest
from pydantic import ValidationError

from app.schemas.user import LoginRequest


def test_login_request_lowercases_whole_email():
    login = LoginRequest(email="Ana.Silva@Example.COM", password="x")

    assert login.email == "ana.silva@example.com"


def test_login_request_accepts_short_password_without_policy():
    assert LoginRequest(email="a@example.com", password="1").password == "1"


def test_login_request_keeps_password_whitespace():
    login = LoginRequest(email="a@example.com", password="  senha  ")

    assert login.password == "  senha  "


@pytest.mark.parametrize("password", ["", "x" * 129])
def test_login_request_rejects_empty_or_oversized_password(password: str):
    with pytest.raises(ValidationError):
        LoginRequest(email="a@example.com", password=password)


def test_login_request_rejects_invalid_email_and_extra_fields():
    with pytest.raises(ValidationError):
        LoginRequest(email="sem-arroba", password="x")
    with pytest.raises(ValidationError):
        LoginRequest.model_validate(
            {"email": "a@example.com", "password": "x", "name": "Ana"},
        )


def test_login_request_repr_does_not_leak_password():
    login = LoginRequest(email="a@example.com", password="segredo-ficticio")

    assert "segredo-ficticio" not in repr(login)
    assert "segredo-ficticio" not in str(login)
