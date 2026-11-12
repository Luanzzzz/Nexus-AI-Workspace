"""Documento enviado a um workspace.

O blob vive no storage; esta tabela guarda só metadados e a chave interna
(`storage_key`), que nunca deve sair em respostas públicas.

FKs usam ON DELETE RESTRICT de propósito: apagar um workspace ou usuário com
documentos falharia em vez de remover as linhas e deixar blobs órfãos no disco.
A remoção de documentos (e de seus blobs) é um fluxo explícito da camada de
serviço, não um efeito colateral de cascata.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workspace import Workspace

DOCUMENT_STATUSES: tuple[str, ...] = ("uploaded", "processing", "ready", "failed")

_STATUS_CHECK_SQL = "status IN ({})".format(
    ", ".join(f"'{status}'" for status in DOCUMENT_STATUSES)
)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_documents_storage_key"),
        CheckConstraint(_STATUS_CHECK_SQL, name="ck_documents_status"),
        CheckConstraint("size_bytes >= 0", name="ck_documents_size_bytes_nonnegative"),
        # Suporta a listagem por workspace: created_at desc, id desc.
        Index(
            "ix_documents_workspace_id_created_at_id",
            "workspace_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey(
            "workspaces.id",
            name="fk_documents_workspace_id_workspaces",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    uploaded_by: Mapped[int] = mapped_column(
        ForeignKey(
            "users.id",
            name="fk_documents_uploaded_by_users",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    # Nome original informado pelo cliente (sanitizado antes de persistir).
    filename: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String,
        default="uploaded",
        server_default="uploaded",
        nullable=False,
    )
    # `metadata` é reservado pelo SQLAlchemy; o atributo Python leva "_".
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    # Chave interna do storage (gerada pelo servidor). Nunca expor.
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    workspace: Mapped[Workspace] = relationship(back_populates="documents")
    uploader: Mapped[User] = relationship(back_populates="uploaded_documents")
