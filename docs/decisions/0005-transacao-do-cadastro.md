# ADR 0005: transação do cadastro sem session.begin()

## Problema

O cadastro precisa consultar, gerar o hash e gravar no mesmo caso de uso. O SQLAlchemy 2 usa autobegin: a primeira instrução SQL abre a transação. Chamar `session.begin()` depois disso trata a sessão como se estivesse limpa e levanta erro, porque a transação já está ativa.

## Opções

- `async with session.begin()` antes de qualquer SQL: a transação nasce explícita. O `get_by_email` não pode rodar antes, senão o `begin()` encontra a transação do autobegin.
- Commit e rollback em cima da transação que o autobegin já abriu, sem `session.begin()`.

## Decisão

O `AuthService` usa a segunda opção.

`get_by_email` é a primeira instrução e abre a transação. O serviço não chama `session.begin()`. No sucesso chama `commit()`. Na duplicidade, no `IntegrityError` e em qualquer outra falha chama `rollback()` antes de propagar o erro. `UNIQUE(email)` na corrida vira a mesma duplicidade de domínio; os outros `IntegrityError` continuam `IntegrityError`.

O repositório faz `add`, consulta e `flush`. Não dá commit nem rollback. `get_db()` só abre e fecha a sessão. Não há classe `UnitOfWork`. Fechar a sessão desfaz o que o serviço não confirmou; isso é rede de segurança, não a fronteira do caso de uso.

A consulta inicial também fica dentro do `try`: se `get_by_email` falhar, o serviço faz `rollback()` antes de propagar o erro.

A ordem do cadastro é hash, consulta e gravação. O hash Argon2id roda em `asyncio.to_thread` **antes** de qualquer SQL, para não ocupar conexão do pool (A3) e para igualar o custo de email novo e existente (A4). A transação abre no `get_by_email`. Não chamamos `session.begin()`. Cada cadastro concorrente usa a própria `AsyncSession`.

No login, a transação de leitura termina com `commit()` (e `expunge` do usuário) antes da verificação Argon2, pelo mesmo motivo.

Adendo da auditoria 2.7 (2026-11-10). Ver [ADR 0007](0007-rate-limit-proxy-e-cadastro-generico.md).
