"""Caso de uso de cadastro.

O SQLAlchemy 2 abre a transação sozinho na primeira consulta (autobegin).
Este serviço não chama session.begin(): depois do get_by_email a transação
já está ativa, e um begin() nessa hora falharia. O fim da transação é
commit() no sucesso ou rollback() na duplicidade e em qualquer falha.
"""

import asyncio
import secrets
from functools import cache

from argon2.exceptions import VerificationError
from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    CredentialVerificationError,
    DuplicateEmailError,
    InvalidCredentialsError,
)
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import LoginRequest, UserRegister

# Nome que o PostgreSQL deu ao UNIQUE(email) na migration inicial.
_EMAIL_UNIQUE_CONSTRAINT = "users_email_key"


@cache
def _dummy_password_hash() -> str:
    # Hash Argon2id descartável, com os mesmos parâmetros dos hashes reais.
    # Gerado uma vez (lazy) e usado quando o email não existe, para a
    # resposta gastar um Argon2 como no caso de usuário real.
    return hash_password(secrets.token_urlsafe(32))


def _verify_blocking(password: str, password_hash: str | None) -> bool:
    # Roda em thread. Hash corrompido ou erro do verificador é falha interna,
    # nunca "credencial inválida"; `from None` evita carregar o hash adiante.
    try:
        if password_hash is None:
            password_hash = _dummy_password_hash()
        return verify_password(password, password_hash)
    except (VerificationError, ValueError):
        raise CredentialVerificationError from None


class AuthService:
    # A sessão vem de fora. O repositório só usa essa mesma sessão.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def register(self, data: UserRegister) -> User:
        # O schema também baixa a caixa. O caso de uso repete, porque o
        # repositório compara o email exatamente como recebe.
        email = data.email.lower()

        try:
            existing = await self.users.get_by_email(email)
            if existing is not None:
                # Sem escrita para confirmar; o except abaixo faz o rollback.
                raise DuplicateEmailError

            # Argon2id é síncrono e lento; a thread libera o event loop.
            # A transação aberta pela consulta continua até o commit
            # (trade-off aceito no MVP: conexão ocupada durante o hash).
            password_hash = await asyncio.to_thread(hash_password, data.password)
            user = await self.users.create_user(
                name=data.name,
                email=email,
                password_hash=password_hash,
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            if _is_email_unique_violation(exc):
                raise DuplicateEmailError from exc
            raise
        except Exception:
            await self.session.rollback()
            raise

        return user

    async def authenticate(self, credentials: LoginRequest) -> User:
        """Valida email e senha; só lê, sem commit nem rollback.

        Inexistente, senha errada e inativo levantam a mesma
        InvalidCredentialsError, depois de uma verificação Argon2 em todos.
        """
        email = credentials.email.lower()
        user = await self.users.get_by_email(email)

        # Sem usuário, confere contra o hash fictício para igualar o custo.
        # Argon2id fora do event loop, como no cadastro; o hash fictício
        # (se ainda não existe) também é gerado dentro da thread.
        matches = await asyncio.to_thread(
            _verify_blocking,
            credentials.password,
            user.password_hash if user is not None else None,
        )

        # Inativo só é rejeitado depois da verificação, com custo similar.
        if user is None or not user.is_active or not matches:
            raise InvalidCredentialsError
        return user


def _is_email_unique_violation(error: IntegrityError) -> bool:
    # CHECK e outras falhas de integridade não são duplicidade de email.
    original = error.orig
    if not isinstance(original, UniqueViolation):
        return False
    return original.diag.constraint_name == _EMAIL_UNIQUE_CONSTRAINT
