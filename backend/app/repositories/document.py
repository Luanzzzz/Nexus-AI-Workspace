from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document


class DocumentRepository:
    # A sessão vem de fora; este repositório nunca chama commit() nem rollback().
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        workspace_id: int,
        uploaded_by: int,
        filename: str,
        mime_type: str,
        size_bytes: int,
        storage_key: str,
    ) -> Document:
        document = Document(
            workspace_id=workspace_id,
            uploaded_by=uploaded_by,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            storage_key=storage_key,
            status="uploaded",
            metadata_={},
        )
        self.session.add(document)
        await self.session.flush()
        return document

    # Toda consulta abaixo filtra por workspace_id E (quando aplicável) por id:
    # nunca há busca só por document_id.

    async def list_by_workspace(
        self, workspace_id: int, limit: int, offset: int
    ) -> list[Document]:
        result = await self.session.scalars(
            select(Document)
            .where(Document.workspace_id == workspace_id)
            .order_by(Document.created_at.desc(), Document.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def count_by_workspace(self, workspace_id: int) -> int:
        total = await self.session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.workspace_id == workspace_id)
        )
        return int(total or 0)

    async def usage_by_workspace(self, workspace_id: int) -> tuple[int, int]:
        # (quantidade de documentos, soma de size_bytes) só deste workspace.
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(Document.size_bytes), 0),
                ).where(Document.workspace_id == workspace_id)
            )
        ).one()
        return int(row[0]), int(row[1])

    async def get_in_workspace(
        self, workspace_id: int, document_id: int
    ) -> Document | None:
        return await self.session.scalar(
            select(Document).where(
                Document.workspace_id == workspace_id,
                Document.id == document_id,
            )
        )

    async def delete(self, document: Document) -> None:
        # Só remove a linha (flush); o commit é do serviço.
        await self.session.delete(document)
        await self.session.flush()
