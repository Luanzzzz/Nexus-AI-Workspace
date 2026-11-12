"""Caso de uso de criação de workspace.

Workspace e membership do dono nascem na mesma transação: um único commit
no sucesso, rollback completo em qualquer falha (sem workspace órfão).
Ver docs/decisions/0001 (slug único) e 0002 (papéis).
"""

from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import DuplicateSlugError, WorkspaceLimitExceededError
from app.models.user import User
from app.models.workspace import Workspace
from app.repositories.user import UserRepository
from app.repositories.workspace import WorkspaceRepository
from app.repositories.workspace_member import WorkspaceMemberRepository
from app.schemas.workspace import WorkspaceCreate

# Nome que o PostgreSQL deu ao UNIQUE(slug) na migration.
_SLUG_UNIQUE_CONSTRAINT = "workspaces_slug_key"
OWNER_ROLE = "owner"
# Teto de espera pelo FOR NO KEY UPDATE da linha do usuário (limite de workspaces).
OWNER_LOCK_TIMEOUT_MS = 5000


class WorkspaceService:
    # A sessão vem de fora. Os repositórios usam essa mesma sessão.
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workspaces = WorkspaceRepository(session)
        self.members = WorkspaceMemberRepository(session)

    async def create_workspace(self, data: WorkspaceCreate, owner: User) -> Workspace:
        try:
            # Limite de workspaces por dono. A linha do usuário é bloqueada
            # FOR NO KEY UPDATE: criações concorrentes do MESMO usuário se serializam e
            # a contagem, lida depois do lock, vê o que já confirmou. Sem corrida
            # além do teto exato.
            await UserRepository(self.session).lock_for_update(
                owner.id, lock_timeout_ms=OWNER_LOCK_TIMEOUT_MS
            )
            if (
                await self.workspaces.count_owned_by(owner.id)
                >= settings.workspace_max_owned_per_user
            ):
                raise WorkspaceLimitExceededError

            # Consulta prévia só evita o caminho comum; a UNIQUE decide na corrida.
            if await self.workspaces.get_by_slug(data.slug) is not None:
                await self.session.rollback()
                raise DuplicateSlugError

            # owner_id e papel vêm do servidor, nunca do payload.
            workspace = await self.workspaces.create(
                name=data.name,
                slug=data.slug,
                owner_id=owner.id,
            )
            await self.members.create(
                workspace_id=workspace.id,
                user_id=owner.id,
                role=OWNER_ROLE,
            )
            await self.session.commit()
        except DuplicateSlugError:
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            if _is_slug_unique_violation(exc):
                raise DuplicateSlugError from exc
            raise
        except Exception:
            await self.session.rollback()
            raise

        return workspace


def _is_slug_unique_violation(error: IntegrityError) -> bool:
    # FK, CHECK e outras falhas de integridade não são slug duplicado.
    original = error.orig
    if not isinstance(original, UniqueViolation):
        return False
    return original.diag.constraint_name == _SLUG_UNIQUE_CONSTRAINT
