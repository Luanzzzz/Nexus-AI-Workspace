"""Rotas de workspace."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_current_user
from app.api.dependencies.database import get_db
from app.api.dependencies.workspace import (
    READ,
    WORKSPACE_NOT_FOUND_DETAIL,
    get_workspace_service,
    require_permission,
)
from app.models.user import User
from app.models.workspace_member import WorkspaceMember
from app.repositories.workspace import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate, WorkspaceResponse
from app.services.workspace import WorkspaceService

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    payload: WorkspaceCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[WorkspaceService, Depends(get_workspace_service)],
) -> WorkspaceResponse:
    # Slug duplicado vira 409 no exception handler.
    workspace = await service.create_workspace(payload, current_user)
    return WorkspaceResponse.model_validate(workspace)


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[WorkspaceResponse]:
    workspaces = await WorkspaceRepository(session).list_by_user(current_user.id)
    return [WorkspaceResponse.model_validate(item) for item in workspaces]


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def read_workspace(
    membership: Annotated[WorkspaceMember, Depends(require_permission(READ))],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceResponse:
    workspace = await WorkspaceRepository(session).get_by_id(membership.workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=WORKSPACE_NOT_FOUND_DETAIL,
        )
    return WorkspaceResponse.model_validate(workspace)
