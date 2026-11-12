# Contrato de workspaces

Fundação mínima de workspaces: criar, listar os acessíveis e consultar um. Todas as rotas exigem `Authorization: Bearer <access_token>` (ver [Usuários](users.md#usuário-atual)). Não há `PATCH`, `DELETE` nem rotas de membros nesta etapa.

O router só orquestra. `WorkspaceService.create_workspace` cria o `Workspace` e a `WorkspaceMember` do dono na mesma transação: um único `commit()` no sucesso, `rollback()` completo em qualquer falha (sem workspace órfão). Os repositórios (`WorkspaceRepository`, `WorkspaceMemberRepository`) usam a sessão recebida e nunca confirmam a transação. Ver [ADR 0001](../decisions/0001-unicidade-do-slug-de-workspace.md) e [ADR 0002](../decisions/0002-papel-de-workspace-member.md).

## WorkspaceCreate

Campos obrigatórios: `name` e `slug`. Campos extras são rejeitados com 422 (`extra="forbid"`), inclusive `owner_id` e `role`. O dono é sempre o usuário autenticado e o papel gravado é sempre `owner`; nada disso vem do cliente.

| Campo | Política |
| --- | --- |
| `name` | Mesma política do nome de usuário: espaços nas extremidades removidos, 1 a 150 caracteres, sem caracteres de controle. |
| `slug` | Minúsculas ASCII (`a-z`), números e hífens; 3 a 63 caracteres; sem hífen no início, no fim ou duplo (`^[a-z0-9]+(?:-[a-z0-9]+)*$`). Não há normalização: `Meu-Time` é rejeitado, não convertido. |

O slug é único globalmente (`UNIQUE(slug)`). A consulta prévia evita o caso comum; a corrida entre duas requisições é decidida pela UNIQUE do banco, e o `IntegrityError` vira 409.

## WorkspaceResponse

Campos públicos: `id`, `name`, `slug`, `owner_id`, `created_at` e `updated_at`.

## Endpoints

### `POST /api/v1/workspaces`

Cria o workspace e a membership `owner` do usuário autenticado.

| Status | Quando | Corpo |
| --- | --- | --- |
| 201 | Criado | `WorkspaceResponse` |
| 401 | Token ausente ou inválido | `{"detail": "Não autenticado."}` |
| 403 | Usuário já é dono do máximo de workspaces (padrão 10) | `{"detail": "Limite de workspaces atingido."}` |
| 409 | Slug já existe (inclusive sob concorrência) | `{"detail": "Slug indisponível."}` |
| 429 | Rate limit de criação por usuário (padrão 10/hora) | `{"detail": "Muitas tentativas. Tente novamente mais tarde."}` com `Retry-After` |
| 422 | Corpo inválido, slug fora do formato ou campo extra | `detail` com `loc`, `type` e `msg`, sem `input` |
| 500 | Falha interna | `{"detail": "Erro interno do servidor."}` |

A mensagem do 409 é genérica e não ecoa o slug. O 403 usa corpo distinto do 403 de permissão. O rate limit é em memória e por processo (ver ADR 0008).

### `GET /api/v1/workspaces`

Lista somente os workspaces em que o usuário tem membership, em qualquer papel, ordenados por `id`. Workspaces de terceiros nunca aparecem. 200 com `list[WorkspaceResponse]` (vazia se não houver nenhum); 401 sem token válido.

### `GET /api/v1/workspaces/{workspace_id}`

`workspace_id` é inteiro de 1 a 2147483647; fora disso, 422.

| Status | Quando |
| --- | --- |
| 200 | Usuário é membro (owner, admin, member ou viewer) |
| 401 | Token ausente ou inválido |
| 404 | Workspace inexistente **ou** usuário sem membership (mesma resposta: `{"detail": "Workspace não encontrado."}`) |

## Autorização reutilizável

`app/api/dependencies/workspace.py` expõe `get_workspace_membership` (resolve a membership de `workspace_id` + usuário atual; 404 se ausente) e `require_permission(permission)` (404 sem membership, 403 `{"detail": "Permissão insuficiente."}` para membro sem a permissão). Permissão desconhecida nega por padrão.

| Permissão | owner | admin | member | viewer |
| --- | --- | --- | --- | --- |
| `workspace:read` (ler workspace, listar e consultar documentos) | sim | sim | sim | sim |
| `document:upload` | sim | sim | não | não |
| `document:delete` | sim | sim | não | não |

Exemplo de uso numa rota: `Depends(require_permission(UPLOAD_DOCUMENT))`.

## Limites

- Sem rate limit nas rotas de workspace.
- Quem cria o workspace é sempre `owner`; não há convite nem alteração de papéis nesta etapa.
- Um usuário pode criar vários workspaces; não há cota.
