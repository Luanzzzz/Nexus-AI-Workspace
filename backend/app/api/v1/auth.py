"""Rotas de autenticação."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.auth import get_auth_service, get_current_user
from app.api.dependencies.database import get_db
from app.core.exceptions import DuplicateEmailError
from app.core.tokens import create_access_token
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.schemas.user import LoginRequest, UserRegister, UserResponse
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


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    # Falhas viram HTTP nos exception handlers; o token só nasce após sucesso.
    user = await service.authenticate(payload)
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserResponse)
async def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    # response_model filtra: password_hash do ORM nunca sai na resposta.
    return UserResponse.model_validate(current_user)
