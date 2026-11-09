from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    # A sessão vem de fora para o mesmo caso de uso poder reutilizá-la.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        # Consulta única pela PK; sem commit, rollback ou consultas extras.
        # Não filtra is_active: quem decide se a conta pode agir é o chamador.
        statement = select(User).where(User.id == user_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        # O email já chega canonicalizado; esta consulta não altera a caixa.
        statement = select(User).where(User.email == email)
        result = await self.session.execute(statement)
        # Uma linha vira User; nenhuma vira None. Mais de uma linha é erro.
        return result.scalar_one_or_none()

    async def create_user(
        self,
        *,
        name: str,
        email: str,
        password_hash: str,
    ) -> User:
        # Dados internos já prontos: sem senha em claro e sem hash neste método.
        # is_active não vem do cliente; o default True do model entra no INSERT.
        user = User(name=name, email=email, password_hash=password_hash)
        self.session.add(user)
        # flush pede o id ao banco e deixa o commit para o serviço.
        await self.session.flush()
        return user
