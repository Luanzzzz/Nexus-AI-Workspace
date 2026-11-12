"""Matriz de papéis e permissões por workspace (sem dependência de HTTP)."""

READ = "workspace:read"
UPLOAD_DOCUMENT = "document:upload"
DELETE_DOCUMENT = "document:delete"

# Matriz de permissões (ver spec da Fase 3): leitura para todos os papéis;
# subir e excluir documento só para owner e admin.
_ALL_ROLES = frozenset({"owner", "admin", "member", "viewer"})
_MANAGERS = frozenset({"owner", "admin"})
PERMISSIONS: dict[str, frozenset[str]] = {
    READ: _ALL_ROLES,
    UPLOAD_DOCUMENT: _MANAGERS,
    DELETE_DOCUMENT: _MANAGERS,
}


def role_has_permission(role: str, permission: str) -> bool:
    # Permissão desconhecida nega por padrão.
    return role in PERMISSIONS.get(permission, frozenset())
