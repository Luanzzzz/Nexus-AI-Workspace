"""Dependencies do upload de documentos."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies.database import get_db
from app.core.config import settings
from app.services.document import DocumentService
from app.storage.local import LocalDocumentStorage


def get_document_storage() -> LocalDocumentStorage:
    # Testes trocam esta dependency por um storage em tmp_path.
    return LocalDocumentStorage(settings.document_storage_dir)


def get_document_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[LocalDocumentStorage, Depends(get_document_storage)],
) -> DocumentService:
    return DocumentService(session, storage)
