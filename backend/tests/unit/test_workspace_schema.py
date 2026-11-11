"""Schemas de workspace e matriz de permissões, sem PostgreSQL."""

import pytest
from pydantic import ValidationError

from app.api.dependencies.workspace import (
    DELETE_DOCUMENT,
    READ,
    UPLOAD_DOCUMENT,
    role_has_permission,
)
from app.schemas.workspace import WorkspaceCreate


@pytest.mark.parametrize("slug", ["abc", "meu-workspace", "a1-b2-c3", "x" * 63])
def test_slug_valido(slug):
    assert WorkspaceCreate(name="Time", slug=slug).slug == slug


@pytest.mark.parametrize(
    "slug",
    [
        "ab",
        "x" * 64,
        "-abc",
        "abc-",
        "a--b",
        "Abc",
        "a_b_c",
        "a b c",
        "ação",
        "abc\n",
        "",
    ],
)
def test_slug_invalido(slug):
    with pytest.raises(ValidationError):
        WorkspaceCreate(name="Time", slug=slug)


@pytest.mark.parametrize("extra", ["owner_id", "role", "id"])
def test_campos_extras_sao_rejeitados(extra):
    with pytest.raises(ValidationError) as info:
        WorkspaceCreate.model_validate({"name": "Time", "slug": "time", extra: 1})
    assert info.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("name", ["", "   ", "a\u0000b"])
def test_nome_invalido(name):
    with pytest.raises(ValidationError):
        WorkspaceCreate(name=name, slug="time")


def test_matriz_de_permissoes():
    for role in ("owner", "admin", "member", "viewer"):
        assert role_has_permission(role, READ)
    for permission in (UPLOAD_DOCUMENT, DELETE_DOCUMENT):
        assert role_has_permission("owner", permission)
        assert role_has_permission("admin", permission)
        assert not role_has_permission("member", permission)
        assert not role_has_permission("viewer", permission)


def test_permissao_desconhecida_ou_papel_desconhecido_nega():
    assert not role_has_permission("owner", "inexistente")
    assert not role_has_permission("root", READ)
