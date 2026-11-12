"""Autorização por workspace: membership e permissão por papel.

Sem membership (ou workspace inexistente) o resultado é 404, para não
revelar a existência do workspace. Membro sem a permissão pedida recebe 403.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.database import get_db
from app.api.exception_handlers import (  # noqa: F401  (reexport)
    FORBIDDEN_DETAIL,
    WORKSPACE_NOT_FOUND_DETAIL,
)
from app.core.permissions import (  # noqa: F401  (reexport)
    DELETE_DOCUMENT,
    PERMISSIONS,
    READ,
    UPLOAD_DOCUMENT,
    role_has_permission,
)
from app.models.user import User
from app.models.workspace_member import WorkspaceMember
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.services.workspace import WorkspaceService

# O id é INTEGER no PostgreSQL: valores fora da faixa viram 422, não erro de banco.
WorkspaceId = Annotated[int, Path(ge=1, le=2147483647)]


def get_workspace_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceService:
    return WorkspaceService(session)


async def get_workspace_membership(
    workspace_id: WorkspaceId,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceMember:
    """Membership do usuário atual no workspace, ou 404."""
    membership = await WorkspaceMemberRepository(session).get_membership(
        workspace_id, current_user.id
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=WORKSPACE_NOT_FOUND_DETAIL,
        )
    return membership


def require_permission(
    permission: str,
) -> Callable[[WorkspaceMember], Awaitable[WorkspaceMember]]:
    """Dependency que exige `permission`: 404 sem membership, 403 sem permissão."""

    async def dependency(
        membership: Annotated[WorkspaceMember, Depends(get_workspace_membership)],
    ) -> WorkspaceMember:
        if not role_has_permission(membership.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=FORBIDDEN_DETAIL,
            )
        return membership

    return dependency
