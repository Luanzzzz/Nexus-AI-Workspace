# Nexus AI Workspace

Backend de uma plataforma multi-tenant em que cada organização tem os próprios workspaces e documentos. O objetivo final é conversar com esses documentos usando RAG e agentes de IA. É um projeto de portfólio, construído em fases, com foco em backend Python, PostgreSQL, testes e segurança.

**Estado atual:** as fases 2 (autenticação) e 3 (workspaces e documentos) estão na `main`. Ainda não existem RAG, agentes, chat nem frontend. A API **não está pronta para exposição pública** (ver [riscos residuais](docs/reviews/phase-2-authentication-audit.md) e a [auditoria da Fase 3](docs/reviews/phase-3-documents-audit.md)).

## Stack

| Camada | Tecnologia | Versão declarada no código |
| --- | --- | --- |
| Linguagem | Python | `>=3.12` (`backend/pyproject.toml`); o CI usa 3.12 |
| API | FastAPI | `fastapi>=0.115.2` |
| ASGI | Starlette, Uvicorn | `starlette>=1.3.1`, `uvicorn[standard]>=0.32.0` |
| ORM | SQLAlchemy (async) | `sqlalchemy[asyncio]>=2.0,<3.0` |
| Driver | psycopg | `psycopg[binary]>=3,<4` |
| Migrations | Alembic | sem versão mínima |
| Validação e config | Pydantic, pydantic-settings, email-validator | sem versão mínima |
| Senha e token | argon2-cffi (Argon2id), PyJWT (HS256) | `argon2-cffi>=23.1.0`, `PyJWT>=2.15.1,<3` |
| Upload | python-multipart | `>=0.0.20` |
| Banco | PostgreSQL | **17**: `pgvector/pgvector:0.8.7-pg17` no `docker-compose.yml` e `postgres:17` no CI |
| Qualidade | pytest, pytest-asyncio, httpx, Ruff | sem versão mínima |

Não há lockfile, então as versões acima são pisos. Redis aparece no `.env.example` (`REDIS_URL`), mas o código não usa. O pgvector está na imagem do Compose, mas nenhuma migration cria a extensão.

## O que já funciona

**Autenticação (Fase 2)**
- Cadastro com senha de 15 a 128 caracteres, guardada com Argon2id (m=64 MiB, t=3, p=4). O email é gravado em minúsculas e o banco garante isso com `CHECK`.
- O cadastro sempre responde `201 {"detail": "Cadastro processado."}`, para email novo ou já existente, para não revelar quais emails têm conta.
- Login com JWT HS256 de 30 minutos, com `iss`, `aud` e `token_type` conferidos. O 401 é igual para email inexistente, senha errada e conta inativa.
- `GET /auth/me` consulta o banco a cada chamada. Desativar ou remover a conta derruba o token na próxima requisição.
- Rate limit em memória, por processo: login com 5 por email e 20 por IP a cada 60 s, e cadastro com 5 por IP a cada 60 s. O excesso recebe 429 com `Retry-After`. O `X-Forwarded-For` só vale vindo de um IP listado em `TRUSTED_PROXIES`.

**Workspaces (Fase 3)**
- Criar um workspace cria também a membership `owner`, na mesma transação. O `owner_id` e o papel vêm do servidor, nunca do payload. Slug repetido dá 409.
- Cada usuário pode ser dono de no máximo 10 workspaces (403) e criar no máximo 10 por hora (429).
- A listagem só traz os workspaces de que o usuário é membro. Workspace sem membership responde 404.
- Os papéis são `owner`, `admin`, `member` e `viewer`. Todos podem ler; só `owner` e `admin` sobem e excluem documentos (`app/core/permissions.py`).

**Documentos (Fase 3)**
- Upload multipart de `.pdf`, `.txt`, `.md` e `.markdown`, com até 10 MiB. O `mime_type` gravado vem da extensão e o conteúdo é verificado. O arquivo vai para o storage local em `DOCUMENT_STORAGE_DIR` (padrão `backend/var/documents`, fora do Git).
- O middleware `UploadGuardMiddleware` valida o JWT e limita o tamanho do corpo **antes** de ler o upload.
- Limites por usuário: 20 uploads por minuto e 2 simultâneos (429). Cotas por workspace: 1000 documentos e 1 GiB (413).
- Listagem paginada (`limit` de 1 a 100, padrão 20, e `offset`), consulta e exclusão. Um documento de outro workspace responde 404, com o mesmo corpo de um documento inexistente.
- Todo documento novo nasce com status `uploaded`. Os estados `processing`, `ready` e `failed` existem no banco, mas nenhum código os usa ainda.
- Existe uma função de reconciliação de arquivos órfãos (`app/services/document_reconciliation.py`, que por padrão só simula com `dry_run`), sem CLI nem agendador.

**Transversal**
- Os erros 500 devolvem JSON genérico com o cabeçalho `X-Request-ID`. Fora de `development`, o log guarda só o tipo, o `request_id` e os frames, e um filtro remove hash, JWT, email, DSN e parâmetros SQL.
- Os erros 422 não repetem o valor enviado. Respostas de autenticação levam `Cache-Control: no-store`.
- Em `production`, `/docs`, `/redoc` e `/openapi.json` ficam desligados, e `DEBUG=true` impede a aplicação de subir.
- CI no GitHub Actions com dois jobs: `unit` (testes sem Postgres) e `test` (Ruff, Alembic e a suíte completa contra Postgres 17).

## Como rodar localmente

Pré-requisitos: Python 3.12 ou mais novo, e Docker com Compose para o banco.

1. **Variáveis de ambiente.** Copie o modelo e preencha os valores na sua máquina:

   ```bash
   cp .env.example .env
   python -c "import secrets; print(secrets.token_urlsafe(32))"   # cole em JWT_SECRET_KEY
   ```

   O `.env` da raiz é lido pela aplicação e pelo Compose. Sem um `JWT_SECRET_KEY` válido, a aplicação não sobe: ele precisa ter pelo menos 32 bytes, sem placeholder e sem baixa entropia. O modelo aponta para `127.0.0.1:5433` e para o banco `nexus_ai`.

2. **Banco.** O `docker-compose.yml` sobe **só o PostgreSQL**, publicado em `127.0.0.1:5433`. A API não tem container (o `backend/Dockerfile` ainda é placeholder).

   ```bash
   docker compose up -d postgres
   ```

3. **Dependências** (de preferência num virtualenv):

   ```bash
   python -m pip install -e "backend[dev]"
   ```

4. **Migrations.** Rode a partir da raiz, onde o `alembic.ini` aponta para `backend/alembic`:

   ```bash
   python -m alembic upgrade head
   ```

   São quatro migrations: `users`, `workspaces` e `workspace_members`, o `CHECK` de email em minúsculas, e `documents` (head `845eb9180446`).

5. **API.** Suba a partir de `backend/`:

   ```bash
   cd backend
   python -m app
   ```

   O servidor sobe em `127.0.0.1:8000`, ou em `APP_HOST`/`APP_PORT` se estiverem definidos. Use `python -m app` em vez de `uvicorn app.main:app`: só essa entrada alinha o tratamento de `X-Forwarded-For` do uvicorn ao `TRUSTED_PROXIES`. A documentação interativa fica em `http://127.0.0.1:8000/docs` fora de `production`.

Outras variáveis (limites, pool e storage) estão no `.env.example` e em `backend/app/core/config.py`.

## Testes

Os testes ficam em `backend/tests`. Os que acessam o banco usam o marcador `integration`. Num teste sem esse marcador, uma fixture do `conftest.py` bloqueia qualquer conexão com o banco (`UnmarkedDatabaseAccessError`).

**Unitários, sem Postgres:**

```bash
POSTGRES_PORT=1 POSTGRES_DB=nexus_ai_test python -m pytest -m "not integration"
```

O `POSTGRES_PORT=1` garante que nenhum teste unitário alcance um banco de verdade, e é assim que o job `unit` do CI roda.

**Integração, com Postgres:** esses testes só rodam no banco `nexus_ai_test` num host local (`127.0.0.1`, `localhost` ou `::1`). Com qualquer outro nome ou host, o pytest para antes de qualquer SQL. O Compose cria apenas o banco do `POSTGRES_DB` (`nexus_ai`), então o banco de testes precisa ser criado à mão. O repositório não automatiza essa etapa. Um jeito é este:

```bash
docker compose exec postgres createdb -U nexus_user nexus_ai_test   # use o POSTGRES_USER do seu .env
POSTGRES_DB=nexus_ai_test python -m alembic upgrade head
POSTGRES_DB=nexus_ai_test python -m pytest
```

**Qualidade** (os mesmos passos do CI):

```bash
python -m ruff check .
python -m ruff format --check .
POSTGRES_DB=nexus_ai_test python -m alembic check
```

A suíte multi-tenant de documentos fica em `backend/tests/test_phase3_security.py`.

## Estrutura de pastas

```text
.
├── backend/
│   ├── app/
│   │   ├── api/            # rotas v1, dependencies, handlers de erro, middlewares (request id, upload guard)
│   │   ├── core/           # config, segurança, JWT, permissões, rate limit, logging
│   │   ├── db/             # engine e sessão async
│   │   ├── models/         # User, Workspace, WorkspaceMember, Document
│   │   ├── repositories/   # acesso a dados (só SQL)
│   │   ├── schemas/        # modelos Pydantic de entrada e saída
│   │   ├── services/       # casos de uso (auth, workspace, documentos, reconciliação)
│   │   ├── storage/        # storage local de arquivos
│   │   ├── ai/             # reservado (agents, embeddings, rag, retrieval...), só pacotes vazios
│   │   ├── utils/ workers/ # reservados, vazios
│   │   └── __main__.py     # entrada `python -m app`
│   ├── alembic/            # migrations
│   ├── tests/              # unitários e de integração
│   ├── evals/              # reservado para avaliação de RAG, vazio
│   └── pyproject.toml
├── frontend/               # reservado (Next.js futuro), só README
├── infrastructure/         # reservado (docker, nginx), só READMEs
├── docs/
│   ├── api/                # contratos HTTP (users, workspaces, documents)
│   ├── decisions/          # ADRs 0001–0009
│   ├── reviews/            # auditorias das fases 2 e 3
│   ├── architecture/ diagrams/
├── .github/workflows/      # CI do backend
├── docker-compose.yml      # só PostgreSQL 17 (+ pgvector)
├── alembic.ini             # aponta para backend/alembic
├── pyproject.toml          # config de pytest e Ruff na raiz
└── Documento_tecnico_V1.0.md
```

Os arquivos `agents.py`, `conversations.py`, `tools.py` e `users.py` em `app/api/v1/` contêm só uma docstring e não estão registrados no router.

## Endpoints

Todos usam o prefixo `/api/v1`. As rotas marcadas com 🔒 exigem `Authorization: Bearer <access_token>`. Os contratos completos estão em [docs/api](docs/api/).

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/health` | Verifica se a API está no ar: `{"status": "ok"}`. |
| `POST` | `/auth/register` | Cadastra um usuário. Sempre 201 genérico. Rate limit por IP. |
| `POST` | `/auth/login` | Valida email e senha e devolve o JWT de acesso. Rate limit por IP e por email. |
| `GET` | `/auth/me` 🔒 | Dados públicos do usuário dono do token. |
| `POST` | `/workspaces` 🔒 | Cria um workspace com o usuário como `owner`. 409 para slug em uso, 403 acima do limite, 429 para criações demais. |
| `GET` | `/workspaces` 🔒 | Lista os workspaces de que o usuário é membro. |
| `GET` | `/workspaces/{workspace_id}` 🔒 | Detalhe do workspace, para qualquer papel. 404 sem membership. |
| `POST` | `/workspaces/{workspace_id}/documents` 🔒 | Upload de documento (PDF, TXT ou Markdown, até 10 MiB), só `owner` ou `admin`. |
| `GET` | `/workspaces/{workspace_id}/documents` 🔒 | Lista os documentos do workspace com paginação (`limit`, `offset`). |
| `GET` | `/workspaces/{workspace_id}/documents/{document_id}` 🔒 | Metadados de um documento do workspace. |
| `DELETE` | `/workspaces/{workspace_id}/documents/{document_id}` 🔒 | Exclui o documento (204), só `owner` ou `admin`. |

## Roadmap

Fases do [Documento técnico](Documento_tecnico_V1.0.md) que ainda faltam, com o que já está pendente no código:

- **Fase 4, base de RAG (em andamento):** extração de texto, chunking, embeddings, pgvector e busca por similaridade. O trabalho está na branch `feat/phase4-rag`, ainda sem PR e fora da `main`.
- **Fase 5, chat com RAG:** conversas, mensagens, recuperação, prompt, LLM e respostas com citações.
- **Fase 6, frontend MVP:** `/login`, `/dashboard`, `/documents` e `/chat`.
- **Fase 7, agentes:** Agent, Tools e ToolCall, com tool calling.
- **Fase 8, aprovação humana:** tool calls pendentes, aprovar, rejeitar, executar e auditar.
- **Fase 9, processamento assíncrono:** Redis, worker e jobs de ingestão de documentos (hoje os status `processing`, `ready` e `failed` não são usados).
- **Fase 10, observabilidade:** logs estruturados, uso de LLM, latência, tokens e custo.
- **Fase 11, avaliação:** datasets e testes de recuperação, de resposta e de citação.
- **Fase 12, release de portfólio:** deploy, screenshots, diagrama, vídeo e workspace de exemplo.

Pendências das fases 2 e 3, previstas no documento técnico ou registradas nas auditorias:
- refresh token, logout e revogação individual de token;
- `PATCH` e `DELETE` de workspace e as rotas de membros (`/workspaces/{workspace_id}/members`);
- envelope de erro padronizado (`{"error": {"code", "message", "request_id"}}`);
- Dockerfile da API e Compose com api, redis, worker e frontend;
- rate limit compartilhado entre processos, limite de corpo no proxy, lockfile de dependências e teto de concorrência do Argon2id.

## Documentação

- Contratos HTTP: [docs/api](docs/api/)
- Decisões (ADRs 0001–0009): [docs/decisions](docs/decisions/)
- Auditorias: [Fase 2](docs/reviews/phase-2-authentication-audit.md) e [Fase 3](docs/reviews/phase-3-documents-audit.md)
- Visão completa do produto: [Documento_tecnico_V1.0.md](Documento_tecnico_V1.0.md)

## Licença

MIT. Ver [LICENSE](LICENSE).
