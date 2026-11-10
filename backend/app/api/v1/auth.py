"""Rotas de autenticação."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies.auth import get_auth_service, get_current_user
from app.api.dependencies.rate_limit import login_rate_limit, register_rate_limit
from app.api.exception_handlers import REGISTER_PROCESSED_DETAIL
from app.core.exceptions import DuplicateEmailError
from app.core.tokens import create_access_token
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.schemas.user import LoginRequest, RegisterResponse, UserRegister, UserResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(register_rate_limit)],
)
async def register_user(
    payload: UserRegister,
    service: Annotated[AuthService, Depends(get_auth_service)],
    response: Response,
) -> RegisterResponse:
    # Resposta idêntica para email novo e já cadastrado (OWASP).
    _no_store(response)
    try:
        await service.register(payload)
    except DuplicateEmailError:
        pass
    return RegisterResponse(detail=REGISTER_PROCESSED_DETAIL)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(login_rate_limit)],
)
async def login(
    payload: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
    response: Response,
) -> TokenResponse:
    # Falhas viram HTTP nos exception handlers; o token só nasce após sucesso.
    _no_store(response)
    user = await service.authenticate(payload)
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserResponse)
async def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
    response: Response,
) -> UserResponse:
    # response_model filtra: password_hash do ORM nunca sai na resposta.
    _no_store(response)
    return UserResponse.model_validate(current_user)
