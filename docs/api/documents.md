# Contrato de documentos

Por ora só o upload. As consultas e a exclusão chegam em etapas seguintes. Exige `Authorization: Bearer <access_token>` (ver [Usuários](users.md#usuário-atual)).

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
