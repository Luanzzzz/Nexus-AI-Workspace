# GitHub Actions

O workflow [`backend.yml`](backend.yml) roda em push e pull request:

1. `ruff check` e `ruff format --check`
2. `alembic upgrade head` e `alembic check` contra um serviço PostgreSQL 16 (`nexus_ai_test`)
3. `pytest` na suíte do backend

O build de imagem Docker fica de fora: o `backend/Dockerfile` ainda é placeholder.
