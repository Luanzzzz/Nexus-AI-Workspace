# ADR 0003: email canônico em minúsculas no cadastro

## Problema

O cadastro precisa identificar a mesma conta sem diferenciar maiúsculas de minúsculas. A biblioteca `email-validator` normaliza o domínio e preserva a caixa da parte local. Sem uma convenção própria, `USUARIO@EXAMPLE.COM` e `usuario@example.com` seriam contas diferentes.

## Opções

- Confiar só no `email-validator`: domínio em minúsculas, parte local com a caixa original.
- Tratar o endereço inteiro sem diferenciação de maiúsculas e minúsculas, com representação canônica em minúsculas.

## Decisão

No Nexus, o `UserRegister` valida com `EmailStr` e em seguida converte o endereço inteiro para minúsculas.

Isso é uma convenção do produto para simplificar cadastro e o futuro login. Não é uma regra universal de email. Em alguns sistemas, a parte anterior ao `@` diferencia maiúsculas de minúsculas. A OWASP também alerta que essa equivalência não vale para todos os provedores. Aceitamos esse trade-off no MVP.

A coluna `users.email` continua `String` com `unique=True`. Essa restrição diferencia maiúsculas de minúsculas, então não impede sozinha dois endereços que só variam na caixa. A Etapa 2.4 precisa aplicar a mesma forma canônica na persistência e na consulta de login, e avaliar uma restrição adicional no banco para os outros caminhos de escrita.

A senha não segue essa normalização. O comprimento de 15 a 128 caracteres também é política do Nexus: o mínimo acompanha a autenticação somente por senha do NIST SP 800-63B-4, e 128 é o teto operacional inicial. Não há regras obrigatórias de composição. Isso não implementa os demais controles do NIST, como o bloqueio de senhas comprometidas.

## Desdobramento

A Etapa 2.4 manteve `String` e `UNIQUE(email)` e acrescentou `CHECK (email = lower(email))`. O registro dessa restrição está no [ADR 0004](0004-restricao-de-email-canonico.md). A fronteira da transação de cadastro está no [ADR 0005](0005-transacao-do-cadastro.md).

`name` e `email` rejeitam caracteres de controle Unicode (categoria Cc, inclusive NUL). Isso evita 500 do PostgreSQL no `name`. A **senha** não passa por esse filtro: a OWASP pede aceitar qualquer caractere, o Argon2id aceita NUL, e o valor não é gravado em coluna `text`. No login, senha com NUL continua 401 (credencial inválida), não 422. Não há NFKC nem política de confusáveis no MVP; `ｆｕｌｌ@example.com` e `full@example.com` continuam identidades distintas.
