from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.user import SafeName

# Minúsculas ASCII, números e hífens; sem hífen no início, no fim ou duplo.
# 3 a 63 caracteres (cabe em um rótulo DNS, caso o slug vire subdomínio).
WorkspaceSlug = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=63,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]


class WorkspaceCreate(BaseModel):
    # Campos extras (owner_id, role...) são rejeitados com 422, não ignorados.
    model_config = ConfigDict(extra="forbid")
    name: SafeName
    slug: WorkspaceSlug


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    owner_id: int
    created_at: datetime
    updated_at: datetime
