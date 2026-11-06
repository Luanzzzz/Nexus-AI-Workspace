from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.user import User
from app.schemas.user import UserRegister, UserResponse

# Senha fictícia dentro da política de 15 a 128 caracteres.
_VALID_PASSWORD = "senha-ficticia-ok"


def test_user_response_serializes_public_user_fields():

    # Datas explícitas: sem persistir, o ORM não aplica os defaults.
    created_at = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    updated_at = datetime(2026, 11, 6, 12, 5, tzinfo=UTC)

    # Objeto em memória, inclusive com o hash que não pode sair na resposta.
    user = User(
        id=1,
        name="John Doe",
        email="john.doe@example.com",
        password_hash="fake-password-hash",
        is_active=True,
        created_at=created_at,
        updated_at=updated_at,
    )

    # Converte o objeto do ORM e serializa só os campos do schema.
    serialized = UserResponse.model_validate(user).model_dump()

    # Campos públicos presentes; senha e hash ficam de fora do dicionário.
    assert serialized["id"] == 1
    assert serialized["name"] == "John Doe"
    assert serialized["email"] == "john.doe@example.com"
    assert serialized["is_active"] is True
    assert serialized["created_at"] == created_at
    assert serialized["updated_at"] == updated_at
    assert "password" not in serialized
    assert "password_hash" not in serialized


def test_user_register_accepts_valid_data():
    # Dados válidos do contrato de registro: nome, email e senha em texto puro.
    data = {
        "name": "John Doe",
        "email": "john.doe@example.com",
        "password": _VALID_PASSWORD,
    }

    # Valida o dicionário pelo schema, sem banco e sem hashing.
    user_register = UserRegister.model_validate(data)

    # Os três campos entram; password_hash não faz parte do schema.
    assert user_register.name == "John Doe"
    assert user_register.email == "john.doe@example.com"
    assert user_register.password == _VALID_PASSWORD
    assert not user_register.password.startswith("$argon2")
    assert "password_hash" not in UserRegister.model_fields
    assert "password_hash" not in user_register.model_dump()


def test_user_register_rejects_invalid_email():

    # preparar um dicionario com nome, email invalido e senha
    data = {
        "name": "John Doe",
        "email": "invalid-email",
        "password": _VALID_PASSWORD,
    }

    # Captura a rejeição e confirma que o campo email causou a falha.
    with pytest.raises(ValidationError) as exc_info:
        UserRegister.model_validate(data)

    # O local do erro precisa ser o campo email, com o tipo do EmailStr.
    errors = exc_info.value.errors()
    assert any(
        error["loc"] == ("email",) and error["type"] == "value_error"
        for error in errors
    )


def test_user_register_canonicalizes_email_case():
    # Convenção do Nexus: o endereço inteiro vira minúsculas.
    data = {
        "name": "Ana",
        "email": "USUARIO@EXAMPLE.COM",
        "password": _VALID_PASSWORD,
    }

    user_register = UserRegister.model_validate(data)

    assert user_register.email == "usuario@example.com"


def test_user_register_rejects_extra_fields():
    # Preparar o dicionário de registro com os três campos válidos e os extras is_active e password_hash.
    data = {
        "name": "John Doe",
        "email": "john.doe@example.com",
        "password": _VALID_PASSWORD,
        "is_active": True,
        "password_hash": "fake-password-hash",
    }

    # Capturar o ValidationError com pytest.raises().
    with pytest.raises(ValidationError) as exc_info:
        UserRegister.model_validate(data)

    # Os dois extras são rejeitados com o tipo extra_forbidden.
    errors = exc_info.value.errors()
    assert any(
        error["loc"] == ("is_active",) and error["type"] == "extra_forbidden"
        for error in errors
    )
    assert any(
        error["loc"] == ("password_hash",) and error["type"] == "extra_forbidden"
        for error in errors
    )


@pytest.mark.parametrize("missing_field", ["name", "email", "password"])
def test_user_register_rejects_missing_required_field(missing_field):
    # Parte de um registro válido e retira um campo obrigatório por cenário.
    data = {
        "name": "John Doe",
        "email": "john.doe@example.com",
        "password": _VALID_PASSWORD,
    }
    incomplete = data.copy()
    del incomplete[missing_field]

    with pytest.raises(ValidationError) as exc_info:
        UserRegister.model_validate(incomplete)

    # A falha precisa ser missing no campo que foi removido.
    errors = exc_info.value.errors()
    assert any(
        error["loc"] == (missing_field,) and error["type"] == "missing"
        for error in errors
    )


def test_user_register_normalizes_name():
    # Espaços nas pontas saem; email e senha só mantêm o cadastro válido.
    data = {
        "name": "  Júlia  ",
        "email": "julia@example.com",
        "password": _VALID_PASSWORD,
    }

    user_register = UserRegister.model_validate(data)

    assert user_register.name == "Júlia"


@pytest.mark.parametrize(
    ("name", "error_type"),
    [
        ("", "string_too_short"),
        ("   ", "string_too_short"),
        ("n" * 151, "string_too_long"),
    ],
)
def test_user_register_rejects_name_outside_length_policy(name, error_type):
    data = {
        "name": name,
        "email": "julia@example.com",
        "password": _VALID_PASSWORD,
    }

    with pytest.raises(ValidationError) as exc_info:
        UserRegister.model_validate(data)

    errors = exc_info.value.errors()
    assert any(
        error["loc"] == ("name",) and error["type"] == error_type for error in errors
    )


@pytest.mark.parametrize("name", ["Ana", "Anne-Marie", "José"])
def test_user_register_accepts_simple_accented_and_hyphenated_names(name):
    data = {
        "name": name,
        "email": "ana@example.com",
        "password": _VALID_PASSWORD,
    }

    user_register = UserRegister.model_validate(data)

    assert user_register.name == name


@pytest.mark.parametrize(
    ("password", "error_type"),
    [
        ("", "string_too_short"),
        ("senha-ficticia", "string_too_short"),
        ("p" * 14, "string_too_short"),
        ("p" * 129, "string_too_long"),
    ],
)
def test_user_register_rejects_password_outside_length_policy(password, error_type):
    data = {
        "name": "Ana",
        "email": "ana@example.com",
        "password": password,
    }

    with pytest.raises(ValidationError) as exc_info:
        UserRegister.model_validate(data)

    errors = exc_info.value.errors()
    assert any(
        error["loc"] == ("password",) and error["type"] == error_type
        for error in errors
    )


@pytest.mark.parametrize(
    "password",
    [
        "p" * 15,
        "p" * 64,
        "p" * 128,
        "senha com ação 123",
        "  senha interna  ",
        "Senha-Ficticia-OK",
    ],
)
def test_user_register_accepts_password_within_length_policy(password):
    data = {
        "name": "Ana",
        "email": "ana@example.com",
        "password": password,
    }

    user_register = UserRegister.model_validate(data)

    # Sem strip, sem minúsculas e sem hashing: a senha permanece o texto recebido.
    assert user_register.password == password
    assert not user_register.password.startswith("$argon2")
