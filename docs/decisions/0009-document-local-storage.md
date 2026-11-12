# ADR 0009: armazenamento local de documentos

## Problema

Documentos enviados precisam de um destino de bytes e de metadados no PostgreSQL. Postgres e filesystem não compartilham transação, então é preciso decidir formato de chave, segurança de caminho, limites, validação de conteúdo, ordem de operações e como tratar falhas parciais.

## Opções

- Guardar o conteúdo no PostgreSQL (`bytea`/large object), em filesystem local ou em object storage.
- Chave derivada do nome do arquivo ou chave aleatória gerada no servidor.
- Abstrair o storage por um `Protocol` já agora ou só quando houver um segundo backend.

## Decisão

- **Filesystem local** em `DOCUMENT_STORAGE_DIR` (variável de ambiente; padrão `backend/var/documents`, fora do Git). Sem object storage no MVP.
- **Chave e layout.** A chave tem 32 hex minúsculos (`secrets.token_hex(16)`), gerada no servidor e nunca derivada do nome do arquivo. O blob vai para `<root>/<2 primeiros hex>/<chave>`; gravações em andamento ficam em `<root>/.tmp/<32 hex>.part`. A chave é validada por regex antes de qualquer caminho existir. Diretórios são criados com modo `0700` e arquivos com `0600`.
- **Gravação.** Os blocos (64 KiB) vão para o temporário, com `fsync`, e são publicados **sem sobrescrita**: `os.link` do temporário para a chave final (mesmo filesystem, atômico; falha com `FileExistsError` se o destino existe), `fsync` do diretório do shard e remoção do temporário. Em colisão de chave sorteia-se outra, até 3 tentativas; esgotadas, `StorageError`. `os.replace` não é usado porque sobrescreveria silenciosamente um blob existente. Falha em qualquer ponto remove o temporário (e o link recém-criado se o `fsync` falhar). Requer filesystem com hard links.
- **Segurança de caminho.** Os acessos usam descritores de diretório (`dir_fd`) e `O_NOFOLLOW`/`O_DIRECTORY`; symlink no shard, no `.tmp` ou no arquivo é recusado (`StorageError`), sem corrida TOCTOU. O diretório raiz é configurado pelo operador e pode ser symlink. Mensagens de erro e logs não carregam caminhos.
- **Limite de 10 MiB com streaming.** O corpo é lido em blocos e a gravação aborta (`DocumentTooLargeError`, 413) ao passar de 10 485 760 bytes; exatamente 10 MiB é aceito.
- **Formatos e conteúdo.** Aceitos: `.pdf`, `.txt`, `.md`/`.markdown`. PDF: só se confere o cabeçalho `%PDF-` (verificação superficial, **não** valida a estrutura). TXT/MD: UTF-8 estrito (decodificador incremental, bytes NUL rejeitados). Arquivo vazio é 422.
- **Mime derivado no servidor.** O `mime_type` gravado vem da extensão do nome sanitizado. O `Content-Type` do cliente nunca é gravado; só é rejeitado (415) quando contradiz a extensão (vazio ou `application/octet-stream` são tolerados). O nome é normalizado (NFC), sem caracteres de controle/formatação e sem diretórios, e serve só para exibição.
- **FK `ON DELETE RESTRICT`** (aprovada pelo owner em 2026-11-12). `documents.workspace_id` e `documents.uploaded_by` usam `RESTRICT`: apagar workspace ou usuário com documentos falha em vez de cascatear e deixar blobs órfãos. A remoção de documentos é um fluxo explícito do serviço.
- **Upload com compensação (não ACID).** Ordem: validar, **encerrar a transação de leitura da autorização** (`commit` no início do serviço, devolvendo a conexão ao pool antes do I/O de até 10 MiB; sem isso cada upload lento prenderia uma conexão), gravar o blob, reler membership/permissão na transação de escrita, `INSERT` + `commit`.
  - *TOCTOU da autorização.* As dependencies autorizam antes do I/O; a decisão pode estar velha quando o blob termina de ser gravado. A releitura usa `FOR SHARE` na linha de membership, com `lock_timeout` de 5 s (`MEMBERSHIP_LOCK_TIMEOUT_MS`, definido por `set_config(..., true)`, vale só na transação); estourar o tempo é falha anterior ao commit (rollback, blob removido, 500, `stage=membership_lock`) (a revogação não confirma entre a leitura e o commit) e `populate_existing` (ignora a instância antiga do identity map). Revogada no meio: mesmas respostas das dependencies (404 sem membership, 403 sem `document:upload`), sem linha, e o blob é removido (nenhuma linha foi confirmada, então é seguro).
  - *Classificação de falhas.* Falha **antes** do commit (storage, releitura, `flush`/`INSERT`, cancelamento): `rollback` e remoção do blob. Exceção levantada **pelo próprio `commit`**: resultado **incerto** (o Postgres pode ter confirmado e a conexão caído antes do ack); o blob **não** é removido (evita linha sem arquivo), faz-se `rollback` best-effort, `error stage=commit_uncertain` e 500. Se o commit realmente falhou, o blob órfão é recolhido pela reconciliação (grace de 1 h, nunca remove blob com linha). Logo, um 500 no upload não prova que o documento não existe.
  - Um crash do processo entre o blob e o commit **pode deixar blob órfão**. Logs trazem só `stage`, `request_id` e o tipo da exceção.
- **Política de exclusão.** O serviço apaga a linha e faz `commit`; só depois remove o blob. Falha no commit: `rollback`, blob intacto, 500 (resultado incerto: a linha pode ter sido removida mesmo assim). Blob já ausente: 204 com warning. Falha ao remover o blob após o commit: 204 (a exclusão lógica ocorreu; decisão aprovada pelo owner em 2026-11-12) e erro `stage=blob_cleanup` no log; o blob fica órfão até a reconciliação. **A exclusão não é atômica** entre Postgres e filesystem.
- **Reconciliação.** `app/services/document_reconciliation.py` (`find_orphan_blobs`, `find_stale_tmp`, `reconcile_orphans`) detecta e remove blobs sem linha e temporários `.part` antigos. `dry_run=True` é o padrão; só atua em arquivos com mais de 1 h (`min_age_seconds`), para não confundir upload em andamento com órfão; nunca remove blob com linha em `documents`; ignora symlinks e nomes fora do formato. **Ainda não há CLI nem agendador**; a execução é manual.
- **Multipart, JWT e corpo (middleware ASGI).** O Starlette grava o multipart em arquivo temporário (acima de 1 MiB) antes das dependencies rodarem. Por isso `app/api/upload_guard.py` (ASGI puro, só API pública; sem `request._receive`) atua somente em `POST /api/v1/workspaces/{id}/documents` (path casado por regex; qualquer outra rota ou método passa intacto) e, **antes de ler qualquer byte do corpo**: (1) `Content-Length` declarado acima de 10 MiB + 64 KiB: 413; (2) valida o Bearer JWT sem banco (mesma `decode_access_token` de `get_current_user`): ausente ou inválido, 401 idêntico ao de `get_current_user`, sem spool; (3) gancho `enforce_upload_rate_limit(user_id, scope)` (hoje sem efeito; ali entrará o rate limit por usuário); (4) conta os bytes recebidos e aborta com 413 ao passar do mesmo teto (corpos chunked ou `Content-Length` falso), descartando qualquer resposta do app e sem enviar duas respostas. **Ressalva:** requisições anônimas ou com token inválido são recusadas antes de qualquer leitura, mas um usuário autenticado **sem membership** (ou sem papel) ainda pode fazer o servidor gravar até ~10 MiB por requisição até a checagem de membership; o mitigador planejado é o rate limit por usuário nesse gancho. **Recomendação mantida:** impor também um limite de corpo no proxy reverso (por exemplo, pouco acima de 10 MiB nas rotas de upload).
- **`metadata` JSONB é público** (aprovado pelo owner em 2026-11-12). A coluna `metadata` é devolvida ao cliente; nada interno (chave de storage, caminhos, hashes) pode ser gravado nela. A chave de storage não faz parte de `DocumentResponse`.

## Trade-offs

- Sem transação distribuída, existem janelas de inconsistência (crash no upload, falha pós-commit no delete). São toleradas porque o dano é blob órfão, nunca linha apontando para blob de outro tenant, e a reconciliação recupera o espaço.
- A checagem de PDF é só de cabeçalho: um arquivo malformado ou malicioso com `%PDF-` é aceito.
- Filesystem local não escala horizontalmente (vários processos precisam do mesmo volume) e não tem criptografia em repouso própria.
- O middleware elimina o spool de requisições anônimas ou com JWT inválido, mas um usuário autenticado sem membership ainda causa até ~10 MiB de spool por requisição até a checagem no banco; a concorrência desses uploads só será limitada pelo rate limit por usuário (a implementar) e pelo proxy.

## Trabalho futuro

- Introduzir um `Protocol` de storage só quando existir um segundo backend (hoje seria camada sem uso).
- Agendar a reconciliação e/ou expor CLI.
- Validação mais profunda de PDF (estrutura, extração) na Fase 4.
- Limite de corpo no proxy e rate limit por usuário no upload (gancho `enforce_upload_rate_limit`).
