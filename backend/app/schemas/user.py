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


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# Convenção do Nexus (ADR 0003): o endereço inteiro fica em minúsculas.
# O email-validator só normaliza o domínio; isto não é regra universal de e-mail.
CanonicalEmail = Annotated[EmailStr, AfterValidator(str.lower)]


class UserRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=150),
    ]
    email: CanonicalEmail
    password: Annotated[
        str,
        StringConstraints(min_length=15, max_length=128, strip_whitespace=False),
    ]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: CanonicalEmail
    # Sem política de tamanho mínimo: senhas antigas ou erradas chegam ao
    # verificador. O teto igual ao do cadastro evita Argon2 sobre entrada enorme.
    password: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128, strip_whitespace=False),
    ] = Field(repr=False)
