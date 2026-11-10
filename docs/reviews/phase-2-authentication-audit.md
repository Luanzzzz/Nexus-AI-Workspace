# Auditoria final da Authentication (Etapa 2.7)

## 1. Contexto

Objetivo: fechar a Fase 2 (Authentication) do Nexus com uma auditoria de arquitetura, QA e revisão adversarial, corrigir o escopo aprovado pelo dono do repositório e deixar o relatório e o CI como artefatos.

- Repositório: Nexus AI Workspace (FastAPI, SQLAlchemy async, PostgreSQL, Alembic, Argon2id, JWT).
- Referência: `Documento_tecnico_V1.0.md`, seção 10 e Fase 2.
- Commit auditado (somente leitura): `123b0076ac8692bc77a6bb92f5da9893008032ca` (`main`).
- Relatórios de origem (hipóteses com evidência, reproduzidas neste trabalho):
  - 2.7.1 Arquitetura (A1–A16)
  - 2.7.2–2.7.6 QA (QA1–QA11)
  - 2.7.4–2.7.5 Interrogador (I1–I11)
- Branch desta correção: `cursor/auth-audit-remediation-6b87`.

## 2. Escopo

**Auditado:** cadastro, login, JWT de acesso, `GET /auth/me`, hashing Argon2id, transações do `AuthService`, pool SQLAlchemy, configuração (`Settings`), contrato HTTP, logs de 500, testes de integração/unidade da auth, ausência de CI.

**Fora do escopo desta etapa (e da correção, salvo o que o dono listou):** RBAC e workspaces, Documents, refresh token, MFA, lockout, HSTS, limite de tamanho de corpo, lockfile com hashes, Docker de aplicação, E2E da seção 20, mypy/coverage como gate, hospedagem real e Python 3.13.

## 3. Arquitetura

Fluxos na `main` auditada e após a correção:

1. **Register:** router → `AuthService.register` → (hash Argon2id em thread) → `UserRepository.get_by_email` / `create_user` → `UNIQUE(email)` → resposta genérica 201.
2. **Login:** router → `AuthService.authenticate` → SELECT → encerra a transação de leitura → Argon2id em thread → JWT HS256.
3. **Me:** `HTTPBearer` → `decode_access_token` → `UserRepository.get_by_id` → 401 se ausente/inativo.

Responsabilidades: router HTTP e rate limit; service para caso de uso e transação; repository só SQL; `core/security` e `core/tokens` isolados; handlers e middleware para 422/401/500/request id.

## 4. Segurança

Controles existentes na auditoria: senha 15–128, email canônico, Argon2id (m=65536, t=3, p=4), JWT com `iss`/`aud`/`token_type`, 401 uniforme no login, `UserResponse` sem hash, 422 sem `input`, DEBUG proibido em production.

Riscos principais confirmados: força bruta sem rate limit (A1), enumeração no cadastro (A4), hash/PII no traceback do uvicorn (QA1/I1), NUL → 500 (QA2), segredo JWT fraco aceito (I6), pool sem `pre_ping` (A12), OpenAPI em production (I9).

## 5. Banco e transações

`get_db` só abre/fecha a sessão. Commit/rollback no service. `UNIQUE(email)` impede duplicata sob corrida. SAVEPOINT nos testes de service/`/me`. Após a correção: hash do cadastro fora da transação; login dá `commit()` de leitura antes do verify; engine com `hide_parameters=True`, `pool_pre_ping=True` e pool explícito (5/10/30).

## 6. Testes

Comandos (raiz, `POSTGRES_DB=nexus_ai_test`, host local):

```bash
python -m ruff check .
python -m ruff format --check .
python -m alembic upgrade head
python -m alembic check
python -m pytest
```

A suíte original na SHA auditada: 222 passed. Esta correção fica em **245 passed** (ruff, `alembic check`, pytest em ordem padrão e com `--randomly-seed=1` e `42`; testes novos também passam isolados). Os testes de integração só rodam se o banco for `nexus_ai_test` **e** o host for `127.0.0.1`/`localhost`/`::1`.

## 7. Achados

IDs consolidados (sem duplicar A6+QA1+I1, A4, etc.). Cada item: problema, onde, reproduzir, impacto, correção, teste.

| ID | Pri | Problema | Onde | Reproduzir | Impacto | Correção | Teste |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A1 | P1 exp | Sem rate limit em login/register | `api/v1/auth.py` | N logins 401 seguidos, nenhum 429 | Força bruta / stuffing | Limitador em memória, 429 + Retry-After, chave IP e email no login | `tests/test_auth_rate_limit.py` |
| I5 | P2 | XFF forjado muda o IP | defaults uvicorn; app sem lista | `X-Forwarded-For: 6.6.6.6` de peer não confiável | Bypass de rate limit por IP | `TRUSTED_PROXIES` vazio; XFF só se o peer está na lista | `test_forged_xff_from_untrusted_peer_is_ignored` |
| A4 | P2 | 409 e oráculo de tempo no cadastro | `auth.py`, `services/auth.py` | duplicado 409 ~3 ms vs 201 ~60 ms | Enumeração de contas | 201 idêntico; hash nos dois caminhos; UNIQUE na corrida | `test_register_existing_email_matches_new_email_response` |
| QA1 / I1 / A6 | P1 exp | 500 relança; uvicorn loga SQL+hash+email | `main.py`, `session.py`, Starlette | `name` com NUL; PG parado | Hash e PII em logs | `hide_parameters`; middleware que não relança; filtro; request id | `tests/test_logging_redaction.py`, `test_engine_pool.py` |
| QA2 | P2 | NUL no name → 500 | `schemas/user.py` | `Ana\u0000Silva` | 500 anônimo + gatilho de QA1 | Rejeitar categoria Cc → 422 | `test_register_rejects_nul_in_name_with_422` |
| I2 | P2 | DEBUG=true no default development devolve traceback | `main.py`, `config.py` | `DEBUG=true` + 500 | Hash no corpo HTTP | 500 JSON via middleware; debug FastAPI só em development; production recusa DEBUG | `test_debug_true_does_not_put_traceback_on_client` |
| I6 / I7 | P2/P3 | Segredo JWT por tamanho; erro ecoa valor | `config.py` | `'a'*32`, 32 espaços, placeholders longos | Forja se o operador errar; vazamento no crash | Entropia, placeholder por repetição, `hide_input_in_errors` | `tests/test_config.py` |
| QA3 | P2 | Parâmetros Argon2 implícitos; mutante fraco passa | `security.py` | `PasswordHasher(t=1,m=8)` | Regressão silenciosa | Constantes explícitas (sem mudar m/t/p) + teste `extract_parameters` | `test_hash_password_uses_explicit_argon2id_parameters` |
| A12 | P2 | Sem `pool_pre_ping` nem pool explícito | `db/session.py` | restart do PG → 1º `/me` 500 | 500 após restart | `pool_pre_ping`, size/overflow/timeout | `test_engine_uses_explicit_pool_and_hides_parameters` |
| A3 / QA5 | P2 | Conexão presa no Argon2; suíte não pega | `services/auth.py` | pool pequeno + N logins; `/me` 500 | DoS de pool | Hash fora da transação (register) e commit de leitura antes do verify (login) | `tests/test_auth_connection_release.py` |
| QA11 | P3 | Teste de falha deixa linha se falhar | `test_auth_service.py` | mutante sem rollback | Resíduo no `nexus_ai_test` | `try/finally` + guarda de host | os próprios testes + `conftest.py` |
| A7 | P2 | Sem CI | `.github/workflows/` | pasta só com README | Merge sem gate | workflow ruff + alembic + pytest + Postgres | `.github/workflows/backend.yml` |
| A8 / A9 | P3 | README e ADRs 0003–0006 desatualizados | `README.md`, `docs/decisions/` | leitura | Operador desinformado | README, ADRs, contrato HTTP, ADR 0007 | revisão |
| I9 | P3 | OpenAPI em production | `main.py` | `ENVIRONMENT=production` `/docs` 200 | Mapa de rotas | docs/redoc/openapi `None` em production | `test_production_hides_openapi` |

**Concordâncias e discordâncias com os relatórios**

- Concordo com A1, A3, A4, A7, A8, A9, A12, QA1–QA3, QA5, QA11, I1, I2, I5, I6, I7, I9.
- **A6:** a premissa “só o nome da classe, não é vazamento” está errada para exceções genéricas; o uvicorn relança e loga parâmetros. Tratei como QA1/I1.
- **A2:** parcialmente confirmado (teto implícito do executor). **Não** introduzi semáforo: o dono pediu correção pequena só se coubesse no item 7 (liberar sessão / reordenar). A3 foi mitigado; A2 permanece residual.
- **I8 nos relatórios** é `Cache-Control: no-store` (P3). O pedido do dono citou I8 como OpenAPI; OpenAPI no Interrogador é **I9**. Apliquei os dois: `no-store` nas respostas de auth e docs desligadas em production. Justificativa OpenAPI: em production o schema mapeia autenticação e, no futuro, Documents; no estudo local (`development`/`test`) as docs continuam ligadas.
- **I3:** sem lockfile (residual). Pisos de `PyJWT>=2.15.1`, `fastapi`, `starlette`, `uvicorn` e `argon2-cffi` foram subidos (trivial).
- P3 QA6, QA7 (IDs JWT), QA8, QA10, QA4, A10, A11, A13–A16, I4, I10, I11: ver seção 9. QA7 (IDs estáveis) foi corrigido por ser trivial.

## 8. Correções

O que mudou (código) e como foi testado:

1. Logging: `core/logging.py` (filtro), `RequestContextMiddleware` (não relança, `X-Request-ID`), `hide_parameters=True`. Testes de redação e 500 com `raise_server_exceptions=True`.
2. Controle Cc nos schemas → 422. Teste de schema e HTTP.
3. `fastapi_debug` só em development; OpenAPI off em production.
4. Validação JWT por whitespace, placeholder repetido e entropia, sem ecoar o valor.
5. Argon2id com constantes iguais à política anterior + teste de parâmetros.
6. Pool explícito + `pool_pre_ping`.
7. Hash antes do SQL no cadastro; `commit` de leitura antes do verify no login; testes de ordem e `/me` concorrente com verify lento.
8. Rate limit em memória + 429; XFF só com proxy confiável.
9. Register genérico 201; testes HTTP e UNIQUE sob corrida mantidos no service.
10. CI GitHub Actions.
11. README, ADRs 0003–0007, `docs/api/users.md`.
12. QA11: cleanup e host local na guarda.

## 9. Riscos residuais

| ID | Risco | Por que ficou | Condição de resolução |
| --- | --- | --- | --- |
| A2 | Sem teto configurável de Argon2id | Correção não é pequena; p=4 permanece por ordem do dono | Benchmark na VPS; `Semaphore` ou executor dedicado; teto ≈ `cpus // p` |
| A5 / I10 | Sem logout, `jti` ou `token_version` | Fora do escopo | Migration + ADR junto com reset de senha |
| A16 | Sem `POST /auth/refresh` | Coerente com §10; §11 cita a rota | Alinhar o documento técnico ou implementar com A5 |
| I3 | Sem lockfile / pin com hash | Só pisos mínimos | `uv lock` ou `pip-compile --generate-hashes` + `pip-audit` no CI |
| I4 | Sem limite de corpo | Fora do escopo | Proxy `client_max_body_size` e/ou middleware 413 |
| I11 | Sem MFA, lockout, HSTS, nosniff, senhas vazadas | MVP de estudo | HSTS no proxy; MFA/lockout em fase posterior |
| QA4 / A13 | Verify aceita tipo/custo do hash; sem rehash | Fora do escopo | `extract_parameters` + teto; `check_needs_rehash` no login |
| A14 | Primeiro dummy hash lazy (~+60 ms / processo) | Residual P3 | Gerar no lifespan |
| QA6 | `alembic check` cego a CHECK | Residual | Teste `pg_constraint` ou plugin Alembic |
| QA8 | Coverage sem greenlet | Residual | `pytest-cov` + `concurrency = thread,greenlet` |
| QA10 | Sem NFKC / confusáveis | Residual | ADR + rejeitar local-part não ASCII ou NFKC |
| A11 | Envelope de erro ≠ §26 | Residual | ADR se o §26 vale no MVP |
| A10 | Instanciação register vs login | Register agora usa `get_auth_service` (trivial) | — |
| A15 | Dockerfile placeholder | Fora da Fase 2 | Quando houver imagem real |
| Limitador | Estado por processo | Documentado no ADR 0007 | Store compartilhado ou limite no proxy |
| Locale PG | `lower()` só conferido em C.UTF-8 nos relatórios | Não reexecutado em `en_US.utf8`/ICU | Repetir no locale de produção |

## 10. Conclusão

**Estudo local de Documents (Fase 3):** pronto. A Fase 2 entrega register, login, JWT e `/me` testados. Nada disto bloqueia autorização por workspace; essa dependency é trabalho da Fase 3.

**Exposição pública:** não pronta. Mesmo com rate limit, cadastro genérico, logs redigidos e pool configurado, faltam teto de Argon2id na máquina alvo, backend de rate limit compartilhado, limite de corpo, HSTS no TLS, lockfile, revogação/logout e hospedagem com proxy confiável configurado. Tratar esta API como laboratório local até essas condições.
