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
- **`TRUSTED_PROXIES` vazio por padrão.** O uvicorn **não** usa o default `forwarded_allow_ips=127.0.0.1`. A entrada `python -m app` liga `proxy_headers` só quando a lista tem IPs, com `--forwarded-allow-ips` igual a ela (nunca `*`). Com lista vazia, `proxy_headers=False`: um `X-Forwarded-For` forjado a partir do loopback não reescreve `request.client`.
- **Cadeia XFF da direita.** Se o peer TCP está na lista, o app percorre os hops da direita para a esquerda e usa o primeiro que não é confiável. O hop da esquerda é controlado pelo cliente e é ignorado quando o proxy anexa.
- **Cadastro genérico:** `POST /auth/register` devolve sempre HTTP 201 e `{"detail": "Cadastro processado."}`, para email novo e já cadastrado. O hash Argon2id roda nos dois caminhos. A unicidade continua no `UNIQUE(email)`; corrida vira o mesmo corpo, sem duplicar linha.
- **Chave de email canônica:** a mesma função do login/cadastro — `EmailStr` do Pydantic seguido de minúsculas (`app.core.emailcanon.canonicalize_email`). Não usar `email_validator.validate_email` isolado: ele recusa o formato RFC 5322 `Nome <user@host>` e o fallback `strip().lower()` geraria uma chave por nome de exibição, enquanto o `EmailStr` do schema aceita o formato e autentica a vítima. Alinhar à canonicalização do schema (em vez de recusar name-addr no `CanonicalEmail`) preserva o contrato HTTP atual e faz `Ana <victim@x>` e `Bruno <victim@x>` compartilharem o teto de 5/60 s.
- **Teto de chaves (4096) fail-closed:** nunca descartar chave com janela ainda ativa. Ao bater o teto, o limitador só remove chaves expiradas; se continuar cheio, uma chave **nova** recebe 429 e um warning sem PII. Chaves já rastreadas seguem o teto normal. Redis continua fora de escopo; o estado permanece por processo.

## Trade-offs

- O cliente de cadastro não recebe `UserResponse` nem distingue email ocupado. O próximo passo é o login. Isso segue a [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) (não enumerar contas) e piora a UX de "este email já existe".
- O limitador em memória **não é compartilhado entre workers**. Dois processos uvicorn dobram o teto efetivo. Antes de expor a API publicamente, o teto precisa ir para o proxy, a plataforma ou um store compartilhado.
- **Saturação do mapa de chaves:** não evictar janelas ativas impede um atacante de “empurrar” a chave da vítima para fora do mapa. O custo é fail-closed para identidades novas enquanto o mapa está cheio (risco de negar serviço a usuários novos sob tráfego distribuído). O warning não registra a chave. Sem Redis neste MVP.
- **Login da vítima (chave por email):** qualquer IP pode esgotar as 5 tentativas / 60 s de um email conhecido e adiar o login legítimo. Mitigação neste MVP: o teto por IP (20/60 s) limita um único atacante; o teto por email evita força bruta distribuída na mesma conta. Não há captcha nem lockout. Quem for expor a API deve colocar o limite também no proxy e, se o lockout por conta for inaceitável, subir `AUTH_LOGIN_PER_EMAIL_LIMIT` ou desligar só a chave de email depois de ter WAF.
- Sem Redis de propósito: o MVP de estudo local não introduz esse serviço. Quando a hospedagem existir, uma ADR nova escolhe o backend.
- Quem sobe com `uvicorn app.main:app` **sem** `python -m app` volta ao default inseguro do uvicorn (loopback honra XFF). O README e este ADR fixam a entrada suportada.

## Dependências

Nenhuma biblioteca nova. O limitador é janela deslizante em `app/core/rate_limit.py`.
