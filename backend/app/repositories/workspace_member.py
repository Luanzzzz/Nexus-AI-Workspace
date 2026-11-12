from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace_member import WorkspaceMember


class WorkspaceMemberRepository:
    # A sessão vem de fora; este repositório nunca chama commit() nem rollback().
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_membership(
        self, workspace_id: int, user_id: int
    ) -> WorkspaceMember | None:
        # UNIQUE(workspace_id, user_id) garante no máximo uma linha.
        statement = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def create(
        self, *, workspace_id: int, user_id: int, role: str
    ) -> WorkspaceMember:
        # O papel é definido pelo servidor; o CHECK do banco valida o valor.
        member = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
        self.session.add(member)
        await self.session.flush()
        return member
