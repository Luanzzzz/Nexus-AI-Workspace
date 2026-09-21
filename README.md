# Nexus AI Workspace

Projeto de portfólio focado em backend Python, engenharia de IA (RAG e agentes), PostgreSQL, testes e infraestrutura.

O objetivo é estudar e consolidar engenharia de software na prática, implementando as partes do sistema de forma incremental.

**Status:** em desenvolvimento. Esta versão contém apenas a estrutura inicial do monorepo. Não há funcionalidades implementadas.

## Stack planejada

- **Backend:** Python, FastAPI, Pydantic, SQLAlchemy, Alembic
- **Banco:** PostgreSQL, pgvector, Redis
- **IA:** LangChain, LangGraph, OpenAI, Gemini, Anthropic
- **Frontend:** Next.js, React, TypeScript, Tailwind
- **Qualidade / infra:** pytest, pytest-asyncio, Ruff, Docker, Docker Compose, GitHub Actions (futuro)

## Estrutura do monorepo

```text
.
├── backend/           # API e subsistema de IA
├── frontend/          # Aplicação Next.js (ainda não criada)
├── infrastructure/    # Docker auxiliar e nginx
├── docs/              # Arquitetura, API, ADRs e diagramas
└── .github/workflows/ # CI/CD (ainda não configurado)
```
