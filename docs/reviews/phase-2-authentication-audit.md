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
POSTGRES_DB=nexus_ai_test python -m pytest
POSTGRES_PORT=1 python -m pytest -m "not integration"
```

A suíte original na SHA auditada: 222 passed. Depois da primeira correção: 245. Na SHA `91d13e8`: 261. Na SHA `db540bb` (Reviewer EmailStr): 269. Nesta rodada do mentor (P1 marcador+guard, P2 teto fail-closed, P2 log sem mensagem): **272 passed** (ordem de arquivo e `--randomly-seed=20261110`). Unitários sem Postgres: **201 passed**, 71 deselected. Integração só em `nexus_ai_test` em host local.

`python -m pytest --collect-only -q -m "not integration" backend/tests/test_auth_rate_limit.py`

Antes (db540bb, 9 collected):

```
tests/test_auth_rate_limit.py::test_login_name_addr_display_names_share_email_limit
tests/test_auth_rate_limit.py::test_login_rate_limit_per_email_returns_429
tests/test_auth_rate_limit.py::test_uvicorn_proxy_kwargs_disable_headers_when_untrusted
tests/test_auth_rate_limit.py::test_register_rate_limit_per_ip_returns_429
tests/test_auth_rate_limit.py::test_name_addr_rate_limit_key_matches_bare_email
tests/test_auth_rate_limit.py::test_login_email_rate_limit_uses_canonical_email
tests/test_auth_rate_limit.py::test_forged_xff_from_untrusted_peer_is_ignored
tests/test_auth_rate_limit.py::test_xff_used_only_from_trusted_proxy
tests/test_auth_rate_limit.py::test_xff_appended_by_trusted_proxy_uses_rightmost_untrusted
9 tests collected
```

Depois (4 HTTP que batem no Postgres saíram da seleção):

```
tests/test_auth_rate_limit.py::test_xff_appended_by_trusted_proxy_uses_rightmost_untrusted
tests/test_auth_rate_limit.py::test_xff_used_only_from_trusted_proxy
tests/test_auth_rate_limit.py::test_uvicorn_proxy_kwargs_disable_headers_when_untrusted
tests/test_auth_rate_limit.py::test_forged_xff_from_untrusted_peer_is_ignored
tests/test_auth_rate_limit.py::test_name_addr_rate_limit_key_matches_bare_email
5/9 tests collected (4 deselected)
```

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
| I8 | P3 | Login/me sem `Cache-Control: no-store` | `api/v1/auth.py` | 200/401 sem o header | Token em cache de proxy | `no-store` em login, me, 401 e 429 | `test_login_returns_decodable_bearer_token` |
| QA7 | P3 | IDs de teste JWT mudavam a cada segundo | `tests/unit/test_jwt.py` | `--collect-only` duas vezes | `no tests ran` no re-run | ids fixos, timestamp dentro do teste | duas coletas com nodeids iguais |
| QA9 | P3 | Placeholder JWT inalcançável (lista curta demais) | `core/config.py` | `changeme`×4 de 32+ bytes aceito | Segredo fraco sobe | repetição compacta + entropia + teclado | `test_settings_rejects_weak_or_placeholder_jwt_secret` |
| A10 | P3 | `register` instanciava o service na rota | `api/v1/auth.py` | override desigual | Testes assimétricos | `Depends(get_auth_service)` | suíte HTTP de register |
| G1 | P2 exp | Uvicorn default honra XFF no loopback; app lia o hop da esquerda | `uvicorn` + `request_context.py` | peer 127.0.0.1 + XFF variando → 201×N | Bypass do rate limit por IP | `python -m app` alinha `proxy_headers`; cadeia da direita | `test_uvicorn_empty_trusted_proxies_ignores_forged_xff` |
| M6 | P3 | Rollback do `IntegrityError` sem teste | `services/auth.py` | mutante tira o rollback e a suíte passa | Sessão suja se o close falhar | teste de fake session conta rollback | `test_register_rolls_back_on_integrity_error` |
| G8 | P1 | `email_rate_limit_key` via `validate_email` recusa `Nome <victim@host>` e o fallback vira chave por nome | `core/emailcanon.py` | 6 logins com nomes distintos, mesmo addr-spec, todos 401 | Bypass do teto 5/60 s (ADR 0007) | Mesmo `EmailStr` do login/cadastro + lower; ADR justifica não recusar name-addr | `test_login_name_addr_display_names_share_email_limit` |
| P1 | P1 | Testes HTTP/SQL sem `@pytest.mark.integration` fogem da guarda da Fase 1 | `conftest.py`, `test_auth_rate_limit.py`, `test_auth_login.py` | pytest sem marcador contra outro `POSTGRES_DB` | Risco de escrever em `nexus_ai` | Marcar quem toca o banco; guard autouse bloqueia connect; job CI unitário sem Postgres | `test_unmarked_test_cannot_open_database_connection` |
| P2-cap | P2 | `_enforce_cap` evictava chaves com janela ativa | `core/rate_limit.py` | encher 4096 chaves novas depois de bloquear uma vítima | Bypass silencioso do teto | Só poda expiradas; chave nova em mapa cheio → 429 + warning sem PII | `test_limiter_keeps_active_key_when_at_capacity` |
| P2-log | P2 | `redact_text` no traceback completo deixa segredo em texto livre | `exception_handlers.py` | 500 cuja mensagem é um sentinela sem padrão | Credencial no log | Fora de development: tipo + frames; traceback completo só em development | `test_non_development_500_log_omits_sentinel_and_cause_message` |

**Concordâncias e discordâncias com os relatórios**

- Concordo com A1, A3, A4, A7, A8, A9, A12, QA1–QA3, QA5, QA11, I1, I2, I5, I6, I7, I9.
- **A6:** a premissa “só o nome da classe, não é vazamento” está errada para exceções genéricas; o uvicorn relança e loga parâmetros. Tratei como QA1/I1.
- **A2:** parcialmente confirmado (teto implícito do executor). **Não** introduzi semáforo: o dono pediu correção pequena só se coubesse no item 7 (liberar sessão / reordenar). A3 foi mitigado; A2 permanece residual.
- **I8 nos relatórios** é `Cache-Control: no-store` (P3). O pedido do dono citou I8 como OpenAPI; OpenAPI no Interrogador é **I9**. Apliquei os dois: `no-store` nas respostas de auth e docs desligadas em production. Justificativa OpenAPI: em production o schema mapeia autenticação e, no futuro, Documents; no estudo local (`development`/`test`) as docs continuam ligadas.
- **I3:** sem lockfile (residual). Pisos de `PyJWT>=2.15.1`, `fastapi`, `starlette`, `uvicorn` e `argon2-cffi` foram subidos (trivial).
- P3 QA6, QA8, QA10, QA4, A11, A13–A16, I4, I10, I11: ver seção 9. QA7, QA9, A10, I8, G1 e M6 foram corrigidos.

## 8. Correções

O que mudou (código) e como foi testado:

1. Logging: `core/logging.py` (filtro), `RequestContextMiddleware` (não relança, `X-Request-ID`), `hide_parameters=True`. Fora de development o 500 interno loga só tipo, `request_id` e frames.
2. Controle Cc nos schemas → 422. Teste de schema e HTTP.
3. `fastapi_debug` só em development; OpenAPI off em production.
4. Validação JWT por whitespace, placeholder repetido e entropia, sem ecoar o valor.
5. Argon2id com constantes iguais à política anterior + teste de parâmetros.
6. Pool explícito + `pool_pre_ping`.
7. Hash antes do SQL no cadastro; `commit` de leitura antes do verify no login; testes de ordem e `/me` concorrente com verify lento, inclusive com `pool_size=1`/`max_overflow=0`.
8. Rate limit em memória + 429; XFF só com proxy confiável; `python -m app` alinha o uvicorn; hops da direita; teto de chaves fail-closed (sem evict de janela ativa); chave de email = `EmailStr` + lower; `TRUSTED_PROXIES=*` recusado na config.
9. Register genérico 201; testes HTTP e UNIQUE sob corrida mantidos no service.
10. CI GitHub Actions: job `unit` (`pytest -m "not integration"` sem Postgres) e job `test` com Postgres 17 + suíte completa.
11. README, ADRs 0003–0007, `docs/api/users.md`.
12. QA11: cleanup e host local na guarda.
13. Guard de testes: fixture autouse intercepta `dialect.connect` / psycopg em testes sem `integration`; marcadores nos HTTP/SQL que faltavam.

## 9. Riscos residuais

Cada residual: problema, onde, reproduzir, impacto, por que ficou, condição de resolução e como testar depois.

| ID | Problema | Onde | Reproduzir | Impacto | Por que ficou | Condição | Como testar |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A2 | Sem teto configurável de Argon2id | `asyncio.to_thread` | N logins concorrentes; RSS sobe com `min(32, cpu+4)` | Pico de memória ~64 MiB × workers | Não é correção pequena; p=4 fixo | Benchmark na VPS; `Semaphore` ≈ `cpus // p` | Instrumentar hasher; N nunca passa do teto |
| A5 / I10 | Sem logout / `token_version` | `tokens.py` | Token de conta ativa vale até `exp`; reset de senha (inexistente) não derruba | Token roubado por 30 min | Fora do escopo | Migration + ADR com reset | Incrementar versão → 401 no token antigo |
| A16 | Sem `POST /auth/refresh` | OpenAPI | A rota não existe | Relogin a cada 30 min | Coerente com §10 | Alinhar §11 ou implementar com A5 | OpenAPI sem a rota, ou 200 com refresh |
| I3 | Sem lockfile | `pyproject.toml` | Build novo resolve outras versões | Advisories em pisos antigos | Só pisos mínimos nesta etapa | `uv lock` + `pip-audit` no CI | Job falha com CVE |
| I4 | Sem limite de corpo | `main.py` | POST 50 MiB | DoS de memória | Fora do escopo | Proxy e/ou middleware 413 | 1 MiB → 413 |
| I11 | Sem MFA, lockout, HSTS | headers HTTP | Login só `www-authenticate` | Superfície OWASP incompleta | MVP de estudo | HSTS no proxy; MFA depois | Headers e fluxo MFA |
| QA4 / A13 | Verify segue o hash gravado; sem rehash | `security.py` | argon2i ou m=256 MiB no banco | DoS / downgrade se o banco for escrito | Fora do escopo | Teto de parâmetros + rehash | Hash fora da política → 500; login regrava |
| A14 | Dummy hash lazy | `services/auth.py` | 1º login inexistente ~+60 ms / processo | Oráculo pontual | P3 | Gerar no lifespan | Dois logins inexistentes no processo novo com tempos iguais |
| QA6 | `alembic check` cego a CHECK | `alembic/env.py` | `DROP CONSTRAINT ck_users_email_lowercase`; check ok | Drift de CHECK | Mitigado pelo teste de model | Plugin ou `pg_constraint` | Teste falha se o CHECK sumir |
| QA8 | Coverage sem greenlet | `pyproject.toml` | pytest-cov padrão 97% | Falso negativo | Residual | `concurrency=thread,greenlet` | Gate ~95% |
| QA10 | Sem NFKC / confusáveis | `schemas/user.py` | `ｆｕｌｌ@` ≠ `full@` | Homógrafo na Fase 3 | ADR 0003 | Política ASCII ou NFKC | Parametrizado |
| A11 | Envelope ≠ §26 | handlers | 500 é `{"detail":...}` | Divergência documental | ADR pendente | Decidir se §26 vale no MVP | Contrato único com `request_id` |
| A15 | Dockerfile placeholder | `backend/Dockerfile` | `docker build` incompleto | Sem imagem | Fora da Fase 2 | Dockerfile real | CI de build |
| G5 | Δ ~1,4 ms novo vs existente no register | INSERT vs rollback | N=40, mediana | Oráculo de tempo residual | Aceitável no MVP | Só se a Fase 3 exigir uniformidade de ns | Teste de timing com folga |
| Limitador | Estado por processo | `rate_limit.py` | 2 workers × teto | Teto efetivo dobra | Sem Redis | Store compartilhado ou proxy | Dois processos, N+1 ainda 200 |
| Locale PG | `lower()` só em C.UTF-8 | CHECK email | Python 3.13 / `en_US.utf8` | 500 de CHECK | Não reexecutado | Repetir no locale de produção | Script de code points |
| Entrada uvicorn | `uvicorn app.main:app` sem flags | CLI | Default honra XFF no loopback | G1 volta | Documentado; `python -m app` é a entrada | Proibir o CLI cru no deploy | Teste G1 contra o comando de produção |
| B3 | SQL no import/coleta do módulo de teste | import time | `engine.connect()` no topo do arquivo | Bypass se o erro for engolido | Fora desta rodada | Falhar coleta se houver checkout | Import que conecta quebra a sessão |
| B4 | Referência a `connect` capturada antes do guard | `async_creator=ref` | guardar `AsyncConnection.connect` no import | Patch não alcança a ref | Monkeypatch não cobre | pytest-socket / porta 1 | Creator direto ainda conecta |
| B5 | `asyncpg` / `postgresql+asyncpg` | driver ausente no repo | `asyncpg.connect` | SQL no banco configurado | asyncpg não é dependência | Patch se o pacote entrar | Teste com asyncpg |
| B6 | libpq cru (`PGconn`), socket v3, subprocess | C / OS | `psycopg.pq.PGconn.connect` | Fora do Python | Patch não alcança | Job `unit` porta 1; pytest-socket | Subprocesso passa no silêncio |
| M1 | Guard vira HTTP 500 no TestClient | middleware 500 | login sem marcador | Teste “500” passa pelo motivo errado | Fora desta rodada | `pytest.fail` no teardown | pytester no login |
| G1 | `PGHOSTADDR` desvia o host da libpq | env | `PGHOSTADDR` ≠ `POSTGRES_HOST` | Host efetivo não é o da URL | Só `host` nos cparams | Abortar se `PGHOSTADDR` existir | Setup falha com o env |
| G1-hostaddr | `hostaddr` no conninfo/URL desvia o host | cparams | `host=127.0.0.1 hostaddr=192.0.2.1` | libpq ignora `host` | Amplia G1; o guard lê só `host` | Recusar `hostaddr` no connect | DSN com hostaddr é bloqueado |
| R19/R20 | Símbolos privados do conftest liberam o banco | `tests.conftest` | `_original_psycopg_connect` / `_allow_marked_connect.set(True)` | Conexão de propósito | Uso deliberado de API interna | Grep no CI fora do conftest | Chamada direta conecta |
| G2 | Integration monta URL/`engine` próprio | `create_engine` | `database=nexus_ai` no connect | Mitigado: `DefaultDialect.connect` recusa dbname/host efetivos ≠ `nexus_ai_test` local | Caiu de graça com a checagem no connect | — | `test_integration_rejects_wrong_database_name` |

## 10. Conclusão

**Estudo local de Documents (Fase 3):** pronto. A Fase 2 entrega register, login, JWT e `/me` testados. Nada disto bloqueia autorização por workspace; essa dependency é trabalho da Fase 3.

**Exposição pública:** não pronta. Mesmo com rate limit, cadastro genérico, logs redigidos e pool configurado, faltam teto de Argon2id na máquina alvo, backend de rate limit compartilhado, limite de corpo, HSTS no TLS, lockfile, revogação/logout e hospedagem com proxy confiável configurado. Tratar esta API como laboratório local até essas condições.
