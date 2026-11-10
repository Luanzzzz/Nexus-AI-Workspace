# ADR 0007: rate limit em memória, proxy confiável e cadastro genérico

## Problema

A auditoria da Fase 2 (Authentication) mostrou três riscos de exposição pública:

1. `POST /auth/login` e `POST /auth/register` não tinham limite de taxa (A1).
2. O IP do cliente não pode ser lido de `X-Forwarded-For` sem uma lista de proxies confiáveis (I5); o default do uvicorn aceita o cabeçalho de `127.0.0.1`.
3. O cadastro respondia 409 `"Email já cadastrado."` e gastava ~3 ms no email existente contra ~60 ms no novo (A4).

## Opções

- Rate limit no proxy/WAF/plataforma, Redis compartilhado, ou limitador em memória no processo.
- IP só do socket, ou `X-Forwarded-For` quando o peer está em `TRUSTED_PROXIES`.
- Manter 409, responder 202/e-mail de verificação (não existe e-mail no MVP), ou a mesma resposta genérica nos dois caminhos, com hash Argon2 nos dois.

## Decisão

- **Rate limit em memória por processo**, sem dependência nova (nem Redis nem SlowAPI). Chaves: `login:ip`, `login:email` e `register:ip`. Resposta 429 com `Retry-After`. Limites padrão: 5 logins por email / 60 s, 20 logins por IP / 60 s, 5 cadastros por IP / 60 s. Desligável com `AUTH_RATE_LIMIT_ENABLED=false` (os testes usam isso).
- **`TRUSTED_PROXIES` vazio por padrão.** Só então o primeiro hop de `X-Forwarded-For` entra na chave. O proxy de produção deve **sobrescrever** o cabeçalho e o uvicorn deve subir com `--forwarded-allow-ips` igual a essa lista (nunca `*`).
- **Cadastro genérico:** `POST /auth/register` devolve sempre HTTP 201 e `{"detail": "Cadastro processado."}`, para email novo e já cadastrado. O hash Argon2id roda nos dois caminhos. A unicidade continua no `UNIQUE(email)`; corrida vira o mesmo corpo, sem duplicar linha.

## Trade-offs

- O cliente de cadastro não recebe `UserResponse` nem distingue email ocupado. O próximo passo é o login. Isso segue a [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) (não enumerar contas) e piora a UX de "este email já existe".
- O limitador em memória **não é compartilhado entre workers**. Dois processos uvicorn dobram o teto efetivo. Antes de expor a API publicamente, o teto precisa ir para o proxy, a plataforma ou um store compartilhado.
- Sem Redis de propósito: o MVP de estudo local não introduz esse serviço. Quando a hospedagem existir, uma ADR nova escolhe o backend.

## Dependências

Nenhuma biblioteca nova. O limitador é janela deslizante em `app/core/rate_limit.py`.
