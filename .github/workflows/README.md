# GitHub Actions

O workflow [`backend.yml`](backend.yml) roda em push e pull request:

1. Job `unit`: `pytest -m "not integration"` **sem** serviço Postgres (`POSTGRES_PORT=1`) para provar que unitários não abrem conexão.
2. Job `test`: `ruff check` e `ruff format --check`
3. `alembic upgrade head` e `alembic check` contra um serviço PostgreSQL 17 (`nexus_ai_test`), a mesma major do `docker-compose.yml`. O job não usa a imagem `pgvector` porque a suíte de Authentication não precisa de extensão.
4. `pytest` na suíte completa do backend (incluindo integração)

O build de imagem Docker fica de fora: o `backend/Dockerfile` ainda é placeholder.
