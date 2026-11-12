# Nexus AI Workspace

Projeto de portfólio focado em backend Python, engenharia de IA (RAG e agentes), PostgreSQL, testes e infraestrutura.

O objetivo é estudar e consolidar engenharia de software na prática, implementando as partes do sistema de forma incremental.

**Status:** Fase 2 (Authentication) concluída e Fase 3 (Workspaces e Documents) implementada no backend. Há cadastro, login com JWT HS256, `GET /auth/me`, hash Argon2id, rate limit em memória, workspaces com membership e papéis, upload/listagem/consulta/exclusão de documentos em storage local e CI no GitHub Actions. Frontend, RAG e agentes ainda não foram implementados; não há endpoints de administração de membros. A API **não está pronta para exposição pública**; ver [riscos residuais](docs/reviews/phase-2-authentication-audit.md).

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

## Workspaces e documentos (Fase 3)

Contratos: [docs/api/workspaces.md](docs/api/workspaces.md) e [docs/api/documents.md](docs/api/documents.md). Decisões: [ADR 0008](docs/decisions/0008-workspace-bootstrap-and-authorization.md) e [ADR 0009](docs/decisions/0009-document-local-storage.md).

| Método | Rota | Notas |
| --- | --- | --- |
| `POST` | `/api/v1/workspaces` | Cria workspace e membership `owner` na mesma transação. Slug duplicado: 409 genérico. |
| `GET` | `/api/v1/workspaces` | Só workspaces em que o usuário é membro. |
| `GET` | `/api/v1/workspaces/{workspace_id}` | Qualquer papel; 404 sem membership. |
| `POST` | `/api/v1/workspaces/{workspace_id}/documents` | Upload multipart (PDF, TXT, MD; até 10 MiB). Só `owner` e `admin`. |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents` | Listagem paginada (`limit` 1–100, padrão 20; `offset`). Qualquer papel. |
| `GET` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}` | Qualquer papel; documento de outro workspace é 404. |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/documents/{document_id}` | Só `owner` e `admin`; 204. Não é atômico entre banco e disco (ver ADR 0009). |

Os blobs ficam no diretório indicado pela variável de ambiente `DOCUMENT_STORAGE_DIR` (padrão `backend/var/documents`, ignorado pelo Git). Nos testes, o `conftest.py` redireciona esse diretório para um temporário por teste. A reconciliação de blobs órfãos existe como função (`app/services/document_reconciliation.py`, `dry_run` por padrão), sem CLI nem agendador. Atrás de um proxy reverso, limite o tamanho do corpo das requisições de upload (ver ADR 0009).

## Verificação do backend

Ruff, pytest e Alembic também podem ser executados na raiz. O pacote e as migrations ficam em `backend/`. Testes de integração exigem `POSTGRES_DB=nexus_ai_test` num host local (`127.0.0.1`, `localhost` ou `::1`).

```bash
python -m ruff check .
python -m ruff format --check .
POSTGRES_DB=nexus_ai_test python -m alembic upgrade head
POSTGRES_DB=nexus_ai_test python -m alembic check
POSTGRES_DB=nexus_ai_test python -m pytest
```

Para rodar só os testes que não tocam o banco: `POSTGRES_PORT=1 POSTGRES_DB=nexus_ai_test python -m pytest -m "not integration"`. A suíte multi-tenant da Fase 3 está em `backend/tests/test_phase3_security.py`.

O CI em [`.github/workflows/backend.yml`](.github/workflows/backend.yml) roda os mesmos passos contra um serviço Postgres.

## Ambiente e modo debug

A configuração vem de variáveis de ambiente ou do `.env` da raiz (modelo em `.env.example`):

- `ENVIRONMENT`: `development` (padrão), `test` ou `production`.
- `DEBUG`: padrão `false`. Só liga o debug do FastAPI em `development`. `ENVIRONMENT=production` com `DEBUG=true` impede a inicialização. Em production `/docs`, `/redoc` e `/openapi.json` ficam desligados.
- `JWT_SECRET_KEY`: obrigatório, ≥32 bytes, sem placeholder e com entropia mínima. Gere com `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- `TRUSTED_PROXIES`: lista vazia por padrão. Só IPs dessa lista podem fazer o app honrar `X-Forwarded-For` (rate limit), lendo a cadeia **da direita**. Suba com `python -m app` a partir de `backend/` (alinha `proxy_headers` / `forwarded_allow_ips` à lista). `uvicorn app.main:app` sem esses flags volta a confiar no loopback. O proxy deve anexar o IP do cliente, não o valor forjado.
- `AUTH_RATE_LIMIT_ENABLED`: padrão `true`. Os testes desligam.
- Limites de upload (em memória, por processo; ver ADR 0009): `UPLOAD_LIMITS_ENABLED` (`true`; os testes desligam), `UPLOAD_RATE_LIMIT_PER_MINUTE` (20 por usuário) e `UPLOAD_MAX_CONCURRENT_PER_USER` (2 por usuário). Excedidos: 429 com `Retry-After`.
- Cotas por workspace: `WORKSPACE_MAX_DOCUMENTS` (1000) e `WORKSPACE_MAX_STORAGE_BYTES` (1073741824, 1 GiB). Excedidas: 413.
- Criação de workspace (ADR 0008): `WORKSPACE_MAX_OWNED_PER_USER` (10; excedido: 403), `WORKSPACE_CREATE_RATE_LIMIT_ENABLED` (`true`; os testes desligam) e `WORKSPACE_CREATE_RATE_LIMIT_PER_HOUR` (10 por usuário; excedido: 429).
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
