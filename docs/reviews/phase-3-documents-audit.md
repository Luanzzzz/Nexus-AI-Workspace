# Auditoria final da Fase 3 (Documents) — Etapa 3.8

## 1. Veredito

**Aprovada com ressalvas para o escopo da fase (estudo local de Documents).** Nenhum achado Crítico. A autorização multi-tenant, a validação de arquivos, a segurança de caminho do storage e a consistência SQL/filesystem se sustentaram em leitura de código, 38 mutações dirigidas e probes de execução. O que sobra são riscos de **disponibilidade** (DoS) e de **documentação**, não de vazamento entre tenants.

Pontos que o dono deve ver antes do merge:

- **F01 (Alto):** o corpo multipart (inclusive chunked, sem teto) é gravado em disco **antes** da autenticação. Está divulgado no ADR 0009, mas o ADR 0008 afirma o contrário (F02).
- **F02 (Médio):** o ADR 0008 afirma que a autorização roda "antes de qualquer ... leitura de corpo"; medi 200 MiB lidos antes do 401.
- **F03 (Médio):** a conexão do pool fica presa durante todo o I/O de arquivo do upload.

Bloqueantes para o **merge da fase**: nenhum achado exige alteração de código. Recomendo corrigir **F02** (texto do ADR, trivial) antes do merge e registrar a **aceitação explícita** de F01/F03/F04 pelo dono (seção 9). Para **exposição pública**, F01, F03 e F04 passam a bloqueantes, junto com os residuais da Fase 2.

## 2. Escopo e método

- Branch `feat/phase3-e-hardening-audit`, 6 commits sobre `main` (`aa01e77` .. `817b672`): A fundação de workspace, B modelo, C storage/upload, D consultas/exclusão, E testes e ADRs. 49 arquivos, +4594 linhas.
- Auditor independente: não escrevi nem alterei código, testes ou ADRs. O único artefato é este arquivo.
- Lido na íntegra: `storage/local.py`, `services/document*.py`, `services/workspace.py`, repositórios, dependencies, rotas, schemas, handlers, migration, modelo, ADRs 0008/0009, `docs/api/*`, README, workflow de CI e a lista de testes.
- **Mutação**: 38 mutações aplicadas no repositório e revertidas com `git checkout -- <arquivo>` logo após a suíte completa (`git status` limpo ao final). 34 foram mortas pela suíte; 1 é equivalente (M15); 3 sobreviveram (M20 e M35, ver F05; M37, `list_blobs` sem checar o shard, inócua porque `delete()` não acharia o arquivo).
- **Probes** (scripts só no scratchpad): spool pré-autenticação, conexão do pool durante o upload, cancelamento do `save()`, permissões do storage, sanitização de nomes unicode, round-trip `alembic downgrade -1`/`upgrade head`.
- **Não inspecionado — requer revisão humana:** `.env.example` e `backend/.env.example` (3 e 4 linhas alteradas segundo `git diff --stat`; leitura vedada por permissão).

### Validação (raiz, `.venv/bin/python`)

| Comando | Resultado |
| --- | --- |
| `ruff check .` / `ruff format --check .` | `All checks passed!` / `147 files already formatted` |
| `POSTGRES_PORT=1 POSTGRES_DB=nexus_ai_test pytest -m "not integration" -q` | **299 passed**, 183 deselected |
| `POSTGRES_DB=nexus_ai_test pytest -q` | **482 passed**, 1 warning (deprecação do `httpx` no TestClient) |
| `POSTGRES_DB=nexus_ai_test alembic check` | `No new upgrade operations detected.` Round-trip downgrade/upgrade ok, head `845eb9180446` |
| `gh pr checks 2,3,4,5` | `test` e `unit` **pass** nos quatro PRs |

Ressalva: o CI usa Python 3.12 e a máquina local 3.14; ambos passam.

## 3. Achados

| ID | Severidade | Achado | Evidência | Impacto | Correção recomendada |
| --- | --- | --- | --- | --- | --- |
| F01 | **Alto** | Multipart é lido e gravado (spool em disco acima de 1 MiB) **antes** da autenticação; corpos chunked não têm teto. O guarda só atua com `Content-Length` declarado. | `backend/app/api/v1/documents.py:116-136`; FastAPI 0.162 `routing.py:455` (`request.form()` antes de `solve_dependencies`). Probe: não autenticado, 5 MiB com `Content-Length` → 401 após 5 242 880 bytes gravados; chunked de **200 MiB** → 401 após 209 715 200 bytes gravados | DoS de disco/CPU/tempo por qualquer cliente anônimo; o limite de 10 MiB não protege a rota. Divulgado no ADR 0009 (trade-offs) | Middleware ASGI que conta bytes do corpo e responde 413 mesmo sem `Content-Length` (ou exigir 411 na rota), e/ou limite no proxy. Decisão do dono (seção 9) |
| F02 | **Médio** | ADR 0008 afirma que a autorização roda "antes de qualquer escrita ou leitura de corpo da rota". É falso para a leitura de corpo e contradiz o ADR 0009. | `docs/decisions/0008-workspace-bootstrap-and-authorization.md`, item "404 versus 403"; medição de F01 | Garantia de segurança documentada que não existe | Trocar por "antes de qualquer escrita no storage; o corpo multipart é lido antes (ver ADR 0009)" |
| F03 | **Médio** | A sessão abre transação nas dependencies de auth (`get_current_user`, membership) e só a encerra no `commit`/`rollback`; o `storage.save()` (até 10 MiB, com `fsync`) roda com a conexão do pool presa. | `backend/app/services/document.py:51-57`. Probe: `engine.pool.checkedout() == 1` dentro de `save()` | Com pool 5+10 (`config.py:122-123`), ~15 uploads lentos concorrentes esgotam o pool e derrubam todas as rotas (mesma classe do A3 da Fase 2) | Encerrar a transação de leitura (`await session.commit()` ou `rollback()`; `expire_on_commit=False`) antes do `save()`, com teste de pool `pool_size=1` como em `test_auth_connection_release.py` |
| F04 | **Médio** | Sem cota nem rate limit: cadastro aberto, qualquer usuário cria workspaces ilimitados e, sendo `owner`, sobe documentos ilimitados. | `docs/api/workspaces.md` (Limites), ADR 0008 (fora de escopo); `api/v1/workspaces.py:199-211` | Esgotamento de disco por conta autenticada | Cota por workspace/usuário (bytes e documentos) e rate limit nas rotas; aceitar explicitamente para o MVP |
| F05 | Baixo | Testes que passariam sem a proteção: (a) `test_declared_content_length_far_over_limit_is_rejected_early` só confere 413 e `_blobs == []`; sem o guarda de `Content-Length` (M20) o limite do storage devolve o mesmo resultado; (b) M35: `list_blobs` com `is_file()` seguindo symlink não é pego (a segunda camada, `delete()` com `S_ISREG`, mascara). | `tests/test_document_upload_api.py:266-277`; `storage/local.py:246-252` | O guarda de F01 e a varredura sem symlink não têm teste dedicado | (a) Espionar `storage.save` e afirmar que não foi chamado/que o corpo não foi lido; (b) teste de `list_blobs` com symlink para fora do root |
| F06 | Baixo | Cancelamento do request pode vazar descritores e `.part`: se a task é cancelada durante `to_thread(self._start, ...)`, a tupla `(root_fd, tmp_fd, fd)` nunca é atribuída e os fds/arquivo ficam sem dono; em `_write_all`, o `except` fecha `fd` enquanto a thread ainda escreve (risco de reuso do número do fd). Não reproduzido (janela estreita), só por leitura. | `storage/local.py:96-97,103-111,121-146` | Vazamento lento de fds; escrita num fd reaproveitado em caso extremo | Abrir os fds dentro de `asyncio.shield` ou tornar a thread dona da limpeza; reconciliação já recolhe `.part` e blob publicado |
| F07 | Baixo | OpenAPI não declara 401/403/404 nos endpoints de documentos e workspace (upload só 413/415/422; list sem 404; `GET /workspaces/{id}` sem 404). Spec 3.2: "OpenAPI documenta". | `api/v1/documents.py:158-167,183`; `api/v1/workspaces.py:223` | Contrato público incompleto; o `docs/api` está correto | Declarar `responses` (401/403/404) ou um helper comum |
| F08 | Baixo | Sanitização de nome: U+2028 (Zl), NBSP e variation selectors passam; só NFC, sem NFKC/confusáveis (`ＮＯＴＥ.md` mantido); limite de 255 é em caracteres, não bytes. Probe confirmou. O nome é só exibição, nunca caminho. | `services/document_validation.py:325-344` | Spoofing visual em UI futura; sem efeito no disco | Incluir Zl/Zp e espaços exóticos em `_DROP`; decidir NFKC (residual QA10 da Fase 2) |
| F09 | Baixo | `reconcile_orphans` aceita `min_age_seconds=0` ou negativo; com `dry_run=False` isso removeria blob publicado cuja linha ainda não foi confirmada, deixando a linha apontando para nada. O padrão (1 h) é seguro e o mtime reflete a última escrita. Sem CLI nem agendador. | `services/document_reconciliation.py:202-225,242-250` | Só por chamada manual errada; órfãos se acumulam até alguém executar | Piso mínimo de idade (ex.: 5 min) com erro explícito; CLI/agendamento na Fase 4 |
| F10 | Informativo | Exclusões concorrentes do mesmo documento: ambas leem a linha, a segunda apaga 0 linhas (aviso do SQLAlchemy) e responde 204 em vez de 404; benigno (idempotente), não reproduzido. | `services/document.py:98-113` | Nenhum dado exposto | Opcional: tratar `rowcount == 0` como 404 |
| F11 | Informativo | Os testes de API usam sessão com `join_transaction_mode="create_savepoint"`: `commit`/`rollback` reais, liberação de conexão e concorrência de upload/delete não são exercitados; falhas de commit são simuladas. | `tests/test_document_upload_api.py:44-56` | Explica por que F03 passou despercebido | Um teste sem savepoint (como em `test_auth_connection_release.py`) |
| F12 | Informativo | Reconciliação só cobre blob sem linha. Linha sem blob (restauração parcial de backup) não é detectada. PDF só confere `%PDF-` (polyglot aceito) e TXT aceita controles além de NUL; ambos divulgados. | ADR 0009; `document_validation.py:371-387` | Aceito no MVP | Fase 4: validação estrutural de PDF; checagem inversa na reconciliação |
| F13 | Informativo | `uploaded_by` e `owner_id` (inteiros sequenciais) são expostos a qualquer papel, inclusive `viewer`; sem índice em `documents.uploaded_by` (FK RESTRICT). Root pré-existente com 0755 não é endurecido (blobs 0600, shards 0700 verificados). Código depende de `dir_fd`/`O_NOFOLLOW` (POSIX). | `schemas/document.py`, `schemas/workspace.py:166-173`; probe de permissões | Sem vazamento entre tenants (IDOR bloqueado por workspace) | Decisão de produto sobre ids públicos; documentar "POSIX only" |
| F14 | Informativo | 409 de slug confirma a existência de slugs de outros tenants (enumeração). Documentado no ADR 0008. | `services/workspace.py:34-37` | Baixo | Aceito; ver seção 9 |

## 4. Verificações sem achado (resumo)

- **Arquitetura:** router orquestra, service decide, repositório só SQL; nenhum repositório chama `commit()`; sem `Protocol`/camadas fictícias; `_BoundedUploadRoute` é a única abstração extra e se justifica.
- **Multi-tenant (BOLA/IDOR):** todas as 7 rotas passam por `require_permission`; `workspace_id` usado nos serviços vem de `membership.workspace_id`, não do path; toda consulta de `DocumentRepository` filtra por `workspace_id`. Mutações M01-M03 (remover o filtro) e M04-M06 (matriz, 404→403) foram **mortas**. 404 idêntico para workspace inexistente e sem membership, e para documento inexistente e de outro workspace; corpos sem metadado.
- **SQL x filesystem:** ordem upload = blob, linha, commit, compensação em falha (M14 morta); delete = linha, commit, blob (M21 morta). Janelas de crash: entre o blob e o commit (órfão) e entre o commit e o `unlink` do delete (órfão); ambas recuperáveis pela reconciliação. A reconciliação **nunca remove blob com linha** (M07 morta), só considera blobs com mais de 1 h (M08 morta), só age sobre arquivo regular com nome de chave válido e nunca sai do root (varredura por `dir_fd` + `O_NOFOLLOW`; M36 morta). Upload em andamento não é confundido com órfão pela regra de 1 h (ver F09 para o piso).
- **Validação:** UTF-8 incremental (M17, M18 mortas), PDF (M16 morta; M15 equivalente, pois `finish()` repete a checagem), NUL (M26), vazio (M25), Content-Type contraditório (M24), traversal no nome (M23), controles/bidi no nome (M22), limite de 10 MiB exato (M12, M13), `.part` removido em falha (M27).
- **Caminho no storage:** regex de chave antes de qualquer caminho (M11), `O_NOFOLLOW` em shard e arquivo (M09, M10), `O_EXCL`, `0600/0700` confirmados por probe, cancelamento no iterador de origem limpa o temporário.
- **Logs:** só `stage`, `request_id` e tipo da exceção; `raise ... from None`; `hide_parameters=True`; fora de development o 500 não imprime mensagem de exceção.
- **Migration:** colunas, CHECKs (`status`, `size_bytes >= 0`), `UNIQUE(storage_key)`, FKs `RESTRICT`, índice composto `(workspace_id, created_at, id)` conferem com o modelo; `downgrade` desfaz índice e tabela; `alembic check` limpo.
- **Transações/sessão:** `expire_on_commit=False`, rollback protegido por `asyncio.shield` nos caminhos de falha, `BaseException` tratado sem engolir cancelamento; criação de workspace é atômica (M29, M31 mortas).

## 5. Checklist de critérios de aceite

Legenda: ✓ atendido, parcial, ✗ não atendido.

### 3.0 Workspace Foundation (PR A)

| Critério | Status | Evidência |
| --- | --- | --- |
| Repositórios reutilizam a sessão, nunca `commit()` | ✓ | `repositories/workspace.py:77-79`, `workspace_member.py:116-118`; só `flush()` |
| Workspace + membership `owner` na mesma transação; falha sem órfão | ✓ | `services/workspace.py:31-61`; `test_workspace_service.py::test_membership_failure_rolls_back_workspace` (M29 morta) |
| Slug duplicado, inclusive sob concorrência | ✓ | `test_workspace_service.py::test_concurrent_same_slug_creates_exactly_one_workspace` (M31 morta); `test_workspace_api.py::test_duplicate_slug_returns_generic_409` |
| Usuário não controla `owner_id`/papel | ✓ | `schemas/workspace.py:161`; `test_payload_cannot_set_owner_or_role` (M28 morta) |
| Listagem não revela terceiros; sem membership não acessa detalhe | ✓ | `repositories/workspace.py:100-109`; `test_list_returns_only_workspaces_with_membership`, `test_detail_is_404_for_non_member_and_nonexistent_alike` |
| Dependency de autorização reutilizável | ✓ | `api/dependencies/workspace.py:315-347` |
| Ruff, Alembic, testes passam | ✓ | seção 2 |

### 3.1 Document Model (PR B)

| Critério | Status | Evidência |
| --- | --- | --- |
| Campos, `metadata_` mapeado para `metadata`, CHECK de status | ✓ | `models/document.py:44-104` |
| `storage_key` único, `size_bytes` | ✓ | `uq_documents_storage_key`; `ck_documents_size_bytes_nonnegative` |
| Índice por `workspace_id` / composto p/ ordenação | ✓ | `ix_documents_workspace_id_created_at_id` (migration `845eb9180446`) |
| Migration revisada à mão, aplicada, `alembic check` | ✓ | round-trip executado |
| Testes de integridade | ✓ | `tests/test_document_model.py` |
| Relacionamentos | ✓ | `Workspace.documents`, `User.uploaded_documents` |
| Observação | parcial | sem índice em `uploaded_by` (F13); RESTRICT é decisão do dono |

### 3.2 Schemas (PR B)

| Critério | Status | Evidência |
| --- | --- | --- |
| `DocumentResponse`/`DocumentListResponse`, `WorkspaceCreate`/`WorkspaceResponse` | ✓ | `schemas/document.py`, `schemas/workspace.py` |
| Campos internos ausentes | ✓ | `tests/unit/test_document_schema.py::test_storage_key_absent_from_openapi_schemas` (M19 morta) |
| Cliente não controla ownership | ✓ | `extra="forbid"` |
| Upload multipart com `UploadFile` | ✓ | `api/v1/documents.py:174` |
| OpenAPI documenta | parcial | sem 401/403/404 nas rotas (F07) |
| Testes unitários sem PostgreSQL | ✓ | `tests/unit/*` rodam com `POSTGRES_PORT=1` |

### 3.3 Storage (PR C)

| Critério | Status | Evidência |
| --- | --- | --- |
| `save()`, `open()`, `delete()` locais, sem Protocol | ✓ | `storage/local.py` |
| Diretório configurável e fora do Git | ✓ | `config.py:132-133`, `.gitignore` (`backend/var/`) |
| Chave imprevisível, não derivada do filename | ✓ | `secrets.token_hex(16)` (`local.py:90`) |
| Temporário + `os.replace` | ✓ | `local.py:96-150` |
| Traversal, symlink, escape do diretório | ✓ | M09, M10, M11, M36 mortas; `test_document_storage.py::test_symlink_*`, `::test_malformed_keys_are_refused` |
| Contagem em blocos e abort acima de 10 MiB | ✓ | M12, M13 mortas |
| Falha de escrita não deixa temporário | ✓ | M27 morta; `::test_write_failure_leaves_no_temp` |
| Nomes iguais não colidem | ✓ | `::test_same_content_gets_distinct_keys_without_overwrite` |
| Testes usam `tmp_path` | ✓ | `conftest.py` autouse `_isolated_document_storage` |

### 3.4 Upload (PR C)

| Critério | Status | Evidência |
| --- | --- | --- |
| 201 válido, `status="uploaded"` | ✓ | `test_owner_and_admin_can_upload` |
| `python-multipart` nas dependências | ✓ | `pyproject.toml` |
| Não autorizado rejeitado **antes de armazenar** | ✓ | `documents.py:176` (dependency); M04/M06 mortas |
| Não autorizado rejeitado antes de **ler/gravar o corpo** | ✗ | F01/F02 (probe) |
| >10 MiB rejeitado; tipo não permitido rejeitado | ✓ | `test_over_limit_gets_413_without_persisting`, `test_invalid_uploads_are_rejected_without_persisting` |
| PDF `%PDF-`; TXT/MD UTF-8 | ✓ | M15-M18 |
| Falha SQL aciona limpeza | ✓ | M14 morta |
| Crash entre passos registrado e reconciliação prevista | ✓ | ADR 0009; `document_reconciliation.py` |
| Sem caminhos internos em respostas ou logs | ✓ | `document.py:139-155`, `test_blob_removal_failure_after_commit_is_204_and_logged_safely` |

### 3.5 Consultas (PR D)

| Critério | Status | Evidência |
| --- | --- | --- |
| Repositório sempre limitado ao workspace | ✓ | `repositories/document.py:39-67` (M01-M03 mortas) |
| Ordenação `created_at desc, id desc`; padrão 20, máximo 100 | ✓ | M32, M34 mortas; `test_list_pagination_is_deterministic_with_id_tiebreak` |
| Vazio -> coleção vazia | ✓ | `test_list_empty` |
| Documento de outro workspace / workspace não autorizado -> 404 | ✓ | `test_cross_workspace_get_is_404_without_leaking_metadata`, `test_list_other_workspace_without_membership_gets_404` |
| Falha real de banco -> 500 controlado | ✓ | `test_read_db_failure_returns_controlled_500` |
| Só campos públicos | ✓ | `test_get_returns_only_public_fields` (M19 morta) |

### 3.6 Delete (PR D)

| Critério | Status | Evidência |
| --- | --- | --- |
| Só owner/admin; não autorizado não altera banco nem disco | ✓ | M05 morta; `test_member_and_viewer_cannot_delete`, `test_non_member_delete_is_404_and_intact` |
| Doc de outro workspace intacto; inexistente 404 | ✓ | M33 morta; `test_cross_workspace_delete_via_own_workspace_is_404_and_intact` |
| Metadados (commit) e depois blob; não descrito como atômico | ✓ | M21 morta; `document.py:89-126`; ADR 0009 |
| Arquivo ausente tolerado; falha pós-commit logada sem dados sensíveis | ✓ | `test_delete_with_blob_already_missing_is_204_and_warns`, `test_blob_removal_failure_after_commit_is_204_and_logged_safely` |
| Reconciliação recuperável | ✓ | `tests/test_document_reconciliation.py` (M07, M08, M30, M38 mortas); piso de idade ausente (F09) |

### 3.7 Testes e segurança (PR E)

Todos os cenários da spec possuem teste que existe e, onde mutado, falha sem a proteção. Ver seção 6. O teste mais importante (usuário A com JWT válido contra documento exclusivo do workspace B) é `test_phase3_security.py::test_multi_tenant_flow_isolates_workspaces` e `test_document_queries_delete_api.py::test_cross_workspace_get_is_404_without_leaking_metadata`: ambos falham com M01. A proteção de integração do `conftest.py` foi preservada (`test_database_guard.py`).

### 3.8 Auditoria final (PR E)

| Entrega | Status |
| --- | --- |
| `docs/reviews/phase-3-documents-audit.md` | ✓ (este arquivo) |
| ADR 0008 | parcial: contradiz a realidade em um ponto (F02) |
| ADR 0009 | ✓ (descreve fielmente F01 e a política de exclusão) |
| `docs/api/documents.md`, `workspaces.md`, README | ✓ conferidos contra o código e o OpenAPI gerado, salvo F07 |

## 6. Matriz de cobertura 3.7, verificada

Todos os nomes de teste citados pelo implementador **existem**. Coluna final: o que a mutação mostrou.

| Cenário | Testes citados | Verificação |
| --- | --- | --- |
| Workspace criado com owner | `WA::test_create_workspace_creates_membership_with_owner_role`, `WS::test_create_workspace_is_atomic_with_owner_membership` | existem; leitura confirma asserts de role/owner |
| Falha de membership -> rollback | `WS::test_membership_failure_rolls_back_workspace`, `..._integrity_error_...` | M29 morta |
| Slug duplicado + concorrência | `WS::test_concurrent_same_slug_...`, `test_duplicate_slug_raises_domain_error`, `WA::test_duplicate_slug_returns_generic_409` | M31 morta |
| JWT inválido 401 | `UP::test_invalid_jwt_gets_401`, `WA::test_invalid_or_missing_jwt_returns_401`, `QD::test_get_and_list_require_authentication` | existem |
| Sem membership 404 | `UP::test_non_member_and_missing_workspace_get_404`, `QD::...`, `WA::...` | M06 morta |
| Member/viewer upload 403 | `UP::test_member_and_viewer_get_403_and_nothing_is_stored`, `WA::test_permission_dependency_matrix` | M04 morta |
| Member/viewer delete 403 | `QD::test_member_and_viewer_cannot_delete` | M05 morta |
| Owner/admin upload e delete | `UP::test_owner_and_admin_can_upload`, `QD::test_owner_and_admin_delete_row_and_blob` | M33 morta |
| Documento de outro workspace 404 | `QD::test_cross_workspace_*`, `QD::test_list_total_and_items_ignore_other_workspaces`, P3 | M01-M03 mortas |
| PDF/TXT/MD válidos | `UP::test_owner_and_admin_can_upload` (parametrizado) | ok |
| Tipo/conteúdo inválido | `UP::test_invalid_uploads_are_rejected_without_persisting`, `test_document_validation.py` | M15-M18, M24-M26 (M15 equivalente) |
| >10 MiB rejeitado | `UP::test_over_limit_gets_413_...`, `test_exactly_limit_is_accepted`, `test_document_storage.py::test_over_limit_aborts_...` | M12, M13 mortas |
| **>10 MiB declarado -> rejeição cedo** | `UP::test_declared_content_length_far_over_limit_is_rejected_early` | **não assere o que alega**: passa sem o guarda (M20 sobreviveu; F05) |
| Falha ao salvar -> nenhuma linha | `UP::test_storage_failure_returns_500_and_no_row`, `test_document_storage.py::test_write_failure_leaves_no_temp` | M27 morta |
| Falha ao persistir -> limpeza | `UP::test_db_failure_returns_500_and_removes_blob`, `test_commit_failure_...` | M14 morta |
| Colisão sem sobrescrita | `UP::test_same_filename_twice_creates_distinct_blobs`, P3 | ok |
| Exclusão parcial identificada | `QD::test_blob_removal_failure_after_commit_is_204_...`, `test_delete_with_blob_already_missing_...`, `test_document_reconciliation.py` | M21, M07, M08, M30 mortas |
| Storage em tmp isolado | `conftest.py` autouse, `P3::test_document_storage_dir_is_isolated_per_test_by_conftest` | ok |
| Banco só `nexus_ai_test` | `conftest.py` guard, `test_database_guard.py` | herdado da Fase 2 |
| Múltiplos usuários, >=2 workspaces | P3 (5 usuários, 2 workspaces, owner/admin/member/viewer) | confirmado em `test_phase3_security.py` |
| Usuário A vs documento do B | `QD::test_cross_workspace_get_is_404_...`, `P3::test_multi_tenant_flow_isolates_workspaces` | M01 mata ambos |

Não coberto por nenhum teste: concorrência de upload/delete, liberação de conexão do pool durante o upload (F03/F11) e cancelamento de request durante `save()` (F06).

## 7. Riscos residuais aceitáveis para o MVP (estudo local)

- F01, F03, F04 enquanto a API não estiver exposta; ADR 0009 já exige limite de corpo no proxy.
- Reconciliação manual, sem CLI/agendador (F09, F12); órfãos só custam disco.
- PDF validado só pelo cabeçalho; sem varredura de malware.
- Enumeração de slug (F14) e ids numéricos públicos (F13).
- Storage local: não escala horizontalmente, sem criptografia em repouso, POSIX apenas.
- Residuais da Fase 2 que continuam valendo: sem limite de corpo global, rate limit por processo, sem refresh/revogação, sem lockfile.

## 8. Itens que exigem revisão humana

- `.env.example` e `backend/.env.example` (3 e 4 linhas alteradas): **não inspecionados — requer revisão humana**. Conferir que só trazem `DOCUMENT_STORAGE_DIR` com valor de exemplo, sem segredo nem caminho real.
- Ambiente de produção: dono e permissões do diretório de documentos, backup que preserve a coerência linha/blob e política de retenção.
- Confirmar no merge que a base de `main` e os PRs empilhados #2-#5 foram verificados com o CI após o commit dos ADRs (os checks que li estão verdes, mas não mapeei cada run ao SHA).

## 9. Decisões que precisam de aprovação explícita do dono

1. **204 quando o blob falha após o commit do delete** (documentado como política; o cliente não vê o órfão).
2. **FKs `ON DELETE RESTRICT`** em `workspace_id` e `uploaded_by`: impedem apagar workspace/usuário com documentos; PATCH/DELETE de workspace futuros precisarão de fluxo explícito.
3. **Política de slug**: `^[a-z0-9]+(?:-[a-z0-9]+)*$`, 3-63, sem normalização, único global, 409 que confirma existência (F14).
4. **`metadata` JSONB público**: nada interno pode entrar nele; hoje sempre `{}`.
5. **Leitura (listar/consultar) liberada a todos os papéis**, incluindo `viewer`, e exposição de `uploaded_by`/`owner_id` (F13).
6. **Aceitar F01** (spool pré-autenticação e chunked sem teto) para o estudo local, ou exigir o middleware de contagem de bytes antes do merge.
7. **Aceitar F04** (sem cota nem rate limit em workspaces/documentos).
8. **Corrigir F03** agora (pequeno, mesma classe da Fase 2) ou registrar como residual.

## 10. Revalidação (commits `dd6d307`..`b691cd0`)

Escopo: reauditoria independente das correções de F01, F02, F05, F06, F07, F08 e F09. Nenhum código, teste ou ADR foi alterado por mim; as mutações abaixo foram aplicadas e revertidas com `git checkout` (`git status` limpo).

### 10.1 Validação

| Comando | Resultado |
| --- | --- |
| `ruff check .` / `ruff format --check .` | `All checks passed!` / `148 files already formatted` |
| `POSTGRES_PORT=1 ... pytest -m "not integration" -q` | **313 passed**, 185 deselected |
| `POSTGRES_DB=nexus_ai_test pytest -q` | **498 passed** |
| `POSTGRES_DB=nexus_ai_test alembic check` | `No new upgrade operations detected.` |
| `gh pr checks 2..5` | verdes, mas são as execuções anteriores: os commits de correção ainda não foram enviados, então o CI **não** os cobriu |

### 10.2 Status por achado

| ID | Status | Verificação |
| --- | --- | --- |
| F01 | **Parcial** (decisão do owner) | Probe ASGI com blocos de 64 KiB, corpo de 200 MiB: chunked -> 413 com **10 485 760 bytes** gravados (antes: 209 715 200); `Content-Length: 100` mentiroso -> idem; `Content-Length` declarado acima do teto -> 413 sem ler o corpo. O teto vale em todos os casos, mas o spool pré-autenticação continua existindo (até ~10 MiB + 64 KiB **por requisição**, sem limite de concorrência). Mutações: sem o swap de `receive` (N01), teto frouxo (N02), sem mapeamento para 413 (N03) e sem o guarda de `Content-Length` (N04) são todas mortas por `test_chunked_body_far_over_limit_is_aborted_with_413` e `test_declared_content_length_over_limit_never_reads_body`. ADR 0009 reescrito e fiel ao comportamento |
| F02 | **Corrigido** | ADR 0008 agora diz que o corpo é lido (e gravado acima de 1 MiB) antes da autenticação e remete ao ADR 0009; coerente com o probe |
| F05 | **Corrigido** | O teste do `Content-Length` agora falha sem o guarda (N04). `test_list_blobs_skips_symlinked_blobs_and_shards` mata a mutação que segue symlink (N12; antes M35 sobrevivia) |
| F06 | **Corrigido** | `_run_to_completion` espera a thread terminar (re-await do `shield` a cada cancelamento, repassa `CancelledError` ao final); `_Descriptors` registra cada fd na própria thread e zera antes de fechar; nenhum fd é fechado enquanto uma thread ainda o usa, logo sem reuso de número. Mortas: `to_thread` simples (N05), `close_all` sem root (N14), sem `unlink` do `.part` (N13). **Sobrevive** N06 (`close()` sem zerar o atributo, que causaria fechamento duplo de fd): ver G03 |
| F07 | **Corrigido** | 401/403/404 declarados em todas as rotas de documentos e workspaces (conferido no `openapi()`); N11 morta por `test_workspace_and_document_routes_document_error_responses` |
| F08 | **Corrigido** | Espaços Unicode colapsados (`a b` -> `a b`), variation selectors removidos, limite em **bytes** UTF-8 cortando em fronteira de caractere, NFKC rejeitado de forma documentada. Mortas: N08, N09, N10 |
| F09 | **Corrigido** | `MIN_AGE_FLOOR_SECONDS = 60`; valores menores, negativos ou NaN geram `ValueError` antes de tocar o storage (N07 morta). Nota: os testes e a função tratam a idade de `.part` do mesmo modo |
| F03, F04, F10-F14 | **Aberto — decisão do owner** | Sem alteração, como combinado. F03 (conexão do pool presa durante o I/O do upload) e F04 (sem cota) seguem bloqueantes para exposição pública |

### 10.3 Análise de F01: fragilidade de `request._receive`

- O código troca o atributo **privado** `Request._receive` (`api/v1/documents.py`, `request._receive = bounded_receive`). Starlette instalado: **1.10.0**; `pyproject.toml` pede apenas `starlette>=1.3.1`, sem teto. O parser de multipart lê `request.stream()`, que usa `self._receive`; funciona hoje.
- Risco de upgrade: se uma versão futura renomear ou copiar o `receive`, a troca vira no-op silencioso e o teto some. Mitigação real: N01 mostra que o teste de 200 MiB chunked falha nesse caso, então o CI denuncia a regressão (ela só não aparece sem rodar a suíte).
- Recomendação (Baixo, não bloqueante): migrar para um middleware ASGI puro, restrito ao caminho `POST .../documents`, que envolve `receive` antes de o Starlette criar o `Request`. É API pública, também limita a leitura que ocorre antes das dependencies e não depende de atributo privado. Alternativa mínima: limitar a versão (`starlette>=1.3.1,<2`) e manter o teste como guarda.
- Cobertura do requisito: o teto limita bytes gravados tanto em chunked quanto com `Content-Length` mentiroso. Em produção, h11/httptools já rejeitam corpo maior que o `Content-Length` declarado; o probe em ASGI direto confirma que o teto não depende disso.

### 10.4 Regressões e novos achados

Não encontrei regressão funcional: suíte completa verde, comportamento antigo de 413/401/404 preservado, tamanhos de arquivo no limite exato ainda aceitos.

| ID | Severidade | Achado |
| --- | --- | --- |
| G01 | Baixo | `request._receive` privado (seção 10.3); recomendar middleware ASGI puro ou teto de versão |
| G02 | Informativo | O spool pré-autenticação ainda ocorre e não há limite de concorrência: 100 requisições anônimas simultâneas gravam ~1 GiB em `TMPDIR`. Mitigar com limite no proxy/rate limit (F04) ou mover a autenticação antes do parsing |
| G03 | Baixo | Falta teste que detecte `_Descriptors.close()` sem zerar o atributo (N06 sobrevive). O código atual está correto (zera antes de fechar), mas a regressão causaria fechamento duplo de um número de fd possivelmente reaproveitado |
| G04 | Informativo | `_run_to_completion`: se a thread falhar depois de cancelada, o `CancelledError` prevalece e a exceção da thread pode ser registrada como "never retrieved"; sem impacto funcional. Um blob já publicado antes do cancelamento não é removido (vira órfão recuperável pela reconciliação; ADR 0009 cobre) |
| G05 | Informativo | O colapso de espaços altera nomes com espaços internos repetidos (`a  b.txt` -> `a b.txt`); intencional e documentado nos testes |

### 10.5 Veredito atualizado

**Aprovada com ressalvas, mais próxima do merge.** Nenhum achado Crítico ou Alto novo; F01 caiu de Alto para **Parcial/Médio** (spool limitado a ~10 MiB por requisição). Bloqueantes para o merge da fase: **nenhum** de código. Pendências que o owner deve aprovar explicitamente: F01 residual (spool pré-autenticação sem limite de concorrência), F03, F04 e as decisões da seção 9. Recomendo, antes de enviar: executar o CI nos commits de correção e considerar G01/G03. Para exposição pública continuam bloqueantes F03, F04 e G02, mais os residuais da Fase 2.
