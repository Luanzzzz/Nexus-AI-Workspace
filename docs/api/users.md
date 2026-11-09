# Contrato de usuário

`POST /api/v1/auth/register` cria o usuário. O corpo é `UserRegister`. A resposta de sucesso é `UserResponse`, HTTP 201. Não há rota de login.

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
- Não existe schema de login. Quando ele for criado, precisa reutilizar a mesma forma canônica de email, senão o endereço em minúsculas do cadastro não encontra a conta.
