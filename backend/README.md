# Backend

Pacote Python do Nexus AI Workspace.

Este diretório contém a API, a persistência e os testes do backend. A integração de IA ainda não foi implementada.

## Ambiente de testes

O desenvolvimento usa o banco `nexus_ai`. Os testes de integração usam outro banco, `nexus_ai_test`, para não gravar no banco de desenvolvimento.

Copie `.env.example` da raiz para `.env` e preencha os valores só na máquina local. O `.env` fica fora do Git. O exemplo versionado usa `CHANGE_ME_LOCAL` e não contém credencial real.

Antes de rodar os testes, aplique as migrations no banco de testes. Os modelos e os testes de integração esperam as tabelas criadas pelo Alembic:

```bash
POSTGRES_DB=nexus_ai_test python -m alembic upgrade head
POSTGRES_DB=nexus_ai_test python -m pytest
```

Testes marcados com `integration` leem o banco em `database_url.database`. Se o nome não for `nexus_ai_test`, o pytest interrompe o setup antes das fixtures e de qualquer SQL. Essa proteção impede o acesso acidental ao banco de desenvolvimento, inclusive quando o `.env` aponta para `nexus_ai`.
