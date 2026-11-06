# Contrato de usuário

Ainda não há rotas HTTP de cadastro ou login. O contrato abaixo é o do schema `UserRegister` e da resposta pública `UserResponse` em `backend/app/schemas/user.py`.

## UserRegister

Campos obrigatórios: `name`, `email` e `password`. Campos extras são rejeitados (`extra="forbid"`), inclusive `is_active` e `password_hash`.

O schema valida a entrada. Ele não calcula hash, não grava no banco e não autentica.

| Campo | Política |
| --- | --- |
| `name` | Texto de exibição. Espaços nas extremidades são removidos. Depois disso, mínimo 1 e máximo 150 caracteres. Uma palavra, acentos e hífens são aceitos. |
| `email` | `EmailStr`, com `email-validator` declarado em `backend/pyproject.toml`. O endereço inteiro é guardado em minúsculas. Ver [ADR 0003](../decisions/0003-canonicalizacao-de-email-no-cadastro.md). |
| `password` | Mínimo 15 e máximo 128 caracteres. Sem exigência de símbolo, número ou maiúscula. Sem `strip`, sem conversão para minúsculas e sem remoção silenciosa de caracteres. Espaços e Unicode permanecem como foram enviados, dentro do limite de comprimento. |

Erros de validação relevantes: `missing`, `string_too_short`, `string_too_long`, `value_error` no email inválido e `extra_forbidden`.

## UserResponse

Somente campos públicos: `id`, `name`, `email`, `is_active`, `created_at` e `updated_at`.

`password` e `password_hash` não fazem parte da resposta. O schema aceita objeto do ORM com `from_attributes=True`.

## Pendências de segurança

- O limite de 128 caracteres é operacional do Nexus. Aceitar pelo menos 64 caracteres e não exigir composição segue a direção do NIST SP 800-63B-4, mas isto não é conformidade completa com o NIST.
- Senhas comprometidas ainda não são bloqueadas. O NIST também trata esse controle, e ele fica fora deste schema.
- O hash Argon2id continua em `hash_password()`. A regra de comprimento do cadastro não altera esse módulo.
- Não existe schema de login. Quando ele for criado, precisa reutilizar a mesma forma canônica de email, senão o endereço em minúsculas do cadastro não encontra a conta.
