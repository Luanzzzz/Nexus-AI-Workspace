# Nexus AI Workspace

## Documento Técnico v1.0

**Tipo:** Projeto de portfólio / SaaS de IA  
**Foco profissional:** Backend Python, Engenharia de IA e Engenharia de Software  
**Stack principal:** Python, FastAPI, PostgreSQL, pgvector, Redis, LangChain/LangGraph, Next.js, Docker  
**Objetivo:** Construir um sistema de IA suficientemente próximo de um produto real para demonstrar conhecimentos em backend, RAG, agentes, bancos de dados, testes, infraestrutura e desenvolvimento de APIs.

---

# 1. Visão geral

O **Nexus AI Workspace** será uma plataforma SaaS multi-tenant onde organizações poderão criar workspaces, carregar documentos, construir bases de conhecimento e interagir com agentes de IA.

Os agentes serão capazes de:

- consultar documentos utilizando RAG;
- responder perguntas com fontes;
- consultar dados estruturados;
- executar ferramentas;
- solicitar aprovação antes de ações sensíveis;
- manter histórico de conversas;
- registrar ações em logs de auditoria.

O objetivo não é construir apenas um chatbot com documentos.

O projeto deve demonstrar como integrar modelos de linguagem em uma aplicação backend real, considerando:

- arquitetura;
- segurança;
- persistência;
- processamento assíncrono;
- observabilidade;
- testes;
- avaliação de IA;
- infraestrutura.

---

# 2. Objetivos profissionais

O projeto será desenvolvido para demonstrar competências relevantes principalmente para vagas como:

### Backend Python

Demonstrar:

- Python;
- FastAPI;
- REST APIs;
- PostgreSQL;
- SQL;
- SQLAlchemy;
- migrations;
- async/await;
- testes;
- Docker;
- arquitetura backend;
- tratamento de erros;
- autenticação;
- autorização.

### Engenharia de IA

Demonstrar:

- integração com LLMs;
- embeddings;
- RAG;
- vector databases;
- prompt engineering;
- agentes;
- tool calling;
- LangChain;
- LangGraph;
- avaliação de respostas;
- observabilidade de LLMs;
- segurança na execução de ferramentas.

### Engenharia de Software

Demonstrar:

- organização de projeto;
- separação de responsabilidades;
- testes automatizados;
- CI/CD;
- documentação;
- padrões de código;
- logs;
- monitoramento;
- Git organizado.

---

# 3. Estratégia de desenvolvimento

O projeto será dividido em duas frentes com filosofias diferentes de desenvolvimento.

## 3.1 Backend / IA / Data / Testing / Infra

Essas áreas serão utilizadas como ambiente de aprendizado técnico.

Incluem:

- Python;
- FastAPI;
- PostgreSQL;
- SQLAlchemy;
- Redis;
- RAG;
- agentes;
- LangChain;
- LangGraph;
- testes;
- Docker;
- CI/CD;
- banco de dados;
- workers;
- observabilidade.

### Regra principal

O desenvolvimento dessas áreas **não será feito através de vibe coding**.

A IA poderá ser utilizada como:

- autocomplete;
- documentação interativa;
- explicação de conceitos;
- code review;
- debugger;
- auxílio arquitetural;
- geração de testes após entendimento;
- ajuda localizada quando houver bloqueio.

A IA não deverá assumir o desenvolvimento completo dessas áreas.

### Fluxo esperado

```text
Entender problema
      ↓
Pensar solução
      ↓
Escrever implementação
      ↓
Usar autocomplete quando necessário
      ↓
Executar
      ↓
Testar
      ↓
Debuggar
      ↓
Code review com IA
```

Caso ocorra um bloqueio técnico:

```text
Problema específico
      ↓
Criar agente temporário
      ↓
Explicar contexto
      ↓
Agente investiga somente aquele problema
      ↓
Entender solução
      ↓
Implementar/corrigir
```

O agente não deverá continuar desenvolvendo outras partes do projeto.

---

# 3.2 Frontend

O frontend poderá ser desenvolvido utilizando **vibe coding completo**.

Stack prevista:

- Next.js;
- React;
- TypeScript;
- Tailwind CSS.

O objetivo do frontend será:

- fornecer uma interface profissional;
- demonstrar o produto;
- permitir testar funcionalidades;
- facilitar demonstrações em entrevistas.

O frontend não será o principal objeto de estudo deste projeto.

A IA poderá:

- gerar componentes;
- criar páginas;
- criar layouts;
- implementar responsividade;
- melhorar UX;
- refatorar componentes;
- implementar dashboard;
- conectar APIs.

Mesmo assim, o código gerado deverá manter:

- organização mínima;
- componentes reutilizáveis;
- tipagem TypeScript;
- separação entre UI e chamadas de API.

---

# 3.3 Bootstrap inicial do projeto

Um agente poderá ser utilizado para criar a estrutura inicial do repositório.

Esse agente deverá criar apenas:

- diretórios;
- arquivos vazios;
- `.gitignore`;
- arquivos de configuração vazios ou mínimos;
- documentação inicial;
- estrutura de módulos.

### O agente NÃO deverá

- implementar endpoints;
- criar models completos;
- implementar autenticação;
- implementar RAG;
- implementar agentes;
- escrever lógica de negócio;
- criar queries;
- criar testes prontos;
- implementar infraestrutura funcional.

O objetivo é economizar tempo com trabalho mecânico sem remover a parte de aprendizado.

---

# 4. Arquitetura geral

```text
                        ┌──────────────────┐
                        │     Next.js      │
                        │                  │
                        │ Dashboard        │
                        │ Chat             │
                        │ Documents        │
                        │ Agents           │
                        │ Settings         │
                        └────────┬─────────┘
                                 │
                              HTTP/SSE
                                 │
                        ┌────────▼─────────┐
                        │     FastAPI      │
                        │                  │
                        │ REST API         │
                        │ Authentication   │
                        │ Authorization    │
                        │ Business Logic   │
                        └───────┬──────────┘
                                │
              ┌─────────────────┼──────────────────┐
              │                 │                  │
              ▼                 ▼                  ▼
       PostgreSQL             Redis            AI Engine
       + pgvector                               │
                                               │
                                  ┌────────────┼──────────┐
                                  ▼            ▼          ▼
                              OpenAI        Gemini    Anthropic

                                │
                                ▼

                         Background Worker
                         document ingestion
                         embeddings
                         async jobs
```

---

# 5. Arquitetura do backend

O backend seguirá separação de responsabilidades.

```text
backend/
│
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── dependencies/
│   │   └── v1/
│   │       ├── auth.py
│   │       ├── users.py
│   │       ├── workspaces.py
│   │       ├── documents.py
│   │       ├── conversations.py
│   │       ├── agents.py
│   │       ├── tools.py
│   │       └── health.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── exceptions.py
│   │   └── logging.py
│   │
│   ├── db/
│   │   ├── session.py
│   │   ├── base.py
│   │   └── migrations/
│   │
│   ├── models/
│   │
│   ├── schemas/
│   │
│   ├── repositories/
│   │
│   ├── services/
│   │
│   ├── ai/
│   │   ├── providers/
│   │   ├── embeddings/
│   │   ├── retrieval/
│   │   ├── rag/
│   │   ├── agents/
│   │   ├── tools/
│   │   └── prompts/
│   │
│   ├── workers/
│   │
│   └── utils/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
│
├── evals/
│   ├── datasets/
│   ├── runners/
│   └── results/
│
├── scripts/
│
├── alembic/
│
├── pyproject.toml
├── Dockerfile
└── README.md
```

---

# 6. Estrutura geral do monorepo

```text
nexus-ai-workspace/
│
├── backend/
│
├── frontend/
│
├── infrastructure/
│   ├── docker/
│   └── nginx/
│
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── decisions/
│   └── diagrams/
│
├── .github/
│   └── workflows/
│
├── docker-compose.yml
│
├── .env.example
│
├── .gitignore
│
├── README.md
│
├── CONTRIBUTING.md
│
└── LICENSE
```

---

# 7. Stack tecnológica

## Backend

```text
Python
FastAPI
Pydantic
SQLAlchemy
Alembic
```

## Banco

```text
PostgreSQL
pgvector
Redis
```

## IA

```text
LangChain
LangGraph
OpenAI
Gemini
Anthropic
```

A arquitetura deverá permitir trocar o provider sem alterar o restante da aplicação.

Exemplo:

```text
LLMProvider
   │
   ├── OpenAIProvider
   ├── GeminiProvider
   └── AnthropicProvider
```

---

# 8. Entidades principais

## User

Representa um usuário da plataforma.

```text
id
name
email
password_hash
is_active
created_at
updated_at
```

---

## Workspace

Representa uma organização ou ambiente de trabalho.

```text
id
name
slug
owner_id
created_at
updated_at
```

---

## WorkspaceMember

Relaciona usuários aos workspaces.

```text
id
workspace_id
user_id
role
created_at
```

Roles iniciais:

```text
owner
admin
member
viewer
```

---

## Document

Documento enviado para uma base de conhecimento.

```text
id
workspace_id
uploaded_by
filename
mime_type
status
metadata
created_at
```

Estados:

```text
uploaded
processing
ready
failed
```

---

## DocumentChunk

Fragmento utilizado pelo mecanismo de RAG.

```text
id
document_id
content
chunk_index
embedding
metadata
created_at
```

---

## Conversation

```text
id
workspace_id
user_id
agent_id
title
created_at
updated_at
```

---

## Message

```text
id
conversation_id
role
content
metadata
created_at
```

Roles:

```text
user
assistant
system
tool
```

---

## Agent

```text
id
workspace_id
name
description
system_prompt
model
temperature
created_at
updated_at
```

---

## Tool

```text
id
workspace_id
name
description
configuration
requires_approval
enabled
created_at
```

---

## ToolCall

```text
id
conversation_id
agent_id
tool_name
arguments
result
status
created_at
executed_at
```

Estados:

```text
requested
pending_approval
approved
rejected
running
completed
failed
```

---

## AuditLog

```text
id
workspace_id
user_id
action
entity_type
entity_id
metadata
created_at
```

---

# 9. Multi-tenancy

Todas as informações pertencentes a uma empresa deverão possuir vínculo com um:

```text
workspace_id
```

Nunca deverá ser possível acessar dados de outro workspace apenas alterando IDs em endpoints.

Exemplo:

```text
/api/v1/workspaces/123/documents/50
```

O backend deverá verificar:

```text
current_user ∈ workspace 123
```

antes de retornar o documento.

---

# 10. Autenticação e autorização

Inicialmente:

```text
email + password
```

Autenticação:

```text
JWT Access Token
```

Possível evolução:

```text
Access Token
+
Refresh Token
```

Autorização baseada em:

```text
RBAC
```

Exemplo:

```text
OWNER
  ↓
gerencia workspace

ADMIN
  ↓
gerencia documentos/agentes

MEMBER
  ↓
usa agentes/chat

VIEWER
  ↓
somente leitura
```

---

# 11. API inicial

Prefixo:

```text
/api/v1
```

## Auth

```text
POST /auth/register
POST /auth/login
POST /auth/refresh
GET  /auth/me
```

---

## Workspaces

```text
POST   /workspaces
GET    /workspaces
GET    /workspaces/{workspace_id}
PATCH  /workspaces/{workspace_id}
DELETE /workspaces/{workspace_id}
```

---

## Members

```text
GET    /workspaces/{workspace_id}/members
POST   /workspaces/{workspace_id}/members
PATCH  /workspaces/{workspace_id}/members/{user_id}
DELETE /workspaces/{workspace_id}/members/{user_id}
```

---

## Documents

```text
POST   /workspaces/{workspace_id}/documents
GET    /workspaces/{workspace_id}/documents
GET    /workspaces/{workspace_id}/documents/{document_id}
DELETE /workspaces/{workspace_id}/documents/{document_id}
```

---

## Conversations

```text
POST /workspaces/{workspace_id}/conversations
GET  /workspaces/{workspace_id}/conversations

GET  /conversations/{conversation_id}
POST /conversations/{conversation_id}/messages
```

---

## Agents

```text
POST   /workspaces/{workspace_id}/agents
GET    /workspaces/{workspace_id}/agents
GET    /workspaces/{workspace_id}/agents/{agent_id}
PATCH  /workspaces/{workspace_id}/agents/{agent_id}
DELETE /workspaces/{workspace_id}/agents/{agent_id}
```

---

## Tool calls

```text
GET  /tool-calls/{tool_call_id}

POST /tool-calls/{tool_call_id}/approve
POST /tool-calls/{tool_call_id}/reject
```

---

# 12. Pipeline de RAG

Fluxo:

```text
Upload
    ↓
Document
    ↓
Text extraction
    ↓
Normalization
    ↓
Chunking
    ↓
Embedding
    ↓
pgvector
```

Consulta:

```text
User question
       ↓
Question embedding
       ↓
Vector search
       ↓
Relevant chunks
       ↓
Prompt context
       ↓
LLM
       ↓
Answer
       ↓
Citations
```

---

# 13. Requisitos do RAG

A resposta deverá conter:

- resposta;
- documentos utilizados;
- trechos utilizados;
- referências;
- score de similaridade quando disponível.

Exemplo:

```json
{
  "answer": "O prazo de troca é de 30 dias.",
  "sources": [
    {
      "document": "politica-trocas.pdf",
      "page": 4,
      "chunk_id": "..."
    }
  ]
}
```

---

# 14. Agentes

A segunda grande camada será baseada em agentes.

Fluxo:

```text
User request
      ↓
Agent
      ↓
Determine action
      ↓
Select tool
      ↓
Execute
      ↓
Observe result
      ↓
Answer
```

LangGraph poderá controlar o fluxo.

Exemplo conceitual:

```text
START
  ↓
Agent
  ↓
Need tool?
 ├── no → answer
 │
 └── yes
       ↓
     Tool
       ↓
 Requires approval?
       │
     ┌─┴─┐
    yes  no
     │    │
 approval execution
     │    │
     └────┘
       ↓
     Agent
       ↓
      END
```

---

# 15. Tools iniciais

Inicialmente serão utilizadas ferramentas internas de demonstração.

### Read-only

```text
search_knowledge_base
get_customer
get_orders
get_products
get_inventory
```

### Write actions

```text
create_task
update_customer
cancel_order
```

Ações destrutivas deverão utilizar aprovação humana.

---

# 16. Human-in-the-loop

Exemplo:

```text
Usuário:

"Cancele o pedido #882."
```

Agent:

```text
cancel_order(order_id=882)
```

Como a ferramenta exige aprovação:

```text
ToolCall.status = pending_approval
```

Frontend:

```text
Cancelar pedido #882?

[Cancelar]
[Rejeitar]
```

Somente após aprovação:

```text
ToolCall.status = approved
```

seguida pela execução.

---

# 17. Workers

Processos pesados não deverão bloquear requests HTTP.

Exemplo:

```text
upload document
      ↓
API
      ↓
enqueue job
      ↓
HTTP 202
```

Worker:

```text
extract text
      ↓
chunk
      ↓
embeddings
      ↓
database
```

Redis poderá ser utilizado como broker/cache.

A tecnologia de worker será escolhida posteriormente após estudar as alternativas.

Possibilidades:

```text
Celery
RQ
Arq
Dramatiq
```

A decisão deverá ser documentada através de ADR.

---

# 18. Async

O projeto deverá possuir casos reais de programação assíncrona.

Exemplos:

- chamadas para APIs de LLM;
- chamadas externas;
- streaming;
- acesso assíncrono ao banco;
- execução concorrente de ferramentas independentes.

O uso de `async` deverá existir por necessidade arquitetural e não apenas para aparecer no projeto.

---

# 19. Streaming

O chat deverá permitir streaming.

Fluxo:

```text
LLM
 ↓
token
 ↓
FastAPI
 ↓
SSE
 ↓
Next.js
```

Tecnologia inicial:

```text
Server-Sent Events
```

WebSocket poderá ser estudado posteriormente caso exista necessidade real.

---

# 20. Testes

O projeto deverá possuir três níveis principais.

## Unit

Testam componentes isolados.

Exemplos:

```text
chunking
permissions
text normalization
tool validation
prompt builders
```

---

## Integration

Testam integração entre componentes.

Exemplos:

```text
API + database
authentication
workspace permissions
document upload
conversation creation
```

---

## E2E

Poucos testes para fluxos críticos.

Exemplo:

```text
register
   ↓
login
   ↓
workspace
   ↓
upload
   ↓
RAG
   ↓
response
```

---

# 21. Ferramentas de qualidade

Inicialmente:

```text
pytest
pytest-asyncio
ruff
```

Opcional futuramente:

```text
mypy
coverage
```

---

# 22. CI

GitHub Actions deverá executar:

```text
Pull Request / Push
        ↓
Install dependencies
        ↓
Lint
        ↓
Tests
        ↓
Build
```

Pipeline esperado:

```text
ruff
pytest
docker build
```

---

# 23. Observabilidade

A aplicação deverá registrar:

```text
request_id
user_id
workspace_id
endpoint
latency
status
```

IA:

```text
model
provider
latency
input_tokens
output_tokens
total_tokens
estimated_cost
retrieved_chunks
tools_called
errors
```

---

# 24. AI Observability

O dashboard poderá mostrar:

```text
Total requests

Average latency

Token consumption

Estimated cost

RAG requests

Tool calls

Failures

Most used agents
```

Cada conversa poderá exibir:

```text
model
latency
tokens
retrieved chunks
tools executed
```

---

# 25. Avaliação de RAG

O projeto possuirá uma pasta:

```text
evals/
```

Datasets simples poderão ser armazenados como JSON.

Exemplo:

```json
{
  "question": "Qual o prazo de devolução?",
  "expected_answer": "30 dias",
  "expected_document": "politica.pdf"
}
```

O runner deverá medir inicialmente:

```text
document retrieval correctness
citation correctness
answer correctness
latency
```

O objetivo não será criar um benchmark científico completo.

O objetivo será demonstrar que sistemas baseados em IA precisam ser avaliados.

---

# 26. Tratamento de erros

O backend deverá possuir exceções padronizadas.

Formato esperado:

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Document not found",
    "request_id": "..."
  }
}
```

Não retornar diretamente:

```text
stack traces
database errors
LLM credentials
internal configuration
```

---

# 27. Segurança

Itens mínimos:

- passwords utilizando hashing seguro;
- secrets através de environment variables;
- `.env` fora do Git;
- RBAC;
- isolamento de workspace;
- validação Pydantic;
- rate limiting futuramente;
- validação de uploads;
- limite de tamanho de arquivos;
- logs de ações importantes.

---

# 28. Docker

Ambiente local deverá poder subir utilizando:

```bash
docker compose up
```

Serviços previstos:

```text
api
postgres
redis
worker
frontend
```

Durante desenvolvimento, o frontend poderá rodar separadamente.

---

# 29. Ambiente

Exemplo:

```text
.env
```

Base:

```text
DATABASE_URL=
REDIS_URL=

JWT_SECRET=

OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
```

O projeto conterá:

```text
.env.example
```

sem credenciais.

---

# 30. Documentação

A pasta:

```text
docs/
```

deverá conter documentação técnica.

## Architecture

```text
docs/architecture/
```

## ADR

```text
docs/decisions/
```

Exemplo:

```text
ADR-001-fastapi.md
ADR-002-postgresql-pgvector.md
ADR-003-sse-vs-websocket.md
ADR-004-worker-selection.md
```

---

# 31. README principal

O README deverá possuir futuramente:

1. descrição;
2. screenshots;
3. arquitetura;
4. funcionalidades;
5. stack;
6. como executar;
7. variáveis de ambiente;
8. testes;
9. API;
10. RAG;
11. agentes;
12. roadmap;
13. decisões arquiteturais.

---

# 32. MVP

O MVP não terá todas as funcionalidades descritas anteriormente.

MVP:

```text
Authentication
      +
Workspace
      +
Document upload
      +
Document ingestion
      +
pgvector
      +
RAG
      +
Chat
      +
Citations
      +
Basic frontend
      +
Docker
      +
Tests
```

Se isso funcionar corretamente, o Nexus já será apresentável.

---

# 33. MVP 2

Segunda etapa:

```text
Agents
+
Tools
+
LangGraph
+
Human approval
+
Audit logs
```

---

# 34. MVP 3

Terceira etapa:

```text
Observability
+
RAG evaluation
+
Redis
+
Workers
+
CI/CD
```

---

# 35. Funcionalidades fora do escopo inicial

Não implementar inicialmente:

- pagamentos;
- sistema complexo de billing;
- aplicativo mobile;
- marketplace de agentes;
- dezenas de providers;
- microservices;
- Kubernetes;
- event sourcing;
- multi-region;
- sistemas avançados de filas;
- dezenas de integrações externas.

O projeto deverá priorizar profundidade sobre quantidade de funcionalidades.

---

# 36. Estratégia de Git

Branches:

```text
main
develop
feature/*
fix/*
```

Exemplo:

```text
feature/authentication
feature/workspaces
feature/document-upload
feature/rag-retrieval
```

Commits deverão explicar mudanças.

Evitar:

```text
fix
update
changes
final
final-final
teste
```

Preferir:

```text
feat(auth): add JWT authentication

feat(rag): implement document chunking

test(workspace): add membership permission tests

fix(retrieval): filter chunks by workspace
```

---

# 37. Regra de commits com IA

Não realizar commits gigantes contendo dezenas de funcionalidades criadas por agentes.

Cada commit deverá representar uma mudança que o desenvolvedor entende.

Antes de commit:

```text
Entendo o código?
       ↓
Consigo explicar?
       ↓
Consigo alterar?
       ↓
Os testes passam?
       ↓
Commit
```

Se alguma resposta for não, o código ainda não deverá ser considerado concluído.

---

# 38. Definition of Done

Uma feature backend somente é considerada concluída quando:

- implementação funciona;
- código foi entendido;
- testes relevantes foram escritos;
- testes passam;
- lint passa;
- erros são tratados;
- documentação necessária foi atualizada;
- não existem secrets no código;
- endpoint foi testado manualmente quando necessário.

---

# 39. Roadmap

## Fase 0 — Project Foundation

Objetivo:

```text
Criar estrutura e ambiente.
```

Tarefas:

- criar monorepo;
- estruturar backend;
- estruturar frontend;
- criar docs;
- configurar Git;
- configurar `.gitignore`;
- criar `.env.example`;
- preparar Docker;
- preparar pyproject;
- criar README inicial.

Nenhuma lógica de negócio.

---

## Fase 1 — Backend Foundation

Estudar e implementar:

```text
FastAPI
Pydantic
SQLAlchemy
PostgreSQL
Alembic
```

Features:

```text
health check
database connection
User
Workspace
WorkspaceMember
```

---

## Fase 2 — Authentication

Implementar:

```text
register
login
JWT
password hashing
current user
```

Depois:

```text
RBAC
```

---

## Fase 3 — Documents

Implementar:

```text
upload
metadata
storage
status
permissions
```

---

## Fase 4 — RAG Foundation

Implementar:

```text
text extraction
chunking
embeddings
pgvector
similarity search
```

Inicialmente sem LangChain se for útil para entender os fundamentos.

Depois poderá ser criada abstração usando LangChain.

---

## Fase 5 — RAG Chat

Implementar:

```text
conversation
messages
retrieval
prompt
LLM
answer
citations
```

---

## Fase 6 — Frontend MVP

Utilizar vibe coding.

Páginas:

```text
/login

/dashboard

/documents

/chat
```

---

## Fase 7 — Agents

Estudar:

```text
function calling
tool calling
LangGraph
agent state
```

Implementar:

```text
Agent
Tools
ToolCall
```

---

## Fase 8 — Human approval

Implementar:

```text
pending tool calls

approve

reject

execute

audit
```

---

## Fase 9 — Async Processing

Adicionar:

```text
Redis
Worker
Document ingestion jobs
```

---

## Fase 10 — Observability

Adicionar:

```text
structured logs

LLM usage

latency

token tracking

cost estimation
```

---

## Fase 11 — Evaluation

Adicionar:

```text
evaluation datasets

retrieval tests

answer evaluation

citation evaluation
```

---

## Fase 12 — Portfolio Release

Finalização:

```text
deploy
README
screenshots
architecture diagram
demo video
sample workspace
sample documents
```

---

# 40. Resultado esperado

Ao finalizar o projeto, o desenvolvedor deverá conseguir explicar tecnicamente:

### Backend

- como FastAPI processa requests;
- dependency injection;
- autenticação JWT;
- async/await;
- SQLAlchemy;
- migrations;
- transactions;
- modelagem relacional;
- PostgreSQL.

### IA

- embeddings;
- similarity search;
- cosine similarity;
- vector databases;
- chunking;
- retrieval;
- RAG;
- contexto;
- agentes;
- tool calling;
- state machines;
- hallucination;
- avaliação.

### Infra

- containers;
- Docker;
- environment variables;
- workers;
- Redis;
- CI/CD.

### Testing

- unit tests;
- integration tests;
- mocks;
- fixtures;
- async tests.

---

# 41. Princípio central do projeto

O Nexus não será desenvolvido para demonstrar quantas bibliotecas o desenvolvedor conhece.

Será desenvolvido para demonstrar que ele entende:

```text
problema
   ↓
arquitetura
   ↓
implementação
   ↓
testes
   ↓
deploy
   ↓
observabilidade
```

A principal evidência de conhecimento será a capacidade de explicar as decisões tomadas durante o desenvolvimento.

---

# 42. Métrica de sucesso

O projeto estará cumprindo seu objetivo quando o desenvolvedor conseguir abrir uma parte importante do backend e responder:

```text
Por que isso existe?

Por que foi implementado dessa forma?

Quais alternativas existiam?

Quais trade-offs foram feitos?

Como isso é testado?

O que acontece se isso falhar?
```

sem precisar consultar uma IA para entender o próprio código.

---

# 43. Objetivo final de portfólio

A apresentação ideal será:

> Nexus AI Workspace é uma plataforma SaaS multi-tenant construída com FastAPI, PostgreSQL, pgvector e Next.js. O sistema implementa RAG com citações, agentes com tool calling, aprovação humana para ações sensíveis, processamento assíncrono, testes automatizados e observabilidade de LLMs. Desenvolvi principalmente a arquitetura e backend do sistema como um projeto de aprofundamento em Backend Python e Engenharia de IA.