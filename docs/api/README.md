# API

Documentação da API HTTP.

- [Usuários](users.md) — `POST /api/v1/auth/register`, `UserRegister` e `UserResponse`. `POST /api/v1/auth/login` e `TokenResponse`. `GET /api/v1/auth/me` (usuário atual, Bearer).
- [Workspaces](workspaces.md) — `POST/GET /api/v1/workspaces`, `GET /api/v1/workspaces/{workspace_id}`, `WorkspaceCreate`, `WorkspaceResponse` e a matriz de permissões.
- [Documentos](documents.md) — `POST /api/v1/workspaces/{workspace_id}/documents` (upload multipart, validações e códigos de erro), `GET` de listagem paginada e de documento, `DELETE`, reconciliação de blobs órfãos e política de falhas parciais.

Contratos das demais rotas serão adicionados quando elas existirem.
