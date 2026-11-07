# Nexus AI Workspace

Projeto de portfólio focado em backend Python, engenharia de IA (RAG e agentes), PostgreSQL, testes e infraestrutura.

O objetivo é estudar e consolidar engenharia de software na prática, implementando as partes do sistema de forma incremental.

**Status:** em desenvolvimento. O backend já tem configuração, endpoint de saúde, conexão assíncrona com PostgreSQL, modelos de usuário e workspace, migrations e testes de integração. Frontend, RAG e agentes ainda não foram implementados.

## Stack planejada

- **Backend:** Python, FastAPI, Pydantic, SQLAlchemy, Alembic
- **Banco:** PostgreSQL, pgvector, Redis
- **IA:** LangChain, LangGraph, OpenAI, Gemini, Anthropic
- **Frontend:** Next.js, React, TypeScript, Tailwind
- **Qualidade / infra:** pytest, pytest-asyncio, Ruff, Docker, Docker Compose, GitHub Actions (futuro)

## Verificação do backend

Ruff, pytest e Alembic também podem ser executados na raiz. O pacote e as migrations ficam em `backend/`, então o teste de schema usa esse caminho:

```bash
python -m ruff check .
python -m ruff format --check .
python -m pytest backend/tests/unit/test_user_schema.py -v
POSTGRES_DB=nexus_ai_test python -m pytest -v
POSTGRES_DB=nexus_ai_test python -m alembic check
```

Dentro de `backend/`, o mesmo teste de schema é `tests/unit/test_user_schema.py`. O `alembic.ini` da raiz aponta para `backend/alembic`.

## Estrutura do monorepo

```text
.
├── backend/           # API e subsistema de IA
├── frontend/          # Aplicação Next.js (ainda não criada)
├── infrastructure/    # Docker auxiliar e nginx
├── docs/              # Arquitetura, API, ADRs e diagramas
└── .github/workflows/ # CI/CD (ainda não configurado)
```
