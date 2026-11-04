# Backend

Pacote Python do Nexus AI Workspace.

Este diretório contém apenas a estrutura inicial (`app/`, `tests/`, `evals/`, `alembic/`). Nenhuma API, persistência ou integração de IA está implementada ainda.

## Ambiente de testes

O arquivo de ambiente da raiz (`.env.example`) usa `POSTGRES_DB=nexus_ai` para o desenvolvimento. Testes marcados com `integration` leem o banco em `database_url.database` e falham antes de qualquer SQL se esse nome não for `nexus_ai_test`.

```bash
POSTGRES_DB=nexus_ai_test python -m pytest
```
