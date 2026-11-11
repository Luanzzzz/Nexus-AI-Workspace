# ADR 0008: criação de workspace e autorização por papel

## Problema

A Fase 3 introduz workspaces como fronteira multi-tenant. Era preciso decidir como o workspace nasce (sem estado órfão), quem define dono e papel, qual é a política do slug, quem pode fazer o quê dentro de um workspace e como as respostas negadas evitam revelar a existência de recursos de outros tenants.

## Opções

- Criar workspace e membership do dono em transações separadas, ou na mesma transação.
- Aceitar `owner_id` e `role` no payload, ou derivá-los do usuário autenticado.
- Normalizar o slug (minúsculas, troca de caracteres) ou validá-lo sem alterar o valor; decidir a unicidade na aplicação ou no banco.
- Responder 403 para qualquer acesso negado, ou 404 quando o usuário não tem vínculo com o workspace.

## Decisão

- **Criação atômica.** `WorkspaceService.create_workspace` cria o `Workspace` e a `WorkspaceMember` com papel `owner` na mesma transação, com um único `commit()` no sucesso e `rollback()` em qualquer falha. Os repositórios usam a sessão recebida e nunca confirmam. Não existe workspace sem dono.
- **Dono e papel só vêm do servidor.** `WorkspaceCreate` usa `extra="forbid"`: `owner_id`, `role` ou qualquer campo extra gera 422. O dono é o usuário autenticado e o papel gravado é sempre `owner`.
- **Política do slug.** Regex `^[a-z0-9]+(?:-[a-z0-9]+)*$`, de 3 a 63 caracteres, **sem normalização** (`Meu-Time` é rejeitado com 422, não convertido). A unicidade é global (ADR 0001) e quem decide é o `UNIQUE(slug)` do banco. Há uma consulta prévia só para o caminho comum; na corrida, o `IntegrityError` da constraint `workspaces_slug_key` vira `DuplicateSlugError`. Outras violações de integridade (FK, CHECK) não são tratadas como slug duplicado e seguem como erro. A resposta é 409 genérica (`"Slug indisponível."`), sem ecoar o slug.
- **Matriz de papéis e permissões** (proposta operacional do MVP, não um RBAC completo):

  | Permissão | owner | admin | member | viewer |
  | --- | --- | --- | --- | --- |
  | `workspace:read` (workspace, listar e ler documentos) | sim | sim | sim | sim |
  | `document:upload` | sim | sim | não | não |
  | `document:delete` | sim | sim | não | não |

  A matriz está em `app/api/dependencies/workspace.py` (`PERMISSIONS`). Permissão desconhecida nega por padrão. Os papéis vêm do ADR 0002.
- **404 versus 403.** Usuário sem membership e workspace inexistente recebem o **mesmo** 404 (`"Workspace não encontrado."`), para não revelar a existência de workspaces alheios. Quem é membro mas não tem a permissão recebe 403 (`"Permissão insuficiente."`). Documento inexistente e documento de outro workspace também recebem o mesmo 404. A autorização roda como dependency, antes de qualquer escrita no storage ou no banco; o corpo multipart, porém, é lido (e, acima de 1 MiB, gravado em arquivo temporário pelo Starlette) **antes** da autenticação, limitado a 10 MiB mais folga na rota de upload (ver ADR 0009).
- **Limites dos ids de path.** `workspace_id` e `document_id` aceitam 1 a 2147483647 (INTEGER do PostgreSQL); fora da faixa vira 422, não erro de banco.

## Trade-offs

- A matriz é uma proposta do MVP: um `member` hoje só lê. Ampliar permissões exige mudar `PERMISSIONS` e os testes de matriz.
- O 404 uniforme dificulta a depuração de quem esqueceu de ser adicionado ao workspace; é o preço de não vazar existência.
- O 409 do slug confirma que o slug já existe (enumeração de slugs). O slug é um identificador de baixa sensibilidade e a resposta não vaza dados do workspace.
- A consulta prévia do slug e o `UNIQUE` dão duas rotas para o mesmo 409; só a constraint garante unicidade.

## Fora de escopo (adiado)

- `PATCH` e `DELETE` de workspace.
- Endpoints de administração de membros (convite, troca de papel, remoção). Hoje memberships além do dono só entram por repositório/banco.
- Rate limit nas rotas de workspace e documentos (só login e cadastro têm limite, ADR 0007).
