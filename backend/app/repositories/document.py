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
