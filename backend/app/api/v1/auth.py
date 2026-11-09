"""Rotas de autenticação."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.database import get_db
from app.core.exceptions import DuplicateEmailError
from app.schemas.user import UserRegister, UserResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    payload: UserRegister,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    # get_db só entrega a sessão. O serviço confirma ou desfaz a transação.
    service = AuthService(session)
    try:
        user = await service.register(payload)
    except DuplicateEmailError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email já cadastrado.",
        ) from None
    return UserResponse.model_validate(user)
