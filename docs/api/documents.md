# Contrato de documentos

Upload, listagem, consulta e exclusão. Exige `Authorization: Bearer <access_token>` (ver [Usuários](users.md#usuário-atual)).

## `POST /api/v1/workspaces/{workspace_id}/documents`

`multipart/form-data` com um único campo `file` (`UploadFile`). Não há JSON nem base64.

Fluxo: JWT, membership e permissão `document:upload` (só `owner` e `admin`), validação, gravação no storage, criação do `Document` com `status="uploaded"` e `commit`. A autorização roda antes de qualquer escrita no storage. O dono (`uploaded_by`) é o usuário autenticado; `workspace_id` vem da URL.

### Regras de validação

| Item | Regra |
| --- | --- |
| Tipos | `.pdf` (`application/pdf`), `.txt` (`text/plain`), `.md` e `.markdown` (`text/markdown`). |
| `mime_type` gravado | Sempre derivado da extensão. O `Content-Type` do cliente nunca é gravado; só é recusado quando contradiz a extensão (`application/octet-stream` e ausente são aceitos). |
| PDF | Deve começar com `%PDF-` (verificação inicial apenas, não garante um PDF íntegro). |
| TXT/MD | UTF-8 estrito (decodificação incremental, inclusive com sequências multibyte entre blocos); byte NUL é rejeitado. |
| Vazio | Rejeitado (422). |
| Tamanho | Até 10 MiB (10 485 760 bytes), contados durante a leitura em blocos de 64 KiB; passou do limite, a gravação é abortada. |
| Nome | Normalizado em NFC; removidos caracteres de controle/formatação e componentes de diretório (`/` e `\`); máximo de 255 caracteres (extensão preservada); resultado vazio ou só pontos é rejeitado. O nome nunca forma o caminho no disco. |

### Respostas

| Status | Quando | Corpo |
| --- | --- | --- |
| 201 | Criado | `DocumentResponse` (`id`, `workspace_id`, `filename`, `mime_type`, `size_bytes`, `status`, `uploaded_by`, `created_at`, `metadata`) |
| 401 | Token ausente ou inválido | `{"detail": "Não autenticado."}` |
| 403 | Membro com papel `member` ou `viewer` | `{"detail": "Permissão insuficiente."}` |
| 404 | Workspace inexistente ou sem membership | `{"detail": "Workspace não encontrado."}` |
| 413 | Arquivo acima de 10 MiB | `{"detail": "Arquivo excede o tamanho máximo de 10 MiB."}` |
| 415 | Extensão fora da lista ou Content-Type incompatível | `{"detail": "Tipo de arquivo não suportado."}` |
| 422 | Campo `file` ausente, nome inválido, arquivo vazio ou conteúdo incompatível com o tipo | `{"detail": "Arquivo inválido."}` ou lista de validação sem `input` |
| 500 | Falha de storage ou banco | `{"detail": "Erro interno do servidor."}` |

A resposta nunca contém a chave do storage nem caminhos. Mensagens de erro são genéricas.

### Armazenamento e consistência

O blob fica no diretório configurado por `DOCUMENT_STORAGE_DIR` (fora de pastas públicas e do Git), com nome aleatório gerado no servidor (32 hex), gravado em temporário no mesmo filesystem e publicado com `os.replace`. Postgres e filesystem não compartilham transação: o blob é gravado primeiro; se a persistência falhar, há rollback e o blob é removido. Um crash entre os dois passos pode deixar um blob órfão (reconciliação futura).

### Limite no nível da requisição

O Starlette lê o multipart para arquivo temporário antes da rota rodar. Um guarda recusa com 413, sem ler o corpo, requisições cujo `Content-Length` declarado supere o limite mais uma folga de 64 KiB para o multipart. Corpos sem `Content-Length` (chunked) não são barrados aí; o limite exato continua valendo no storage. Um proxy reverso deve limitar o corpo também.

## `GET /api/v1/workspaces/{workspace_id}/documents`

Lista os documentos do workspace. Qualquer papel (`owner`, `admin`, `member`, `viewer`) pode ler.

Query: `limit` (1 a 100, padrão 20) e `offset` (>= 0, até 2 147 483 647). Fora da faixa, 422. Ordem fixa: `created_at` decrescente, desempate por `id` decrescente (paginação determinística). `total` conta só os documentos deste workspace.

```json
{"items": [ /* DocumentResponse */ ], "total": 0, "limit": 20, "offset": 0}
```

## `GET /api/v1/workspaces/{workspace_id}/documents/{document_id}`

Retorna um `DocumentResponse`. `document_id` deve estar entre 1 e 2 147 483 647 (senão 422). A busca é sempre por workspace **e** id: um documento de outro workspace responde 404 com o mesmo corpo de um documento inexistente (`{"detail": "Documento não encontrado."}`), sem nenhum metadado. Quem não é membro do workspace recebe 404 (`{"detail": "Workspace não encontrado."}`).

## `DELETE /api/v1/workspaces/{workspace_id}/documents/{document_id}`

Exige a permissão `document:delete` (`owner` e `admin`). Resposta 204 sem corpo.

| Status | Quando |
| --- | --- |
| 204 | Documento excluído |
| 401 | Token ausente ou inválido |
| 403 | Papel `member` ou `viewer` (nada é alterado) |
| 404 | Sem membership, documento inexistente ou de outro workspace (nada é alterado) |
| 422 | Id fora da faixa |
| 500 | Falha ao confirmar a exclusão no banco (`{"detail": "Erro interno do servidor."}`) |

Os status das consultas são os mesmos (200, 401, 404, 422, 500); 403 não se aplica a leitura.

### Política de exclusão (NÃO é atômica)

Postgres e filesystem não compartilham transação. Ordem: carregar o documento no workspace, remover a linha, `commit`, e só então remover o blob.

- Falha no `commit`: rollback, blob intacto, 500 genérico.
- Blob já ausente: 204 e um warning no log (sem chave, caminho ou nome).
- Falha ao remover o blob depois do `commit`: responde **204** (a exclusão lógica, que o cliente pediu, aconteceu e não pode ser desfeita) e registra `error stage=blob_cleanup` com `request_id` e só o tipo da exceção. O blob fica órfão no disco até a reconciliação.

### Reconciliação

`app/services/document_reconciliation.py` oferece `find_orphan_blobs`, `find_stale_tmp` e `reconcile_orphans(session, storage, dry_run=True, ...)`. Remove blobs sem linha em `documents` e temporários `.tmp/*.part` antigos. Salvaguardas: `dry_run` é o padrão; só blobs com mais de 1 h (`min_age_seconds`) são candidatos, para não confundir com um upload em andamento (blob publicado antes do commit da linha); a existência da linha é consultada no banco antes de remover; a varredura usa descritores com `O_NOFOLLOW`, ignora symlinks e nomes fora do formato e nunca sai do diretório do storage. Não há CLI nem agendador: precisa ser executada manualmente ou agendada em fase futura.
