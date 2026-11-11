"""Schemas de documento, sem PostgreSQL."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.document import DOCUMENT_STATUSES
from app.schemas.document import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    DocumentListResponse,
    DocumentResponse,
)

SECRET_KEY = "ab12cd34-segredo-interno"


def _orm_like(**overrides):
    data = {
        "id": 1,
        "workspace_id": 2,
        "filename": "a.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 10,
        "status": "uploaded",
        "uploaded_by": 3,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "metadata_": {"pages": 2},
        "storage_key": SECRET_KEY,
        # Imita o atributo reservado `metadata` do SQLAlchemy.
        "metadata": object(),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_from_orm_uses_metadata_underscore_and_serializes_metadata_key():
    doc = DocumentResponse.model_validate(_orm_like())
    dumped = doc.model_dump(mode="json")
    assert dumped["metadata"] == {"pages": 2}
    assert "metadata_" not in dumped
    assert '"metadata":{"pages":2}' in doc.model_dump_json()


def test_accepts_public_metadata_key_from_dict():
    data = {
        k: v
        for k, v in vars(_orm_like()).items()
        if k not in ("metadata_", "storage_key")
    }
    data["metadata"] = {"x": 1}
    assert DocumentResponse.model_validate(data).metadata == {"x": 1}


def test_storage_key_never_serialized():
    doc = DocumentResponse.model_validate(_orm_like())
    assert "storage_key" not in doc.model_dump()
    assert SECRET_KEY not in doc.model_dump_json()
    assert "storage_key" not in DocumentResponse.model_fields


def test_storage_key_absent_from_openapi_schemas():
    for model in (DocumentResponse, DocumentListResponse):
        for mode in ("validation", "serialization"):
            schema = str(
                model.model_json_schema(mode=mode, ref_template="#/$defs/{model}")
            )
            assert "storage" not in schema
            assert "path" not in schema.lower()


def test_openapi_serialization_property_is_metadata():
    props = DocumentResponse.model_json_schema(mode="serialization")["properties"]
    assert "metadata" in props
    assert "metadata_" not in props


def test_invalid_status_rejected():
    with pytest.raises(ValidationError):
        DocumentResponse.model_validate(_orm_like(status="deleted"))


def test_status_literal_matches_model_constant():
    from typing import get_args

    from app.schemas.document import DocumentStatus

    assert get_args(DocumentStatus) == DOCUMENT_STATUSES


def test_list_response_shape():
    item = DocumentResponse.model_validate(_orm_like())
    resp = DocumentListResponse(items=[item], total=1, limit=20, offset=0)
    dumped = resp.model_dump(mode="json")
    assert set(dumped) == {"items", "total", "limit", "offset"}
    assert dumped["items"][0]["metadata"] == {"pages": 2}
    assert "storage_key" not in dumped["items"][0]


def test_pagination_constants():
    assert DEFAULT_PAGE_LIMIT == 20
    assert MAX_PAGE_LIMIT == 100
