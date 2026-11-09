# ADR 0006: JWT de acesso com PyJWT e HS256

## Problema

O login precisa devolver um token que o backend consiga validar sem consultar o banco a cada requisição. Falta decidir algoritmo de assinatura, biblioteca, origem do segredo, claims, expiração e o que o token não carrega.

## Opções

- HS256 (segredo compartilhado) ou RS256 (par de chaves). RS256 permite que terceiros validem sem poder emitir, mas exige gerar, guardar e rotacionar um par de chaves. Hoje só o backend emite e valida.
- Bibliotecas: PyJWT ou python-jose. PyJWT é pequena, mantida e cobre só o que usamos.
- Segredo com valor padrão para facilitar o desenvolvimento, ou segredo obrigatório sem padrão.
- Access token sozinho ou com refresh token.

## Decisão

- Biblioteca: PyJWT.
- Algoritmo: HS256 fixo. `Settings.jwt_algorithm` é um `Literal["HS256"]`, e o `decode` recebe `algorithms=[...]` com esse único valor. Tokens `alg=none` ou HS512 são rejeitados. RS256 fica fora do MVP: só existe um emissor/validador e não há serviço externo que precise verificar o token. Se isso mudar, uma nova ADR troca o algoritmo.
- Segredo: `JWT_SECRET_KEY` (`SecretStr`), obrigatório via ambiente ou `.env`, sem valor padrão. A aplicação não sobe com segredo ausente, com menos de 32 bytes ou com placeholder conhecido (`changeme`, `CHANGE_ME_LOCAL` etc.). O `.env.example` deixa o campo vazio e documenta a geração: `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Nos testes, o `conftest.py` define um segredo aleatório antes de importar a configuração.
- Claims obrigatórias: `sub`, `iat`, `exp`, `iss`, `aud` e `token_type="access"`. `sub` é `str(user.id)` e deve ser inteiro positivo. `iss="nexus-ai-workspace"` e `aud="nexus-api"`. Todas as claims são exigidas e conferidas na validação; qualquer falha vira a mesma `InvalidTokenError`, sem detalhe do motivo.
- Expiração: 30 minutos (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`), calculada pelo backend em UTC.
- Sem roles, email ou dados de workspace no token. Permissões são lidas do banco quando necessárias, então mudanças valem de imediato.
- Sem refresh token no MVP. Depois de expirar, o usuário faz login de novo.

## Limitações

- Não há revogação: um token roubado vale até `exp`. A janela curta de 30 minutos reduz o risco, não o elimina.
- JWT assinado não é criptografado. Qualquer um com o token lê as claims, por isso não colocamos email nem dados sensíveis.
- Vazar o segredo permite forjar tokens de qualquer usuário. A rotação do segredo invalida todos os tokens existentes.
- Força bruta no login e rate limit continuam pendentes e precisam existir antes de expor a API publicamente.
