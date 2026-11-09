# ADR 0004: CHECK para email canônico

## Problema

O [ADR 0003](0003-canonicalizacao-de-email-no-cadastro.md) guarda o email inteiro em minúsculas no `UserRegister`. A coluna `users.email` é `String` com `UNIQUE(email)`. No PostgreSQL essa unicidade diferencia maiúsculas de minúsculas. Outro caminho de escrita, que não passe pelo schema, pode gravar `Usuario@Example.com` ao lado de `usuario@example.com`.

## Opções

- `CITEXT`: a coluna deixa de diferenciar maiúsculas de minúsculas. Muda o tipo e o comportamento de comparação para além do cadastro.
- Índice único em `lower(email)`, removendo ou mantendo o `UNIQUE(email)`: a busca canônica fica protegida, mas a coluna ainda aceita a caixa original.
- Manter `UNIQUE(email)` e acrescentar `CHECK (email = lower(email))`: só a forma já canônica entra. A comparação continua a da string exata.

## Decisão

Fica a terceira opção. O schema Pydantic continua sendo o caminho canônico do cadastro. O banco passa a recusar email que não esteja em minúsculas, inclusive quando alguém grava direto no model.

Não usamos `CITEXT`. Não trocamos o `UNIQUE(email)` por um índice só em `lower(email)`.

Antes da migration, em 9 de novembro de 2026, `nexus_ai` e `nexus_ai_test` tinham zero linhas em `users` e zero emails diferentes de `lower(email)`. A migration conta essas linhas e interrompe se houver alguma. Ela não reescreve e não apaga dados.

O autogenerate do Alembic não compara `CHECK` a menos que o plugin opcional seja ligado. A restrição está no model e na migration `2e25f9565a47`. O teste de integração cobre a rejeição.

`lower()` do PostgreSQL e `str.lower()` do Python não coincidem para todo caractere Unicode. O MVP aceita esse limite, o mesmo trade-off já registrado no ADR 0003.
