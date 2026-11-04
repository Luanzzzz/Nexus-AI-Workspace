"""Associação entre um usuário e um workspace.

O papel é texto restrito aos valores do documento. A criação da associação
do proprietário fica para a camada de serviço.
Ver docs/decisions/0002-papel-de-workspace-member.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    # Importação só para o tipo: os modelos de associação se referenciam.
    from app.models.user import User
    from app.models.workspace import Workspace

WORKSPACE_MEMBER_ROLES: tuple[str, ...] = ("owner", "admin", "member", "viewer")

_ROLE_CHECK_SQL = "role IN ({})".format(
    ", ".join(f"'{role}'" for role in WORKSPACE_MEMBER_ROLES)
)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_members_workspace_id_user_id",
        ),
        CheckConstraint(_ROLE_CHECK_SQL, name="ck_workspace_members_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    workspace: Mapped[Workspace] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")
