# ADR 0003: email canônico em minúsculas no cadastro

## Problema

O cadastro precisa identificar a mesma conta sem diferenciar maiúsculas de minúsculas. A biblioteca `email-validator` normaliza o domínio e preserva a caixa da parte local. Sem uma convenção própria, `USUARIO@EXAMPLE.COM` e `usuario@example.com` seriam contas diferentes.

## Opções

- Confiar só no `email-validator`: domínio em minúsculas, parte local com a caixa original.
- Tratar o endereço inteiro sem diferenciação de maiúsculas e minúsculas, com representação canônica em minúsculas.

## Decisão

No Nexus, o `UserRegister` valida com `EmailStr` e em seguida converte o endereço inteiro para minúsculas.

Isso é uma convenção do produto para simplificar cadastro e o futuro login. Não é uma regra universal de email. Em alguns sistemas, a parte anterior ao `@` diferencia maiúsculas de minúsculas. Aceitamos esse trade-off no MVP.

A senha não segue essa normalização. O comprimento de 15 a 128 caracteres também é política do Nexus: o mínimo acompanha a autenticação somente por senha do NIST SP 800-63B-4, e 128 é o teto operacional inicial. Não há regras obrigatórias de composição. Isso não implementa os demais controles do NIST, como o bloqueio de senhas comprometidas.
