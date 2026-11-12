from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import Workspace
from app.models.workspace_member import WorkspaceMember


class WorkspaceRepository:
    # A sessão vem de fora; este repositório nunca chama commit() nem rollback().
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, workspace_id: int) -> Workspace | None:
        statement = select(Workspace).where(Workspace.id == workspace_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def lock_for_update(self, workspace_id: int) -> bool:
        # Serializa as escritas de cota do workspace até o commit/rollback do
        # chamador. False se o workspace não existe mais.
        found = await self.session.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id).with_for_update()
        )
        return found is not None

    async def count_owned_by(self, user_id: int) -> int:
        total = await self.session.scalar(
            select(func.count())
            .select_from(Workspace)
            .where(Workspace.owner_id == user_id)
        )
        return int(total or 0)

    async def get_by_slug(self, slug: str) -> Workspace | None:
        statement = select(Workspace).where(Workspace.slug == slug)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def create(self, *, name: str, slug: str, owner_id: int) -> Workspace:
        # owner_id vem do usuário autenticado, nunca do payload.
        workspace = Workspace(name=name, slug=slug, owner_id=owner_id)
        self.session.add(workspace)
        # flush pede o id ao banco (e dispara a UNIQUE do slug); o commit é do serviço.
        await self.session.flush()
        return workspace

    async def list_by_user(self, user_id: int) -> list[Workspace]:
        # Só workspaces em que o usuário tem membership; ordem estável por id.
        statement = (
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(Workspace.id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())
