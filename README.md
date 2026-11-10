# Nexus AI Workspace

Projeto de portfólio focado em backend Python, engenharia de IA (RAG e agentes), PostgreSQL, testes e infraestrutura.

O objetivo é estudar e consolidar engenharia de software na prática, implementando as partes do sistema de forma incremental.

**Status:** Fase 2 (Authentication) concluída no backend. Há cadastro, login com JWT HS256, `GET /auth/me`, hash Argon2id, rate limit em memória e CI no GitHub Actions. Frontend, RAG, agentes, RBAC e Documents ainda não foram implementados. A API **não está pronta para exposição pública**; ver [riscos residuais](docs/reviews/phase-2-authentication-audit.md).

## Stack planejada

- **Backend:** Python, FastAPI, Pydantic, SQLAlchemy, Alembic, Argon2id, PyJWT
- **Banco:** PostgreSQL, pgvector, Redis (ainda não usado)
- **IA:** LangChain, LangGraph, OpenAI, Gemini, Anthropic
- **Frontend:** Next.js, React, TypeScript, Tailwind
- **Qualidade / infra:** pytest, pytest-asyncio, Ruff, Docker Compose (só Postgres), GitHub Actions

## Autenticação (Fase 2)

Contrato: [docs/api/users.md](docs/api/users.md). Decisões: [ADR 0003](docs/decisions/0003-canonicalizacao-de-email-no-cadastro.md)–[0007](docs/decisions/0007-rate-limit-proxy-e-cadastro-generico.md). Auditoria: [docs/reviews/phase-2-authentication-audit.md](docs/reviews/phase-2-authentication-audit.md).

| Método | Rota | Notas |
| --- | --- | --- |
| `POST` | `/api/v1/auth/register` | Sempre 201 genérico (não enumera email). Rate limit por IP. |
| `POST` | `/api/v1/auth/login` | JWT de 30 min. Rate limit por IP e por email. |
| `GET` | `/api/v1/auth/me` | Bearer; consulta o usuário no banco. |
| `GET` | `/api/v1/health` | Saúde. |

Não há refresh token, logout nem revogação individual. Desativar ou remover a conta invalida o acesso na próxima chamada a `/me`.

## Verificação do backend

Ruff, pytest e Alembic também podem ser executados na raiz. O pacote e as migrations ficam em `backend/`. Testes de integração exigem `POSTGRES_DB=nexus_ai_test` num host local (`127.0.0.1`, `localhost` ou `::1`).

```bash
python -m ruff check .
python -m ruff format --check .
POSTGRES_DB=nexus_ai_test python -m alembic upgrade head
POSTGRES_DB=nexus_ai_test python -m alembic check
POSTGRES_DB=nexus_ai_test python -m pytest
```

O CI em [`.github/workflows/backend.yml`](.github/workflows/backend.yml) roda os mesmos passos contra um serviço Postgres.

## Ambiente e modo debug

A configuração vem de variáveis de ambiente ou do `.env` da raiz (modelo em `.env.example`):

- `ENVIRONMENT`: `development` (padrão), `test` ou `production`.
- `DEBUG`: padrão `false`. Só liga o debug do FastAPI em `development`. `ENVIRONMENT=production` com `DEBUG=true` impede a inicialização. Em production `/docs`, `/redoc` e `/openapi.json` ficam desligados.
- `JWT_SECRET_KEY`: obrigatório, ≥32 bytes, sem placeholder e com entropia mínima. Gere com `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- `TRUSTED_PROXIES`: lista vazia por padrão. Só IPs dessa lista podem fazer o app honrar `X-Forwarded-For` (rate limit), lendo a cadeia **da direita**. Suba com `python -m app` a partir de `backend/` (alinha `proxy_headers` / `forwarded_allow_ips` à lista). `uvicorn app.main:app` sem esses flags volta a confiar no loopback. O proxy deve anexar o IP do cliente, não o valor forjado.
- `AUTH_RATE_LIMIT_ENABLED`: padrão `true`. Os testes desligam.
- Pool: `DB_POOL_SIZE` (5), `DB_MAX_OVERFLOW` (10), `DB_POOL_TIMEOUT` (30), `DB_POOL_PRE_PING` (`true`).

Erros 500 devolvem JSON genérico e o cabeçalho `X-Request-ID` (valor recebido só é ecoado se for hex/token curto). Fora de `development`, o log interno traz o mesmo id, o tipo da exceção e os frames (arquivo, linha, função), sem a mensagem, sem locals e sem o texto de `__cause__`/`__context__`. O traceback completo só em `development`, ainda passando por `redact_text()`.

## Estrutura do monorepo

```text
.
├── backend/           # API e subsistema de IA
├── frontend/          # Aplicação Next.js (ainda não criada)
├── infrastructure/    # Docker auxiliar e nginx
├── docs/              # Arquitetura, API, ADRs, auditorias e diagramas
└── .github/workflows/ # CI do backend
```
