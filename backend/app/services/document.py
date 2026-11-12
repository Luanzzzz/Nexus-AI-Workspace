"""Caso de uso de upload de documento.

Postgres e filesystem não compartilham transação: o blob é gravado primeiro
(temporário + os.replace), depois a linha é criada e confirmada. Se qualquer
passo após o blob falhar, há rollback e o blob é removido (limpeza
compensatória). Um crash entre os dois passos ainda pode deixar blob órfão
(reconciliação futura, ADR 0009).

Logs levam só request_id e o tipo da exceção: nada de caminho, chave ou nome.
"""

import asyncio
import logging

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DocumentUploadError, StorageError
from app.core.logging import request_id_ctx
from app.models.document import Document
from app.models.user import User
from app.repositories.document import DocumentRepository
from app.services.document_validation import (
    MAX_UPLOAD_BYTES,
    resolve_mime_type,
    sanitize_filename,
    validated_chunks,
)
from app.storage.local import LocalDocumentStorage

logger = logging.getLogger(__name__)


class DocumentService:
    def __init__(self, session: AsyncSession, storage: LocalDocumentStorage) -> None:
        self.session = session
        self.storage = storage
        self.documents = DocumentRepository(session)

    async def upload_document(
        self, *, workspace_id: int, user: User, upload: UploadFile
    ) -> Document:
        # Erros de validação (415/422/413) sobem como estão: nada foi persistido.
        filename = sanitize_filename(upload.filename)
        mime_type = resolve_mime_type(filename, upload.content_type)
        chunks = validated_chunks(upload.read, mime_type)
        try:
            stored = await self.storage.save(chunks, max_bytes=MAX_UPLOAD_BYTES)
        except (OSError, StorageError) as exc:
            self._log_failure("storage", exc)
            raise DocumentUploadError from None
        finally:
            await chunks.aclose()

        try:
            document = await self.documents.create(
                workspace_id=workspace_id,
                uploaded_by=user.id,
                filename=filename,
                mime_type=mime_type,
                size_bytes=stored.size,
                storage_key=stored.key,
            )
            await self.session.commit()
        except BaseException as exc:
            await self._compensate(stored.key)
            if not isinstance(exc, Exception):
                raise
            self._log_failure("database", exc)
            raise DocumentUploadError from None
        return document

    async def _compensate(self, key: str) -> None:
        try:
            await asyncio.shield(self.session.rollback())
        except Exception as exc:
            self._log_failure("rollback", exc)
        try:
            await asyncio.to_thread(self.storage.delete, key)
        except Exception as exc:
            # Blob órfão: fica para reconciliação futura.
            self._log_failure("cleanup", exc)

    @staticmethod
    def _log_failure(stage: str, exc: BaseException) -> None:
        logger.error(
            "Falha no upload de documento stage=%s request_id=%s type=%s",
            stage,
            request_id_ctx.get("-"),
            type(exc).__name__,
        )
