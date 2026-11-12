# Auditoria final da Fase 3 (Documents) — Etapa 3.8

## 1. Veredito (estado atual — HEAD `fcdeddf`, após as revalidações das seções 10, 11, 12 e 13)

**Fase 3 aprovada para encerramento (escopo: estudo local de Documents / MVP).** Nenhum achado Crítico, Alto ou Médio em aberto. A autorização multi-tenant, a validação de arquivos, a segurança de caminho do storage, a consistência SQL/filesystem, o guarda ASGI do upload e as cotas/rate limits se sustentaram em leitura de código, mutações dirigidas e probes de execução (inclusive contra um uvicorn real). Os achados R01-R08 da revalidação 3 foram corrigidos e reverificados (seção 13). O que resta é para **produção**, não para o merge.

Estado dos achados (a tabela da seção 3 é o registro histórico da primeira passada; cada linha traz o status atual):

- **F01** (era Alto): **Parcial, residual aceito para o MVP**. O middleware ASGI valida o JWT sem banco antes de ler o corpo (anônimo/token inválido: 0 bytes lidos, provado em ASGI e em uvicorn real) e limita o corpo a ~10 MiB + 64 KiB; o guarda agora também vale com `root_path`/mount/prefixo (R01 corrigido). Resta o spool de usuário autenticado sem membership/inativo, limitado por rate limit e teto de simultâneos, registrado como política aceita no ADR 0009.
- **F02, F03, F05, F06, F07, F08, F09**: **Corrigidos**. **G01**: Corrigido. **G02**: Reduzido (ver F01). **N01, N02, N03, R01-R08**: **Corrigidos**.
- **F04**: **Atendido para o MVP** (aprovado pelo owner); limites em memória e **por processo**.
- **F10, F11, F12, F13**: **Abertos, informativos**. **F14**: aceito.

Bloqueantes para o **encerramento/merge da Fase 3**: nenhum. CI no HEAD `fcdeddf`: `test` e `unit` em success (run `43306801953`). Para **produção** (seção 9): limite de corpo no proxy, store compartilhado (ou limites no proxy) com mais de um worker, reconciliação operacionalizada, PDF mais rigoroso, residuais da Fase 2.

## 2. Escopo e método

- Branch `feat/phase3-e-hardening-audit` (PR #6, empilhada sobre #2-#5). Primeira passada: 6 commits sobre `main` (`aa01e77` .. `817b672`): A fundação de workspace, B modelo, C storage/upload, D consultas/exclusão, E testes e ADRs. Revalidações posteriores cobrem os commits até o HEAD `800f71c` (seções 10, 11 e 12).
- Auditor independente: não escrevi nem alterei código, testes ou ADRs. O único artefato é este arquivo.
- Lido na íntegra: `storage/local.py`, `services/document*.py`, `services/workspace.py`, repositórios, dependencies, rotas, schemas, handlers, migration, modelo, ADRs 0008/0009, `docs/api/*`, README, workflow de CI e a lista de testes.
- **Mutação**: 38 mutações aplicadas no repositório e revertidas com `git checkout -- <arquivo>` logo após a suíte completa (`git status` limpo ao final). 34 foram mortas pela suíte; 1 é equivalente (M15); 3 sobreviveram (M20 e M35, ver F05; M37, `list_blobs` sem checar o shard, inócua porque `delete()` não acharia o arquivo).
- **Probes** (scripts só no scratchpad): spool pré-autenticação, conexão do pool durante o upload, cancelamento do `save()`, permissões do storage, sanitização de nomes unicode, round-trip `alembic downgrade -1`/`upgrade head`.
- `.env.example` e `backend/.env.example`: a leitura me era vedada por permissão; o **owner inspecionou manualmente** os dois arquivos e confirmou que só foi adicionada a configuração de storage, comentada, sem nenhum segredo real (informação do owner, não verificada por mim).

### Validação da primeira passada (histórico; números superados — ver 10.1, 11.1, 12.1 e **13.1** para o estado atual no HEAD)

| Comando | Resultado |
| --- | --- |
| `ruff check .` / `ruff format --check .` | `All checks passed!` / `147 files already formatted` (superado: 156 arquivos no HEAD `fcdeddf`) |
| `POSTGRES_PORT=1 POSTGRES_DB=nexus_ai_test pytest -m "not integration" -q` | 299 passed, 183 deselected (superado: **336 passed, 227 deselected** no HEAD `fcdeddf`) |
| `POSTGRES_DB=nexus_ai_test pytest -q` | 482 passed, 1 warning (superado: **563 passed** no HEAD `fcdeddf`) |
| `POSTGRES_DB=nexus_ai_test alembic check` | `No new upgrade operations detected.` Round-trip downgrade/upgrade ok, head `845eb9180446` |
| `gh pr checks 2,3,4,5` | `test` e `unit` **pass** nos quatro PRs (superado: PR #6, run `43306801953`, head `fcdeddf`, `test` e `unit` **pass**) |

Ressalva: o CI usa Python 3.12 e a máquina local 3.14; ambos passam.

## 3. Achados (registro da primeira passada; texto das colunas de severidade, evidência e impacto é histórico e está **superado** onde a última coluna indica correção)

| ID | Severidade | Achado | Evidência | Impacto | Correção recomendada | Status atual |
| --- | --- | --- | --- | --- | --- | --- |
| F01 | **Alto** | Multipart é lido e gravado (spool em disco acima de 1 MiB) **antes** da autenticação; corpos chunked não têm teto. O guarda só atua com `Content-Length` declarado. | `backend/app/api/v1/documents.py:116-136`; FastAPI 0.162 `routing.py:455` (`request.form()` antes de `solve_dependencies`). Probe: não autenticado, 5 MiB com `Content-Length` → 401 após 5 242 880 bytes gravados; chunked de **200 MiB** → 401 após 209 715 200 bytes gravados | DoS de disco/CPU/tempo por qualquer cliente anônimo; o limite de 10 MiB não protege a rota. Divulgado no ADR 0009 (trade-offs) | Middleware ASGI que conta bytes do corpo e responde 413 mesmo sem `Content-Length` (ou exigir 411 na rota), e/ou limite no proxy. Decisão do dono (seção 9) | **Parcial (residual aceito no MVP)** — ver §10/§12/§13. Alto superado. JWT validado sem banco antes de ler o corpo; guarda vale também com `root_path`/mount (R01 corrigido); resta o spool de usuário autenticado sem membership/inativo, limitado por F04 |
| F02 | **Médio** | ADR 0008 afirma que a autorização roda "antes de qualquer escrita ou leitura de corpo da rota". É falso para a leitura de corpo e contradiz o ADR 0009. | `docs/decisions/0008-workspace-bootstrap-and-authorization.md`, item "404 versus 403"; medição de F01 | Garantia de segurança documentada que não existe | Trocar por "antes de qualquer escrita no storage; o corpo multipart é lido antes (ver ADR 0009)" | Corrigido — ver §10 |
| F03 | **Médio** | A sessão abre transação nas dependencies de auth (`get_current_user`, membership) e só a encerra no `commit`/`rollback`; o `storage.save()` (até 10 MiB, com `fsync`) roda com a conexão do pool presa. | `backend/app/services/document.py:51-57`. Probe: `engine.pool.checkedout() == 1` dentro de `save()` | Com pool 5+10 (`config.py:122-123`), ~15 uploads lentos concorrentes esgotam o pool e derrubam todas as rotas (mesma classe do A3 da Fase 2) | Encerrar a transação de leitura (`await session.commit()` ou `rollback()`; `expire_on_commit=False`) antes do `save()`, com teste de pool `pool_size=1` como em `test_auth_connection_release.py` | Corrigido — ver §11 |
| F04 | **Médio** | Sem cota nem rate limit: cadastro aberto, qualquer usuário cria workspaces ilimitados e, sendo `owner`, sobe documentos ilimitados. | `docs/api/workspaces.md` (Limites), ADR 0008 (fora de escopo); `api/v1/workspaces.py:199-211` | Esgotamento de disco por conta autenticada | Cota por workspace/usuário (bytes e documentos) e rate limit nas rotas; aceitar explicitamente para o MVP | **Atendido para o MVP** (aprovado pelo owner) — ver §12: rate limit e teto de simultâneos por usuário, cota por workspace, teto de workspaces por dono; em memória e por processo; lacunas R02/R03 fechadas (§13) |
| F05 | Baixo | Testes que passariam sem a proteção: (a) `test_declared_content_length_far_over_limit_is_rejected_early` só confere 413 e `_blobs == []`; sem o guarda de `Content-Length` (M20) o limite do storage devolve o mesmo resultado; (b) M35: `list_blobs` com `is_file()` seguindo symlink não é pego (a segunda camada, `delete()` com `S_ISREG`, mascara). | `tests/test_document_upload_api.py:266-277`; `storage/local.py:246-252` | O guarda de F01 e a varredura sem symlink não têm teste dedicado | (a) Espionar `storage.save` e afirmar que não foi chamado/que o corpo não foi lido; (b) teste de `list_blobs` com symlink para fora do root | Corrigido — ver §10 |
| F06 | Baixo | Cancelamento do request pode vazar descritores e `.part`: se a task é cancelada durante `to_thread(self._start, ...)`, a tupla `(root_fd, tmp_fd, fd)` nunca é atribuída e os fds/arquivo ficam sem dono; em `_write_all`, o `except` fecha `fd` enquanto a thread ainda escreve (risco de reuso do número do fd). Não reproduzido (janela estreita), só por leitura. | `storage/local.py:96-97,103-111,121-146` | Vazamento lento de fds; escrita num fd reaproveitado em caso extremo | Abrir os fds dentro de `asyncio.shield` ou tornar a thread dona da limpeza; reconciliação já recolhe `.part` e blob publicado | Corrigido — ver §10 |
| F07 | Baixo | OpenAPI não declara 401/403/404 nos endpoints de documentos e workspace (upload só 413/415/422; list sem 404; `GET /workspaces/{id}` sem 404). Spec 3.2: "OpenAPI documenta". | `api/v1/documents.py:158-167,183`; `api/v1/workspaces.py:223` | Contrato público incompleto; o `docs/api` está correto | Declarar `responses` (401/403/404) ou um helper comum | Corrigido — ver §10 |
| F08 | Baixo | Sanitização de nome: U+2028 (Zl), NBSP e variation selectors passam; só NFC, sem NFKC/confusáveis (`ＮＯＴＥ.md` mantido); limite de 255 é em caracteres, não bytes. Probe confirmou. O nome é só exibição, nunca caminho. | `services/document_validation.py:325-344` | Spoofing visual em UI futura; sem efeito no disco | Incluir Zl/Zp e espaços exóticos em `_DROP`; decidir NFKC (residual QA10 da Fase 2) | Corrigido — ver §10 |
| F09 | Baixo | `reconcile_orphans` aceita `min_age_seconds=0` ou negativo; com `dry_run=False` isso removeria blob publicado cuja linha ainda não foi confirmada, deixando a linha apontando para nada. O padrão (1 h) é seguro e o mtime reflete a última escrita. Sem CLI nem agendador. | `services/document_reconciliation.py:202-225,242-250` | Só por chamada manual errada; órfãos se acumulam até alguém executar | Piso mínimo de idade (ex.: 5 min) com erro explícito; CLI/agendamento na Fase 4 | Corrigido — ver §10 |
| F10 | Informativo | Exclusões concorrentes do mesmo documento: ambas leem a linha, a segunda apaga 0 linhas (aviso do SQLAlchemy) e responde 204 em vez de 404; benigno (idempotente), não reproduzido. | `services/document.py:98-113` | Nenhum dado exposto | Opcional: tratar `rowcount == 0` como 404 | Aberto — informativo (sem mudança; benigno) |
| F11 | Informativo | Os testes de API usam sessão com `join_transaction_mode="create_savepoint"`: `commit`/`rollback` reais, liberação de conexão e concorrência de upload/delete não são exercitados; falhas de commit são simuladas. | `tests/test_document_upload_api.py:44-56` | Explica por que F03 passou despercebido | Um teste sem savepoint (como em `test_auth_connection_release.py`) | Aberto — informativo (os testes novos de F03/F04 usam sessões reais sem savepoint, o que mitiga na prática; sem teste de upload/delete concorrentes) |
| F12 | Informativo | Reconciliação só cobre blob sem linha. Linha sem blob (restauração parcial de backup) não é detectada. PDF só confere `%PDF-` (polyglot aceito) e TXT aceita controles além de NUL; ambos divulgados. | ADR 0009; `document_validation.py:371-387` | Aceito no MVP | Fase 4: validação estrutural de PDF; checagem inversa na reconciliação | Aberto — informativo (aceito no MVP; PDF só pelo cabeçalho) |
| F13 | Informativo | `uploaded_by` e `owner_id` (inteiros sequenciais) são expostos a qualquer papel, inclusive `viewer`; sem índice em `documents.uploaded_by` (FK RESTRICT). Root pré-existente com 0755 não é endurecido (blobs 0600, shards 0700 verificados). Código depende de `dir_fd`/`O_NOFOLLOW` (POSIX). | `schemas/document.py`, `schemas/workspace.py:166-173`; probe de permissões | Sem vazamento entre tenants (IDOR bloqueado por workspace) | Decisão de produto sobre ids públicos; documentar "POSIX only" | Parcial — leitura por todos os papéis aprovada (decisão 5 do owner); exposição de `uploaded_by`/`owner_id`, índice em `uploaded_by` e "POSIX only" sem decisão explícita |
| F14 | Informativo | 409 de slug confirma a existência de slugs de outros tenants (enumeração). Documentado no ADR 0008. | `services/workspace.py:34-37` | Baixo | Aceito; ver seção 9 | **Aceito** — slug e 409 aprovados pelo owner (decisão 3, 2026-11-12; ADR 0008) |

## 4. Verificações sem achado (resumo)

- **Arquitetura:** router orquestra, service decide, repositório só SQL; nenhum repositório chama `commit()`; sem `Protocol`/camadas fictícias; `_BoundedUploadRoute` é a única abstração extra e se justifica. *(Histórico: `_BoundedUploadRoute` foi substituída pelo `UploadGuardMiddleware`, seção 12.)*
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
| Não autorizado rejeitado antes de **ler/gravar o corpo** | parcial (era ✗) | JWT ausente/inválido: 401 sem ler o corpo (middleware, §12; probes ASGI e uvicorn). Membership/papel/usuário ativo ainda são checados depois da leitura (≤ ~10 MiB por requisição, limitado por F04); R01 |
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
| ADR 0008 | ✓ (F02 corrigido); linha obsoleta de "Fora de escopo" corrigida (R05, §13) |
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
| **>10 MiB declarado -> rejeição cedo** | `UP::test_declared_content_length_over_limit_never_reads_body` | (histórico: o teste original não assertava o que alegava, F05; corrigido e verificado na §10/§12) |
| Falha ao salvar -> nenhuma linha | `UP::test_storage_failure_returns_500_and_no_row`, `test_document_storage.py::test_write_failure_leaves_no_temp` | M27 morta |
| Falha ao persistir -> limpeza | `UP::test_db_failure_returns_500_and_removes_blob`, `test_commit_failure_...` | M14 morta |
| Colisão sem sobrescrita | `UP::test_same_filename_twice_creates_distinct_blobs`, P3 | ok |
| Exclusão parcial identificada | `QD::test_blob_removal_failure_after_commit_is_204_...`, `test_delete_with_blob_already_missing_...`, `test_document_reconciliation.py` | M21, M07, M08, M30 mortas |
| Storage em tmp isolado | `conftest.py` autouse, `P3::test_document_storage_dir_is_isolated_per_test_by_conftest` | ok |
| Banco só `nexus_ai_test` | `conftest.py` guard, `test_database_guard.py` | herdado da Fase 2 |
| Múltiplos usuários, >=2 workspaces | P3 (5 usuários, 2 workspaces, owner/admin/member/viewer) | confirmado em `test_phase3_security.py` |
| Usuário A vs documento do B | `QD::test_cross_workspace_get_is_404_...`, `P3::test_multi_tenant_flow_isolates_workspaces` | M01 mata ambos |

Não coberto na primeira passada (superado): liberação de conexão do pool durante o upload e cancelamento durante `save()` agora têm testes (seções 10 e 11); concorrência de upload/delete continua sem teste.

## 7. Riscos residuais (desenvolvimento local x produção) — atualizado no HEAD `fcdeddf`

Tabela do owner, com as linhas atualizadas pelas revalidações finais (seções 12 e 13). As colunas de desenvolvimento e produção foram mantidas; a coluna "Status no HEAD" é nova.

| Risco | Desenvolvimento local | Produção | Status no HEAD (verificação, seção 12) |
| --- | --- | --- | --- |
| Spool multipart antes da autenticação | Aceitável com ressalva | Exige mitigação | **Reduzido.** Anônimo/JWT inválido: 401 sem ler byte (provado em ASGI e em uvicorn real). Resta usuário autenticado sem membership ou inativo (≤ ~10 MiB por requisição, limitado por rate limit e simultâneos; aceito no MVP). R01 (fuga com `root_path`/mount) **corrigido**. Mitigação em produção: limite de corpo no proxy |
| Ausência de cotas de arquivos/workspaces | Aceitável | Bloqueante | **Atendido para o MVP** (cota 1000 docs/1 GiB por workspace, 10 workspaces por dono; pré-checagem + checagem autoritativa sob `FOR UPDATE`; mutações mortas). Em produção: valores a rever; contagem é O(documentos) por upload |
| Rate limiting ausente nos uploads | Aceitável | Bloqueante | **Atendido para o MVP** (20/min e 2 simultâneos por usuário; 10 criações de workspace/hora). **Por processo e em memória**: com N workers o teto é N vezes maior e o reinício zera. Produção multi-worker: store compartilhado ou limite no proxy |
| Conexão SQL durante I/O | Resolvido (verificado: `pool.checkedout() == 0` durante `save()` no engine real) | Resolvido; monitorar espera por lock (`FOR SHARE`/`FOR UPDATE` do workspace) e pool | **Resolvido**; esperas por lock limitadas a 5 s por `lock_timeout` local à transação (N02 verificado, sem vazamento para o pool) |
| Dependência de `request._receive` privado | Monitorar | Avaliar substituição | **Resolvido** (G01): middleware ASGI puro, só API pública; nenhuma referência a `_receive` em `app/` |
| Reconciliação sem agendador | Aceitável | Operacionalizar | Inalterado: sem CLI nem agendador |
| PDF validado apenas pelo cabeçalho | Aceitável na Fase 3 | Exige tratamento mais rigoroso conforme uso | Inalterado |
| Guarda de upload depende do path casar (`root_path`/mount) | Aceitável | Resolvido | **Resolvido (R01)**: prefixo opcional + remoção do `root_path`; verificado com o app real |

Nota: o middleware elimina o spool anônimo, mas a proteção em produção ainda precisa combinar limite de corpo no proxy, limites compartilhados (ou no proxy) e cotas. Antes do `UploadGuardMiddleware` (histórico): `_BoundedUploadRoute` só reduzia o consumo, cada requisição anônima podia gravar ~10 MiB antes do 401.

Outros residuais: 500 no upload não prova que o documento não existe (commit incerto, seção 11); enumeração de slug (F14, aceita) e ids numéricos públicos (F13); storage local sem criptografia em repouso, só POSIX e com hard links; residuais da Fase 2 (rate limit por processo, sem refresh/revogação, sem lockfile); espaço de chaves do limitador limitado a 4096 por instância (R07, documentado no ADR 0009).

## 8. Itens que exigem revisão humana — atualizado

- `.env.example` e `backend/.env.example`: **inspecionados manualmente pelo owner** (só a configuração de storage comentada foi adicionada, sem segredo real). Os novos nomes de configuração de F04 (`UPLOAD_*`, `WORKSPACE_*`) estão no README; **não li nenhum `.env*`** e não verifiquei se foram acrescentados aos exemplos (não é bloqueante: os padrões estão no código e no README).
- Ambiente de produção: dono e permissões do diretório de documentos, backup que preserve a coerência linha/blob e política de retenção; limite de corpo no proxy; número de workers (limites por processo); (R01 corrigido: `--root-path`/mount são seguros para o guarda).
- CI: **resolvido para o HEAD `fcdeddf`**: run `43306801953` (PR #6) com `test` e `unit` em **success** (commit `800f71c` também passou, run `43302165607`).
- Higiene de ambiente local: `backend/.venv` não tem `python-multipart` (17 erros de coleção se usado); a suíte roda no `.venv` da raiz. Não afeta o CI.

## 9. Decisões do dono — estado no HEAD `fcdeddf`

Aprovadas pelo owner em **2026-11-12** e registradas nos ADRs 0008/0009 (commit `dc07d36`, conferido):

1. **Aprovada:** 204 quando o blob falha após o commit do delete (ADR 0009, Política de exclusão).
2. **Aprovada:** FKs `ON DELETE RESTRICT` em `workspace_id` e `uploaded_by` (ADR 0009).
3. **Aprovada:** política de slug `^[a-z0-9]+(?:-[a-z0-9]+)*$`, 3-63, sem normalização, único global; 409 que confirma existência (F14 aceito) (ADR 0008).
4. **Aprovada:** `metadata` JSONB público; nada interno pode entrar nele (ADR 0009).
5. **Aprovada:** leitura liberada a todos os papéis, incluindo `viewer` (ADR 0008). A exposição de `uploaded_by`/`owner_id` (F13) não é citada nominalmente.
6. **F04 aprovado para o MVP** (ADR 0008 e 0009: "aprovado pelo owner para o MVP"): cotas, rate limit e teto de simultâneos, com a ressalva "em memória, por processo".
7. **F01 residual, commit incerto e hard links**: o ADR 0009 agora traz a seção "Políticas aceitas para o MVP (revisar antes de produção)", atribuída ao owner em 2026-11-12. Registro verificado nos ADRs; a aceitação em si é informação do owner (não verificada por mim).
8. "POSIX only" e exposição de `uploaded_by`/`owner_id` (F13): sem decisão nominal.

O que resta **somente para produção** (nada bloqueia o encerramento da Fase 3):
- limite de corpo no proxy reverso (pouco acima de 10 MiB nas rotas de upload);
- store compartilhado (ou limites no proxy) para rate limit e simultâneos se houver mais de um worker; hoje por processo e zerados no reinício;
- agendar/operacionalizar a reconciliação (sem CLI nem agendador);
- validação mais profunda de PDF conforme o uso;
- rever os valores de cota/limites e as "políticas aceitas" do ADR 0009 (F01 residual, commit incerto, hard links);
- decidir F10-F13 (informativos);
- residuais da Fase 2 (rate limit por processo, sem refresh/revogação, sem lockfile);
- operação: permissões do diretório de documentos, backup coerente linha/blob, retenção.

## 10. Revalidação 1 (commits `dd6d307`..`b691cd0`) — histórico

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
| F03 (superado: corrigido na §11), F04, F10-F14 | **Aberto na época; F03 corrigido na §11** | Sem alteração, como combinado. F03 (conexão do pool presa durante o I/O do upload) e F04 (sem cota) seguem bloqueantes para exposição pública |

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

### 10.5 Veredito atualizado (histórico, superado pela seção 12)

**Aprovada com ressalvas, mais próxima do merge.** Nenhum achado Crítico ou Alto novo; F01 caiu de Alto para **Parcial/Médio** (spool limitado a ~10 MiB por requisição). Bloqueantes para o merge da fase: **nenhum** de código. Pendências que o owner deve aprovar explicitamente: F01 residual (spool pré-autenticação sem limite de concorrência), F03, F04 e as decisões da seção 9. Recomendo, antes de enviar: executar o CI nos commits de correção e considerar G01/G03. (Superado pela seção 11.) Para exposição pública continuam bloqueantes F04 e G02, mais os residuais da Fase 2.

## 11. Revalidação 2 (commits `c97452c`, `54b72dd`, `2d50aeb`, `4848aa6`) — histórico

Mesmas regras: nenhum código, teste ou ADR alterado por mim; mutações revertidas (`git status` limpo).

### 11.1 Validação (HEAD)

| Comando | Resultado |
| --- | --- |
| `ruff check .` / `ruff format --check .` | `All checks passed!` / `149 files already formatted` |
| `POSTGRES_PORT=1 ... pytest -m "not integration" -q` | **315 passed**, 190 deselected |
| `POSTGRES_DB=nexus_ai_test pytest -q` | **505 passed**, 1 warning |
| `POSTGRES_DB=nexus_ai_test alembic check` | `No new upgrade operations detected.` |

### 11.2 Status por item

| Item | Status | Verificação |
| --- | --- | --- |
| F03: conexão presa durante o I/O | **Corrigido** | `DocumentService.upload_document` faz `commit()` da transação de leitura antes de `storage.save()` (`services/document.py:64`). Probe no **engine real** (não o do teste, sem override de sessão): `pool.checkedout()` dentro de `save()` passou de 1 para **0**. Mutação sem o commit antecipado (Q01) é morta por `test_connection_released_during_storage_io` (`pool_size=1`) e por outros 2 testes. O commit não grava nada indevido: as dependencies (`get_current_user`, membership) só leem, e `get_current_user` não tem escrita; `expire_on_commit=False` mantém `user`/`membership` utilizáveis |
| Releitura de permissão (TOCTOU) | **Corrigido** | `get_membership(..., lock_shared=True)` na transação de escrita (`services/document.py:81-83`); 404 sem membership, 403 sem `document:upload`, linha não criada e blob removido. Mutações: sem releitura (Q04), sem checar papel (Q05), sem remover o blob (Q06) e sem `populate_existing` (Q03) são mortas. **Q02 (remover `FOR SHARE`) sobrevive**: nenhum teste exercita o lock (ver N02) |
| Commit de resultado incerto | **Corrigido** | Exceção levantada **por** `session.commit()` mantém o blob, faz rollback best-effort, loga `stage=commit_uncertain` e responde 500 (`services/document.py:113-129`). Falha antes do commit continua removendo o blob. Classificação correta: `DocumentRepository.create()` faz `flush()` antes (INSERT, FKs e CHECKs são verificados ali, dentro do primeiro `try`, e não há constraint deferida), então um `IntegrityError` do INSERT cai no ramo "antes do commit" e remove o blob; o `commit()` só emite `COMMIT` (nada pendente a flushar). Mutações: commit falho apagando o blob (Q07) e falha pré-commit sem apagar (Q08) são mortas; cancelamento (`BaseException`) é relançado com rollback sob `shield` e blob mantido |
| `os.replace` -> `os.link` | **Corrigido** | `_publish` usa `os.link(..., follow_symlinks=False)` entre dir fds (falha se o destino existe), até 3 chaves, depois `StorageError` (`storage/local.py:196-233`); `fsync` do shard; `unlink` do `.part`. Mutações: voltar a `os.replace` (Q09), 1 tentativa (Q10) e não remover o `.part` (Q12) são mortas. **Q11 sobrevive** (remover o `unlink` do link quando o `fsync` falha): ver N03 |
| Resumo e tabela inicial desatualizados | **Corrigido** | Seções 1, 2, 3, 7, 8 e 9 reescritas/marcadas como superadas; números atualizados |
| `.env.example` | **Registrado** | Owner inspecionou: só a configuração de storage comentada, sem segredo (seção 8) |
| Tabela de riscos do owner | **Incluída** | Seção 7, com a linha de conexão SQL atualizada |

### 11.3 Análise dos pontos pedidos

- **Commit antecipado libera a conexão em produção?** Sim: o probe com `SessionLocal`/engine reais mostra 0 conexões em uso durante `save()`. O ganho depende de o chamador não reabrir transação antes do I/O: `validated_chunks`/`upload.read` não tocam o banco.
- **Algo pendente indevido?** Hoje não (dependencies só leem). Risco futuro: qualquer dependency que passe a escrever na sessão teria a escrita confirmada nesse commit antes da validação do conteúdo (N04).
- **`FOR SHARE`: deadlock e espera.** A releitura trava a linha de membership em modo compartilhado até o commit, que vem logo a seguir. Locks seguintes do upload (INSERT em `documents`: `FOR KEY SHARE` em `workspaces` e `users` pelas FKs) são compatíveis entre si, então não vejo ordem de lock que gere deadlock com as rotas existentes. Não há rota que revogue/altere membership hoje; quando existir, ela esperará o upload em andamento (curto) e, no sentido inverso, o upload esperaria o revogador **sem `lock_timeout`**, prendendo uma conexão do pool (N02). Sem interação com o caminho incerto: o lock cai no `rollback`/`COMMIT`.
- **Cancelamento.** Antes do commit: `_compensate` (rollback sob `shield`, remoção do blob). Durante o commit: rollback sob `shield`, blob mantido, `CancelledError` relançado. Após o link e antes do retorno de `_publish`: a chave se perde e o blob vira órfão recuperável (igual ao residual G04).
- **`os.link` + fsync + limpeza.** Se o link existe e o `fsync` falha, o código remove o link e relança; `save()` então remove o `.part`. Se o `unlink` do `.part` falha após o sucesso, o `.part` (mesmo inode do blob) fica até a reconciliação: apagar o blob não libera espaço enquanto o `.part` existir (N05). Exige filesystem com hard links (documentado no ADR 0009).

### 11.4 Novos achados

| ID | Severidade | Achado | Evidência | Correção recomendada |
| --- | --- | --- | --- | --- |
| N01 | **Médio** | Dependência invertida: `DocumentService` (camada de serviço) levanta `fastapi.HTTPException` e importa matriz de permissões, `role_has_permission` e textos de erro de `app.api.dependencies.workspace`, que por sua vez importa `app.services.workspace`. Mistura semântica HTTP no domínio, cria risco de import circular e duplica a lógica 404/403 das dependencies. | `backend/app/services/document.py:16-24,84-96,105-106` | Mover `PERMISSIONS`/`role_has_permission` para um módulo neutro (`app/core/permissions.py`), levantar exceções de domínio (`WorkspaceNotFoundError`, `PermissionDeniedError`) e mapeá-las para 404/403 nos exception handlers; as dependencies usam o mesmo módulo |
| N02 | Baixo | `FOR SHARE` sem `lock_timeout` e sem teste: se um revogador futuro segurar a linha, o upload espera indefinidamente com uma conexão do pool. Q02 (remover o lock) sobrevive à suíte. | `repositories/workspace_member.py:20-26` | `SET LOCAL lock_timeout` curto (mapeado para 503) e um teste com duas sessões reais: `UPDATE/DELETE` do membership bloqueia até o commit do upload |
| N03 | Baixo | Sem teste para o desfazimento do link quando o `fsync` do shard falha (Q11 sobrevive): regressão deixaria blob publicado numa operação falha. | `storage/local.py:219-225` | Teste que força `os.fsync` a falhar na publicação e confere que o blob não fica publicado |
| N04 | Informativo | O `commit()` antecipado confirma qualquer escrita pendente na sessão do chamador; seguro hoje. | `services/document.py:64` | Comentário/teste que garanta dependencies de auth somente leitura |
| N05 | Informativo | Commit incerto e `.part` residual mantêm bytes em disco até a reconciliação manual (sem agendador); um 500 no upload não prova que o documento não existe, e o cliente que repete a requisição pode duplicar. | `services/document.py:113-129`; ADR 0009 | Operacionalizar a reconciliação (tabela de riscos); documentado no ADR |

### 11.5 Veredito atualizado (histórico, superado pela seção 12)

**Aprovada com ressalvas.** As três correções pedidas pelo owner estão implementadas, testadas e verificadas por mutação (as sobreviventes são lacunas de teste, N02/N03, não falhas de comportamento). Nenhum achado Crítico ou Alto. Nenhum bloqueante para o merge da fase; recomendo tratar N01 (camadas) antes ou logo depois do merge, e N02/N03 como testes pequenos. Para exposição pública continuam bloqueantes: cotas, rate limit/limite de concorrência de uploads e mitigação do spool pré-autenticação (seção 7). CI ainda precisa rodar sobre estes commits após o push.

## 12. Revalidação 3 — final (commits `ec71964`..`800f71c`, HEAD `800f71c`)

Mesmas regras: nenhum código, teste ou ADR alterado por mim. Mutações e testes de sondagem foram aplicados e revertidos/removidos (`git status` limpo; scripts só no scratchpad). Probes: ASGI direto contra o app real, **uvicorn real** (`curl`, corpos de 5 MiB e 30 MiB), PostgreSQL real (`nexus_ai_test`) com pool de 1 conexão e com carga concorrente. Commits cobertos: `ec71964` (N01), `37b1aad` (N02), `b70016a` (N03), `2b5e7af` (middleware ASGI), `dc07d36` (docs/aprovações), `d41d936`, `56388ea`, `51e4aa6`, `e351455`, `800f71c` (F04).

### 12.1 Validação (HEAD `800f71c`)

| Comando | Resultado |
| --- | --- |
| `ruff check .` / `ruff format --check .` (raiz do repositório) | `All checks passed!` / `155 files already formatted` |
| `POSTGRES_PORT=1 POSTGRES_DB=nexus_ai_test pytest -m "not integration" -q` | **325 passed**, 221 deselected, 1 warning |
| `POSTGRES_DB=nexus_ai_test pytest -q` | **546 passed**, 1 warning |
| `POSTGRES_DB=nexus_ai_test alembic check` | `No new upgrade operations detected.` |
| `gh run list --branch feat/phase3-e-hardening-audit` / `gh pr checks 6` | run `43302165607`, head `800f71c`: `test` (51 s) e `unit` (25 s) **success**. Run antigo `43098202408` (2026-11-11) preso em `queued` |

Observação de ambiente: usei o `.venv` da raiz; o `backend/.venv` não tem `python-multipart` e falha na coleção. A suíte completa foi rodada no estado limpo (sem meus arquivos de sondagem) e **depois** de uma limpeza de linhas que um probe meu interrompido deixou no banco de teste (removidas; afetou só execuções intermediárias, refeitas).

### 12.2 Status por item

| Item | Status | Evidência |
| --- | --- | --- |
| **N01** módulo de permissões + exceções de domínio | **Corrigido** (nuance R04) | `app/core/permissions.py` neutro; `DocumentService` levanta `WorkspaceNotFoundError`/`PermissionDeniedError`. `grep` em `app/services`, `repositories`, `core`, `storage`, `models`, `schemas`: **nenhum** `import app.api` nem `HTTPException`; resta `from fastapi import UploadFile` em `services/document.py:16` (tipo do upload, sem semântica HTTP; R04). Importação isolada de 9 módulos (`app.main`, serviços, dependencies, handlers, `permissions`, `upload_guard`, repositórios) sem ciclo. **Respostas idênticas em bytes**: sondagem com pool de 1 conexão comparou o 404 do serviço (membership removida durante o I/O) com o 404 da dependency, e o 403 do serviço (papel rebaixado durante o I/O) com o da dependency: mesmo status, corpo (`{"detail":"Workspace não encontrado."}` / `{"detail":"Permissão insuficiente."}`) e cabeçalhos (exceto `x-request-id`). Mutações: serviço importando `app.api.*` e serviço importando `HTTPException` mortas por `test_services_do_not_import_api_layer_or_http_exception` |
| **N02** `lock_timeout` | **Corrigido** (lacuna de teste R03) | `set_config('lock_timeout', '5000ms', true)` (`services/document.py:98-104`, local à transação) executa **antes** do `FOR SHARE` da membership **e** do `FOR UPDATE` do workspace (o mesmo valor vale para os dois). Sondagem no engine real com `pool_size=1`: depois de upload com sucesso, cota negada, 404/403 do serviço, criação de workspace e timeout, `SHOW lock_timeout` na mesma conexão do pool = `0` (**sem vazamento**). Timeout do `FOR UPDATE` do workspace (200 ms, linha bloqueada por outra sessão): 500 genérico, **0 blobs novos** (arquivos == linhas), rollback ok. Mutação de remover o `set_config` (N02b): morta. **Mutações `is_local=False` no upload (N02a) e no `UserRepository.lock_for_update` (N02c) sobrevivem**: nenhum teste prova a localidade (R03) |
| **N03** teste do desfazimento do link | **Válido** | `test_shard_fsync_failure_undoes_link_and_keeps_existing_blob` (`tests/test_document_storage.py:294`) força `fsync` de diretório a falhar. Mutações: sem o `unlink` do link novo (N03a) e `unlink` do nome errado (N03b): **ambas mortas**. Q11 da seção 11 deixou de sobreviver |
| **Middleware: casamento de path** | **Falha em `root_path`/mount (R01)**; demais casos ok | Regex `^/api/v1/workspaces/[^/]+/documents$` sobre `scope["path"]` (`upload_guard.py:53,120`). ASGI direto (corpo de 40 x 64 KiB): barra final -> 307 (o cliente repete no path guardado); `//api/...`, caixa diferente, `%2F` decodificado, `./` -> 404 (a rota também não casa); `HEAD`/`OPTIONS` -> 405 sem ler corpo; query string não faz parte de `scope["path"]`; id não numérico ou gigante entra no guarda (401 sem ler). **`root_path="/gw"` com `path="/gw/api/v1/..."` (como o uvicorn monta com `--root-path`, `h11_impl.py:206`; e como um `Mount` mantém o path completo) NÃO casa**: o guarda é ignorado e o Starlette roteia normalmente (`get_route_path` remove o prefixo). Medido com o app real e JWT válido: corpo de 25 MiB **inteiro consumido** (26 214 505 bytes) contra 10 551 392 com o guarda; também ficam sem efeito o rate limit e o teto de simultâneos |
| **Middleware: paridade de JWT** | **Idêntico** | `authenticate_bearer` usa a mesma `decode_access_token` e `get_authorization_scheme_param`. Comparei 19 formas de cabeçalho com `HTTPBearer` + `decode_access_token`: `bearer`/`BEARER`/dois espaços ok nos dois; sem credencial, `Basic`, tabulação, texto extra, vazio, `alg=none`, HS512, expirado, `nbf` futuro, `aud` errado, `token_type` errado, `sub` não string, lixo, espaço inicial, não ASCII rejeitados nos dois; cabeçalhos `Authorization` duplicados: ambos usam o primeiro. O 401 do guarda tem o mesmo corpo e `WWW-Authenticate: Bearer`; usuário inativo/inexistente (JWT válido) passa pelo guarda e leva 401 na dependency |
| **Middleware: corpo nunca lido antes de 401/429** | **Provado** | ASGI com o app real: anônimo, JWT inválido e 429 por rate limit consumiram **0 bytes** de `receive`. **uvicorn real**: anônimo e token ruim com 5 MiB -> 401 com `size_upload=0`; 2ª requisição do mesmo usuário (limite 1/min) -> 429 `Retry-After: 60` com `size_upload=0`; cabeçalho `x-request-id` presente nas respostas antecipadas (conferido em 413 e 429 reais). JWT válido de usuário inexistente: o guarda deixa passar e a dependency recusa **depois** de ler (5 242 985 bytes): residual documentado |
| **Middleware: corpo limitado** | **Ok** | `Content-Length` declarado de 1e9 -> 413 com 0 bytes lidos; chunked de 25 MiB -> 413 com 10 551 392 bytes (teto + folga + um bloco); `Content-Length: 100` falso com corpo de 25 MiB -> 413 com os mesmos 10 551 392; no uvicorn real, chunked de 30 MiB -> 413 após ~14 MB enviados (buffers de socket). `http.disconnect` no meio do corpo: resposta 400 descartada e vaga liberada. Sem resposta dupla (mutação sem o descarte do 400 do FastAPI morta; mutação do teto x10 e do guarda de `Content-Length` mortas). Mensagens sem `body` e `more_body` tratados. Exceção do app: relançada se não for o estouro; engolida só quando o estouro causou o erro. Sem arquivo temporário residual em `/tmp` depois dos probes |
| **Middleware: ordem com `RequestContextMiddleware`** | **Ok** | `add_middleware(UploadGuardMiddleware)` primeiro, `RequestContextMiddleware` depois: o contexto fica por fora, então as respostas antecipadas (401/413/429) levam `X-Request-ID` (visto em 413/429 reais). Exceções não tratadas passam pelo guarda e viram 500 do `RequestContextMiddleware` |
| **F04: limitador** | **Correto** | `SlidingWindowLimiter` com instâncias separadas (`upload_limiter`, `workspace_create_limiter`, `limiter`); chave por usuário (`upload:user:{id}`, `workspace-create:user:{id}`); só registra o evento quando permitido; `Retry-After >= 1`. Mutações: chave compartilhada (upload, simultâneos, criação), janela minúscula (upload, criação), rate limit desligado, sem rejeição, `Retry-After` 0: **todas mortas**. Defeitos: R02, R06, R07 |
| **F04: vaga de simultâneos liberada exatamente uma vez** | **Ok** | Adquirida só no caminho que não faz retorno antecipado; liberada no `finally`. Provado com o app real e o banco: sucesso, desconexão no meio do corpo, cancelamento de duas requisições e 429 do terceiro (sem leitura do corpo) terminam com `active == 0`. Mutações sem liberar e liberando duas vezes: mortas |
| **F04: cota por workspace** | **Correta** | Pré-checagem antes do I/O (sem blob) e checagem autoritativa sob `FOR UPDATE` do workspace dentro do mesmo `lock_timeout`; `count + 1 > máx` e `used + size > máx` (exatamente no limite é aceito). Mutações: sem `FOR UPDATE` (corrida) morta por `test_race_on_document_count_only_one_fits`; sem pré-checagem, `count` off-by-one e bytes sem `size`: mortas. A contagem vem das linhas, então **exclusão libera cota** (estrutural; não há teste dedicado, R06). Blobs órfãos não contam (reconciliação) |
| **F04: ordem de locks e deadlock** | **Sem deadlock encontrado** | Upload: membership `FOR SHARE` -> workspace `FOR UPDATE` -> `INSERT` (`KEY SHARE` em `workspaces`/`users`). Delete de documento: só a linha do documento, sem lock do workspace. Criação de workspace: usuário `FOR UPDATE` -> `INSERT` em linhas novas. Nenhum caminho adquire os locks em ordem inversa; criação espera, no máximo, o commit de uploads em andamento do mesmo usuário. Estresse (60 uploads de 2 usuários, alternância de papel, 60 exclusões e 6 criações de workspace simultâneos, banco real): 0 respostas 500, sem travamento |
| **F04: teto de workspaces por dono** | **Correto** | `FOR UPDATE` na linha do usuário antes de contar; criações concorrentes do mesmo usuário se serializam (`test_concurrent_creations_cannot_exceed_owned_limit`). Mutações sem o lock e com off-by-one: mortas |
| **F04: 401 antes de 429 em `POST /workspaces`** | **Ok** | `workspace_create_rate_limit` depende de `get_current_user`; `test_rate_limit_runs_after_authentication`. No upload, JWT inválido não consome o limite (`test_invalid_jwt_does_not_consume_rate_limit`) |
| **F04: chaves de desligamento e isolamento de testes** | **Ok, com lacuna R02** | `conftest.py` desliga tudo por variável de ambiente e zera os 4 limitadores antes/depois de cada teste; os testes de F04 religam explicitamente. Isso **mascara os padrões**: virar `upload_limits_enabled`, `workspace_create_rate_limit_enabled`, `workspace_max_documents` ou `upload_max_concurrent_per_user` do padrão seguro para desligado/enorme **sobrevive à suíte inteira** (R02). Teto de simultâneos ignorando a chave de desligamento também sobrevive (R06) |
| **Aviso "por processo"** | **Documentado** | ADR 0008, ADR 0009, `docs/api/documents.md`, `docs/api/workspaces.md`, README e docstring do `upload_guard.py` |
| **Docs** | **Fiéis, com 2 defeitos (R05)** | README, `docs/api/*` e as tabelas de padrões do ADR 0009 conferem com `config.py` e os handlers (413 de cota, 429, 403 de limite, `Retry-After`). Aprovações do owner de 2026-11-12 registradas (seção 9). Defeitos: linha obsoleta em ADR 0008 "Fora de escopo" e período emendado de forma truncada no ADR 0009 (bullet TOCTOU) |
| **Regressões** | **Nenhuma** | Suíte completa verde; comportamento anterior de 413/401/404/403 preservado; tamanho exato no limite ainda aceito |

### 12.3 Resultado das mutações desta rodada

Mortas (por suíte focada em upload, quota, limites, conexão, storage, layering e API): N01 (2), N02b, N03 (2), vaga sem liberar, vaga liberada duas vezes, sem `FOR UPDATE` do workspace, sem pré-checagem, sem `FOR UPDATE` do usuário, `count` off-by-one, bytes sem `size`, chave compartilhada (rate, simultâneos, criação), teto de corpo x10, sem 401 no guarda, sem rate limit, sem descarte do 400, sem guarda de `Content-Length`, janelas minúsculas (upload, criação), `Retry-After` 0, rate de criação sem rejeição, off-by-one do teto de workspaces. **Sobreviveram**: N02a (`is_local=False` no upload) e N02c (idem no usuário) (R03); padrões de configuração invertidos (R02); teto de simultâneos ignorando a chave de desligamento (R06).

### 12.4 Novos achados

| ID | Severidade | Achado | Evidência | Correção recomendada |
| --- | --- | --- | --- | --- |
| R01 | **Médio (condicional)** | O guarda casa o path em `scope["path"]`, não no path de rota. Com `root_path` (uvicorn `--root-path`, ASGI >= 2.4) ou app montado sob `Mount`, `scope["path"]` inclui o prefixo, o regex não casa e o guarda **falha aberto** em silêncio: sem checagem de JWT, sem teto de corpo, sem rate limit, sem teto de simultâneos (volta o F01/G02). A aplicação hoje não define `root_path` e nada no repositório usa `--root-path`; sem teste nem aviso na documentação | `backend/app/api/upload_guard.py:53,120`; probe: 25 MiB consumidos por inteiro com `root_path="/gw"` contra 10,5 MiB sem prefixo; `uvicorn/protocols/http/h11_impl.py:206`; `starlette/_utils.py:137` (`get_route_path`) | Casar no path sem o `root_path` (`scope["path"].removeprefix(scope.get("root_path", ""))`, ou aceitar prefixo opcional) e adicionar teste com `root_path`/`Mount`; até lá, documentar "não usar `--root-path`/mount" |
| R02 | Baixo | Os **padrões** de F04 não são testados: o `conftest.py` força `UPLOAD_LIMITS_ENABLED=false` e `WORKSPACE_CREATE_RATE_LIMIT_ENABLED=false` no ambiente e nenhum teste lê os valores padrão. Trocar para `False`, `1_000_000_000` ou `1000` simultâneos sobrevive à suíte; um commit assim desligaria F04 sem aviso | `backend/app/core/config.py:131-140`; `backend/tests/conftest.py:26-28` | Teste de `Settings(_env_file=None)` com o ambiente limpo, assertando `True`/20/2/1000/1 GiB/10/`True`/10 |
| R03 | Baixo | Nenhum teste prova que o `lock_timeout` é local à transação: `set_config(..., False)` vazaria 5 s para a conexão do pool e sobrevive à suíte. O comportamento atual está correto (sondagem) | `backend/app/services/document.py:98-104`; `backend/app/repositories/user.py:202-204` | Teste com `pool_size=1`: após um upload/criação, `SHOW lock_timeout` na mesma conexão == `0` |
| R04 | Informativo | `services/document.py` ainda importa `fastapi.UploadFile`; o teste de camadas só proíbe `app.api` e `HTTPException`, então um `Response`/`Request` do FastAPI passaria. Não há semântica HTTP no serviço hoje | `backend/app/services/document.py:16`; `backend/tests/unit/test_service_layering.py:19-28` | Opcional: receber um leitor assíncrono (`read`) em vez de `UploadFile`, ou ampliar o teste para `fastapi`/`starlette` com exceção explícita |
| R05 | Informativo | Documentação: (a) ADR 0008, "Fora de escopo", ainda diz que rate limit nas rotas de workspace e documentos está adiado, contradizendo a seção "Limites de criação" do mesmo ADR; (b) ADR 0009, bullet TOCTOU: a oração sobre `lock_timeout` foi emendada no meio da frase anterior e "(a revogação não confirma entre a leitura e o commit)" ficou fora de lugar | `docs/decisions/0008-workspace-bootstrap-and-authorization.md:45`; `docs/decisions/0009-document-local-storage.md` (bullet "TOCTOU da autorização") | Remover/atualizar a linha; reescrever o período |
| R06 | Informativo | Lacunas pequenas: (a) o teto de simultâneos ignora `UPLOAD_LIMITS_ENABLED=false` sem que algum teste note (mutação sobrevive); (b) "exclusão libera cota" é afirmado no ADR, mas sem teste; (c) `scope["state"]["upload_user_id"]` é gravado e nunca lido, e o parâmetro `scope` de `enforce_upload_rate_limit` não é usado; (d) timeout do `FOR UPDATE` do workspace é registrado com `stage=database`, não `membership_lock` | `backend/app/api/upload_guard.py:91,134,136`; `backend/app/services/document.py:108-119` | Testes/limpeza opcionais |
| R07 | Informativo | O limitador recusa chave **nova** quando há 4096 chaves ativas (`_max_keys`); com janela de 3600 s em `workspace_create_limiter`, 4096 usuários distintos criando workspace em uma hora fariam novos usuários receberem 429 até a janela expirar (exige 4096 contas; por processo; registra warning) | `backend/app/core/rate_limit.py:340-346`; `backend/app/api/dependencies/rate_limit.py:479` | Aceitável no MVP; monitorar o log e mover para store compartilhado/proxy em produção |
| R08 | Informativo | `FOR UPDATE` na linha de `users` é o lock mais forte e conflita com o `FOR KEY SHARE` de FK de uploads em andamento do mesmo usuário; `FOR NO KEY UPDATE` bastaria. Efeito: criar workspace pode esperar até o commit (curto) de um upload do mesmo usuário e, passados 5 s, falha com 500 genérico. Sem deadlock (estresse) | `backend/app/repositories/user.py:206` | Opcional: `with_for_update(key_share=True)` |

### 12.5 Veredito final

**Aprovada com ressalvas; nada bloqueia o merge da Fase 3 (escopo MVP/estudo local).** N01, N02, N03, G01 e F04 estão corrigidos e verificados por mutação e por execução real; F01 caiu para residual (autenticado sem membership/inativo, mais R01 sob `root_path`/mount). Nenhum Crítico ou Alto. Recomendo, no mesmo PR ou imediatamente depois, a correção de R01 (poucas linhas) e os testes R02/R03; R04-R08 são opcionais. Para produção: limite de corpo no proxy, limites compartilhados ou no proxy com vários workers, reconciliação operacionalizada, e as pendências listadas na seção 9.

## 13. Revalidação 4 (encerramento) — commits `9b9727f`..`fcdeddf`, HEAD `fcdeddf`

Mesmas regras: só este arquivo foi alterado por mim; mutações revertidas e probes removidos (`git status` limpo; banco de teste sem resíduos).

### 13.1 Validação (HEAD `fcdeddf`)

| Comando | Resultado |
| --- | --- |
| `ruff check .` / `ruff format --check .` (raiz) | `All checks passed!` / `156 files already formatted` |
| `POSTGRES_PORT=1 POSTGRES_DB=nexus_ai_test pytest -m "not integration" -q` | **336 passed**, 227 deselected, 1 warning |
| `POSTGRES_DB=nexus_ai_test pytest -q` | **563 passed**, 1 warning |
| `POSTGRES_DB=nexus_ai_test alembic check` | `No new upgrade operations detected.` |
| `gh run list` | run `43306801953`, head `fcdeddf`: `test` e `unit` **success** (1 min); o anterior (`43305711426`) também success |

### 13.2 Status por achado

| ID | Status | Verificação |
| --- | --- | --- |
| R01 | **Corrigido** | `_route_path` remove o `root_path` só em fronteira de segmento e o regex aceita prefixo opcional (`^(?:/.*)?/api/v1/workspaces/[^/]+/documents$`). Probe ASGI com o app real (corpo de 64 KiB x 40, sem JWT): `root=/gw` com path prefixado e sem prefixo, `root=/api` com `/api/api/v1/...`, `root=""` com `/prefix/api/...`, `root=/pre` com `/preX/api/...` e `root=/gw/` (barra final): todos 401 com **0 bytes lidos**. Com JWT válido e corpo de 25 MiB: `root_path=/gw` -> 413 com **10 551 392** bytes (antes: 26 214 505), igual ao caso sem prefixo. Não dispara em outras rotas: `POST /api/v1/workspaces/1/documents/2` e `POST /api/v1/health` -> 405 sem ler corpo; `GET` sob prefixo -> 401 da própria rota, não do guarda. Efeito colateral inofensivo: um path com prefixo que o roteador responderia 404 recebe 401 do guarda (fail-safe). Mutações: remover o prefixo do regex **e** o `_route_path` ao mesmo tempo: morta (3 testes); cada um isolado sobrevive por redundância deliberada (um cobre o outro); remover a fronteira de segmento é equivalente com o regex de prefixo aberto. Testes com `root_path` e `Mount` reais |
| R02 | **Corrigido** | `tests/test_config.py::test_phase3_limits_have_secure_defaults`: as 4 mutações de padrão (limites desligados, rate de criação desligado, 1e9 documentos, 1000 simultâneos) são **mortas** |
| R03 | **Corrigido** | Testes com pool de 1 conexão (`test_upload_lock_timeout_does_not_leak_to_pooled_connection`, `test_create_workspace_lock_timeout_does_not_leak_to_pooled_connection`): `is_local=False` no upload e no usuário **mortas** |
| R04 | **Corrigido** | `DocumentService` usa o `Protocol` `UploadSource`; nenhum import de `fastapi`/`starlette` em `app/services`. O teste de camadas agora proíbe frameworks HTTP: importar `fastapi.Response` em serviço é **morto**; `starlette` em serviço quebra a coleção |
| R05 | **Corrigido** | ADR 0008 "Fora de escopo" reescrito (store compartilhado; upload/criação já têm rate limit); bullet TOCTOU do ADR 0009 reescrito de forma coerente |
| R06 | **Corrigido** | Teto de simultâneos respeita `UPLOAD_LIMITS_ENABLED` (mutação morta por `test_concurrent_cap_respects_disable_switch`); `upload_user_id` e o parâmetro `scope` removidos; timeout do lock do workspace agora é `stage=workspace_lock` (mutação morta por `test_workspace_lock_timeout_is_logged_with_its_own_stage`); teste de cota após exclusão acrescentado ao suíte de cota |
| R07 | **Documentado** | ADR 0009 descreve o teto de 4096 chaves por instância (chave nova recusada, warning); comportamento inalterado, aceitável no MVP |
| R08 | **Corrigido, serialização preservada** | `with_for_update(key_share=True)` (`FOR NO KEY UPDATE`) em usuário e workspace. Mutações: remover o lock do usuário, trocá-lo por `FOR KEY SHARE`, remover o lock do workspace e trocá-lo por `FOR KEY SHARE`: **todas mortas** por `test_concurrent_creations_cannot_exceed_owned_limit` e `test_race_on_document_count_only_one_fits` (`FOR NO KEY UPDATE` ainda conflita com ele mesmo, então as corridas de cota e de teto continuam serializadas). Estresse com banco real (60 uploads, alternância de papel, exclusões, criações de workspace): 0 respostas 500, sem deadlock (201/204/403) |

### 13.3 Observação (não é achado novo)

`POST /api/v1/workspaces` (e login/cadastro) leem o corpo JSON antes da autenticação, sem teto próprio (medi 2,6 MiB consumidos por requisição anônima no probe); é comportamento pré-existente das rotas JSON, fora do escopo de Documents. Cobrir com limite de corpo no proxy (já listado para produção).

### 13.4 Veredito final

**Fase 3 aprovada para encerramento.** Nenhum achado novo; R01-R08 resolvidos e reverificados por mutação e execução real; CI verde no HEAD `fcdeddf`. Permanecem apenas os itens de produção listados na seção 9.
