from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)

from app.core.emailcanon import canonicalize_email
from app.core.text import reject_control_characters


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RegisterResponse(BaseModel):
    detail: str


# Convenção do Nexus (ADR 0003): o endereço inteiro fica em minúsculas.
# O email-validator só normaliza o domínio; isto não é regra universal de e-mail.
CanonicalEmail = Annotated[
    EmailStr,
    AfterValidator(reject_control_characters),
    AfterValidator(canonicalize_email),
]

SafeName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=150),
    AfterValidator(reject_control_characters),
]

RegisterPassword = Annotated[
    str,
    StringConstraints(min_length=15, max_length=128, strip_whitespace=False),
]

LoginPassword = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, strip_whitespace=False),
]


class UserRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: SafeName
    email: CanonicalEmail
    password: RegisterPassword


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: CanonicalEmail
    # Sem política de tamanho mínimo: senhas antigas ou erradas chegam ao
    # verificador. O teto igual ao do cadastro evita Argon2 sobre entrada enorme.
    password: LoginPassword = Field(repr=False)
