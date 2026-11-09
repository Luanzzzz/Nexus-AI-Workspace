# Contrato de usuário

`POST /api/v1/auth/register` cria o usuário. O corpo é `UserRegister`. A resposta de sucesso é `UserResponse`, HTTP 201. O login está descrito em [Login](#login).

O router chama o `AuthService`. O serviço canonicaliza o email, consulta, gera o hash Argon2id fora do event loop e grava. O `UserRepository` não baixa a caixa do email, não recebe senha em claro e não confirma a transação. Ver [ADR 0005](../decisions/0005-transacao-do-cadastro.md).

## UserRegister

Campos obrigatórios: `name`, `email` e `password`. Campos extras são rejeitados (`extra="forbid"`), inclusive `is_active` e `password_hash`.

O schema valida a entrada. Ele não calcula hash, não grava no banco e não autentica.

| Campo | Política |
| --- | --- |
| `name` | Texto de exibição. Espaços nas extremidades são removidos. Depois disso, mínimo 1 e máximo 150 caracteres. Uma palavra, acentos e hífens são aceitos. |
| `email` | `EmailStr`, com `email-validator` declarado em `backend/pyproject.toml`. O endereço inteiro é guardado em minúsculas. Ver [ADR 0003](../decisions/0003-canonicalizacao-de-email-no-cadastro.md). |
| `password` | Mínimo 15 e máximo 128 caracteres. Sem exigência de símbolo, número ou maiúscula. Sem `strip`, sem conversão para minúsculas e sem remoção silenciosa de caracteres. Espaços e Unicode permanecem como foram enviados, dentro do limite de comprimento. |

Erros de validação relevantes: `missing`, `string_too_short`, `string_too_long`, `value_error` no email inválido e `extra_forbidden`.

O HTTP 422 não usa `UserResponse`. O handler central tira `password` e `password_hash` dos detalhes públicos, inclusive quando o valor está aninhado em `input`. O detalhe mantém `loc`, `type` e a mensagem. O handler não registra o `input` da senha.

## Sucesso e duplicidade

HTTP 201 devolve `id`, `name`, `email`, `is_active`, `created_at` e `updated_at`. `password` e `password_hash` não entram nessa resposta. `is_active` sai do default do model (`True`), não do cliente.

O email gravado é o canônico, em minúsculas. `USUARIO@EXAMPLE.COM` e `usuario@example.com` são a mesma conta: o segundo cadastro responde HTTP 409 com `{"detail": "Email já cadastrado."}`. Esse corpo não traz senha nem hash.

A coluna continua `String` com `UNIQUE(email)` e agora também `CHECK (email = lower(email))`. Ver [ADR 0004](../decisions/0004-restricao-de-email-canonico.md).

## UserResponse

Somente campos públicos: `id`, `name`, `email`, `is_active`, `created_at` e `updated_at`.

`password` e `password_hash` não fazem parte da resposta. O schema aceita objeto do ORM com `from_attributes=True`.

## Limites que permanecem

- O limite de 128 caracteres é operacional do Nexus. Aceitar pelo menos 64 caracteres e não exigir composição segue a direção do NIST SP 800-63B-4, mas isto não é conformidade completa com o NIST.
- O schema aceita senhas longas e triviais, como 15 espaços ou 15 vezes a mesma letra. Isso segue a regra de comprimento. Não vamos acrescentar exigência de símbolo, número ou maiúscula para compensar. Senhas comprometidas ou excessivamente comuns ficam para uma política separada, fora deste schema.
- O hash Argon2id continua em `hash_password()`, que permanece síncrono. A regra de comprimento do cadastro não altera esse módulo.
- `LoginRequest` reutiliza a mesma forma canônica de email do cadastro; sem isso o endereço em minúsculas não encontraria a conta.

## Login

`POST /api/v1/auth/login` recebe JSON (`LoginRequest`) e devolve um access token. Não é o fluxo OAuth2 password: não usa `application/x-www-form-urlencoded`, `username` nem `OAuth2PasswordRequestForm`.

O router só orquestra: chama `AuthService.authenticate` e emite o JWT depois do sucesso. O serviço não levanta `HTTPException`; os exception handlers traduzem as exceções de domínio em HTTP.

### Pedido

```json
{"email": "ana@example.com", "password": "senha-ficticia-ok"}
```

`email` é canonicalizado em minúsculas (`ANA@Example.com` entra na mesma conta). `password` tem de 1 a 128 caracteres, sem `strip`; não há tamanho mínimo de cadastro, para que senhas antigas ou erradas cheguem ao verificador. Campos extras são rejeitados.

### Resposta 200 (`TokenResponse`)

```json
{"access_token": "<jwt>", "token_type": "bearer"}
```

O token segue o [ADR 0006](../decisions/0006-jwt-access-token.md): HS256, expira em 30 minutos, `sub` é o id do usuário e não há email nem roles.

### Status

| Status | Quando | Corpo |
| --- | --- | --- |
| 200 | Credenciais válidas e conta ativa | `TokenResponse` |
| 401 | Email inexistente, senha errada ou conta inativa | `{"detail": "Credenciais inválidas."}` e `WWW-Authenticate: Bearer` |
| 422 | Corpo inválido, campo ausente, email inválido ou campo extra | `detail` com `loc`, `type` e `msg`, sem `input` nem a senha |
| 500 | Falha interna (hash armazenado corrompido, erro de banco, erro inesperado) | `{"detail": "Erro interno do servidor."}` |

O 401 é idêntico nos três casos, e o serviço faz uma verificação Argon2 em todos para igualar o custo. O 500 é distinto do 401 e não traz hash, SQL, email nem stack trace. O log de erro interno registra só o nome da classe da exceção; nenhum log traz senha, hash, token, segredo JWT ou email.

### Exemplo

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "ana@example.com", "password": "senha-ficticia-ok"}'
```

### Limites

- JWT assinado não é criptografado: qualquer portador lê as claims. Por isso o token não leva email nem dados sensíveis.
- Não há refresh token nem revogação. Um token vale até `exp` (30 minutos).
- **O login não está pronto para exposição pública.** Pendentes: controle de taxa (força bruta, OWASP Authentication Cheat Sheet) e controle de concorrência das verificações Argon2id, que custam CPU e memória. Não há rate limiting nesta etapa. Redis não será introduzido agora; os controles proporcionais dependem da hospedagem do MVP. Ver [ADR 0006](../decisions/0006-jwt-access-token.md).
- Produção exige `DEBUG=false` (`ENVIRONMENT=production` com `DEBUG=true` impede a inicialização); com debug o 500 vazaria traceback em vez do corpo genérico.
- O token só é aceito com `sub` inteiro positivo (até 2147483647) e `iat`/`exp` inteiros válidos; qualquer outra forma é rejeitada como token inválido.
- A única rota que consome o token é [`GET /api/v1/auth/me`](#usuário-atual).

## Usuário atual

`GET /api/v1/auth/me` devolve o usuário dono do token. Autenticação: cabeçalho `Authorization: Bearer <access_token>` (o token do [login](#login)). Não há corpo nem parâmetros.

A dependência `get_current_user` roda nesta ordem: extrai o Bearer (`HTTPBearer(auto_error=False)`), valida o JWT com `decode_access_token()`, lê o id de `sub` e só então consulta o usuário no PostgreSQL (`UserRepository.get_by_id`). O JWT prova apenas que o backend emitiu o token; o banco decide se a conta ainda pode usá-lo. A consulta ocorre em toda requisição protegida e a dependência devolve o `User` do ORM; a rota responde com `UserResponse`.

### Resposta 200 (`UserResponse`)

```json
{"id": 1, "name": "Ana Silva", "email": "ana@example.com", "is_active": true, "created_at": "2026-01-01T12:00:00Z", "updated_at": "2026-01-01T12:00:00Z"}
```

Só campos públicos; `password` e `password_hash` nunca saem.

### Status

| Status | Quando | Corpo |
| --- | --- | --- |
| 200 | Token válido de usuário existente e ativo | `UserResponse` |
| 401 | Token ausente, vazio, malformado, esquema que não é Bearer, assinatura inválida, expirado, usuário inexistente ou inativo | `{"detail": "Não autenticado."}` e `WWW-Authenticate: Bearer` |
| 500 | Banco indisponível ou erro inesperado | `{"detail": "Erro interno do servidor."}` |

O 401 é idêntico em todos os casos e não diferencia token inválido de conta removida ou desativada. Não se usa 403. Com token inválido, o banco nem é consultado. Falha do banco não vira 401: segue o tratamento HTTP 500 existente, sem SQL, credenciais nem token na resposta ou no log.

### Exemplo

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

### Limites

- Um token de usuário removido ou desativado deixa de valer na próxima requisição, mas não há revogação por token nem refresh token: um token válido de conta ativa vale até `exp`.
- Sem RBAC, roles ou workspace nesta etapa.
