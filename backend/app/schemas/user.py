from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, StringConstraints


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=150),
    ]
    # Convenção do Nexus: o endereço inteiro fica em minúsculas.
    # O email-validator só normaliza o domínio; isto não é regra universal de e-mail.
    email: Annotated[EmailStr, AfterValidator(str.lower)]
    password: Annotated[
        str,
        StringConstraints(min_length=15, max_length=128, strip_whitespace=False),
    ]
