# ADR 0002: papel de WorkspaceMember como texto com restrição

## Problema

O documento define os papéis `owner`, `admin`, `member` e `viewer`, sem escolher como persistir esse conjunto.

## Opções

- `String` com `CheckConstraint` listando os quatro valores.
- Enum Python mapeado para um tipo enumerado do PostgreSQL.

## Decisão

`role` é `String`, obrigatório, restrito por `CheckConstraint` aos quatro papéis do documento.

A constraint impede valores fora da lista e continua simples de alterar numa migration futura. Um tipo enumerado do PostgreSQL exigiria alterar o tipo do banco a cada papel novo.

`owner_id` em `Workspace` e o papel `owner` em `WorkspaceMember` permanecem conceitos distintos. A associação do proprietário não é criada pelo modelo.
