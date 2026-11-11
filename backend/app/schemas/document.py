from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

# Paginação da listagem de documentos (reutilizada pela rota na etapa 3.5).
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100

# Deve espelhar app.models.document.DOCUMENT_STATUSES (há teste de paridade).
DocumentStatus = Literal["uploaded", "processing", "ready", "failed"]


class DocumentResponse(BaseModel):
    """Representação pública de um documento.

    O campo `metadata` é público: só pode conter informações que o cliente
    pode ver (ex.: detalhes de processamento). Dados internos não entram nele.
    """

    # Nota (fora do OpenAPI): este schema não tem a chave interna do storage.

    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
    filename: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    uploaded_by: int
    created_at: datetime
    # No ORM o atributo é `metadata_` (`metadata` é reservado no SQLAlchemy).
    metadata: dict[str, Any] = Field(
        validation_alias=AliasChoices("metadata_", "metadata")
    )


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int
