"""Caso de uso de cadastro.

O SQLAlchemy 2 abre a transação sozinho na primeira consulta (autobegin).
Este serviço não chama session.begin(): depois do get_by_email a transação
já está ativa, e um begin() nessa hora falharia. O fim da transação é
commit() no sucesso ou rollback() na duplicidade e em qualquer falha.
"""

import asyncio

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateEmailError
from app.core.security import hash_password
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import UserRegister

# Nome que o PostgreSQL deu ao UNIQUE(email) na migration inicial.
_EMAIL_UNIQUE_CONSTRAINT = "users_email_key"


class AuthService:
    # A sessão vem de fora. O repositório só usa essa mesma sessão.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def register(self, data: UserRegister) -> User:
        # O schema também baixa a caixa. O caso de uso repete, porque o
        # repositório compara o email exatamente como recebe.
        email = data.email.lower()

        existing = await self.users.get_by_email(email)
        if existing is not None:
            # A consulta já abriu a transação. Não há escrita para confirmar.
            await self.session.rollback()
            raise DuplicateEmailError

        try:
            # Argon2id é síncrono e lento; a thread libera o event loop.
            # A transação aberta pela consulta continua até o commit.
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


def _is_email_unique_violation(error: IntegrityError) -> bool:
    # CHECK e outras falhas de integridade não são duplicidade de email.
    original = error.orig
    if not isinstance(original, UniqueViolation):
        return False
    return original.diag.constraint_name == _EMAIL_UNIQUE_CONSTRAINT
