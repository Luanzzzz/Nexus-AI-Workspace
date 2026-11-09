"""Dependências de autenticação: AuthService e usuário atual."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.database import get_db
from app.core.tokens import InvalidTokenError, decode_access_token
from app.models.user import User
from app.repositories.user import UserRepository
from app.services.auth import AuthService

# auto_error=False: o 401 é montado aqui (mensagem genérica "Não autenticado."
# e WWW-Authenticate), em vez da resposta padrão do HTTPBearer.
# O login é JSON próprio, então OAuth2PasswordBearer não se aplica.
bearer_scheme = HTTPBearer(auto_error=False)

NOT_AUTHENTICATED_DETAIL = "Não autenticado."


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthService:
    return AuthService(session)


def _unauthorized() -> HTTPException:
    # Mensagem única: não diferencia token ruim, usuário ausente ou inativo.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=NOT_AUTHENTICATED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Devolve o usuário do token Bearer; o banco decide se a conta ainda vale.

    O JWT só prova que o backend emitiu o token. Toda requisição consulta o
    usuário. Falhas do banco não são capturadas: viram o 500 genérico.
    """
    # 1) Credenciais: ausente, não-Bearer ou vazio não chegam ao JWT nem ao banco.
    if credentials is None or not credentials.credentials:
        raise _unauthorized()
    # 2) e 3) Assinatura, expiração e `sub` válido, tudo antes de qualquer SQL.
    try:
        claims = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise _unauthorized() from None
    # 4) Só agora a consulta ao banco.
    user = await UserRepository(session).get_by_id(claims.user_id)
    # 5) Removido ou desativado depois da emissão: o token deixa de valer.
    if user is None or not user.is_active:
        raise _unauthorized()
    return user
