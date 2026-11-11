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
- **Gravação.** Os blocos (64 KiB) vão para o temporário, com `fsync`, e são publicados com `os.replace` (mesmo filesystem, atômico) seguido de `fsync` do diretório do shard. Falha em qualquer ponto remove o temporário. Cada chave é nova: nomes iguais nunca sobrescrevem.
- **Segurança de caminho.** Os acessos usam descritores de diretório (`dir_fd`) e `O_NOFOLLOW`/`O_DIRECTORY`; symlink no shard, no `.tmp` ou no arquivo é recusado (`StorageError`), sem corrida TOCTOU. O diretório raiz é configurado pelo operador e pode ser symlink. Mensagens de erro e logs não carregam caminhos.
- **Limite de 10 MiB com streaming.** O corpo é lido em blocos e a gravação aborta (`DocumentTooLargeError`, 413) ao passar de 10 485 760 bytes; exatamente 10 MiB é aceito.
- **Formatos e conteúdo.** Aceitos: `.pdf`, `.txt`, `.md`/`.markdown`. PDF: só se confere o cabeçalho `%PDF-` (verificação superficial, **não** valida a estrutura). TXT/MD: UTF-8 estrito (decodificador incremental, bytes NUL rejeitados). Arquivo vazio é 422.
- **Mime derivado no servidor.** O `mime_type` gravado vem da extensão do nome sanitizado. O `Content-Type` do cliente nunca é gravado; só é rejeitado (415) quando contradiz a extensão (vazio ou `application/octet-stream` são tolerados). O nome é normalizado (NFC), sem caracteres de controle/formatação e sem diretórios, e serve só para exibição.
- **FK `ON DELETE RESTRICT`.** `documents.workspace_id` e `documents.uploaded_by` usam `RESTRICT`: apagar workspace ou usuário com documentos falha em vez de cascatear e deixar blobs órfãos. A remoção de documentos é um fluxo explícito do serviço.
- **Upload com compensação (não ACID).** Ordem: validar, gravar o blob, `INSERT` + `commit`. Se a persistência falhar (ou a requisição for cancelada), há `rollback` e o blob é removido; falha de storage não cria linha. Um crash do processo entre o blob e o commit **pode deixar blob órfão**. Logs trazem só `stage`, `request_id` e o tipo da exceção.
- **Política de exclusão.** O serviço apaga a linha e faz `commit`; só depois remove o blob. Falha no commit: `rollback`, blob intacto, 500. Blob já ausente: 204 com warning. Falha ao remover o blob após o commit: 204 (a exclusão lógica ocorreu) e erro `stage=blob_cleanup` no log; o blob fica órfão até a reconciliação. **A exclusão não é atômica** entre Postgres e filesystem.
- **Reconciliação.** `app/services/document_reconciliation.py` (`find_orphan_blobs`, `find_stale_tmp`, `reconcile_orphans`) detecta e remove blobs sem linha e temporários `.part` antigos. `dry_run=True` é o padrão; só atua em arquivos com mais de 1 h (`min_age_seconds`), para não confundir upload em andamento com órfão; nunca remove blob com linha em `documents`; ignora symlinks e nomes fora do formato. **Ainda não há CLI nem agendador**; a execução é manual.
- **Multipart e Content-Length.** O Starlette grava o multipart em arquivo temporário **antes** da rota (e da autenticação) rodar, então um cliente não autorizado ainda consome disco/CPU até o limite do servidor. Mitigação parcial: um guarda na rota recusa com 413, sem ler o corpo, requisições cujo `Content-Length` declarado exceda 10 MiB mais 64 KiB de folga e, para corpos sem `Content-Length` (chunked) ou com tamanho declarado falso, conta os bytes recebidos e aborta a leitura com 413 ao passarem desse mesmo teto. O spool anterior à autenticação continua acontecendo, mas fica limitado a cerca de 10 MiB mais 64 KiB por requisição; mover a autenticação para antes do parsing do multipart é uma decisão arquitetural em aberto do dono. **Recomendação:** impor também um limite de corpo no proxy reverso (por exemplo, pouco acima de 10 MiB nas rotas de upload).
- **`metadata` JSONB é público.** A coluna `metadata` é devolvida ao cliente; nada interno (chave de storage, caminhos, hashes) pode ser gravado nela. A chave de storage não faz parte de `DocumentResponse`.

## Trade-offs

- Sem transação distribuída, existem janelas de inconsistência (crash no upload, falha pós-commit no delete). São toleradas porque o dano é blob órfão, nunca linha apontando para blob de outro tenant, e a reconciliação recupera o espaço.
- A checagem de PDF é só de cabeçalho: um arquivo malformado ou malicioso com `%PDF-` é aceito.
- Filesystem local não escala horizontalmente (vários processos precisam do mesmo volume) e não tem criptografia em repouso própria.
- O guarda de corpo limita o spool anterior à autenticação a cerca de 10 MiB mais folga por requisição, mas não o elimina nem limita a concorrência de uploads anônimos.

## Trabalho futuro

- Introduzir um `Protocol` de storage só quando existir um segundo backend (hoje seria camada sem uso).
- Agendar a reconciliação e/ou expor CLI.
- Validação mais profunda de PDF (estrutura, extração) na Fase 4.
- Limite de corpo no proxy e rate limit nas rotas de documentos.
