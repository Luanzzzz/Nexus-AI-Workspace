# ADR 0006: JWT de acesso com PyJWT e HS256

## Problema

O login precisa devolver um token que o backend consiga validar. Falta decidir algoritmo de assinatura, biblioteca, origem do segredo, claims, expiração e o que o token não carrega. A dependência `get_current_user` consulta o banco a cada requisição protegida: o JWT prova a emissão; o PostgreSQL decide se a conta ainda está ativa.

## Opções

- HS256 (segredo compartilhado) ou RS256 (par de chaves). RS256 permite que terceiros validem sem poder emitir, mas exige gerar, guardar e rotacionar um par de chaves. Hoje só o backend emite e valida.
- Bibliotecas: PyJWT ou python-jose. PyJWT é pequena, mantida e cobre só o que usamos.
- Segredo com valor padrão para facilitar o desenvolvimento, ou segredo obrigatório sem padrão.
- Access token sozinho ou com refresh token.

## Decisão

- Biblioteca: PyJWT.
- Algoritmo: HS256 fixo. `Settings.jwt_algorithm` é um `Literal["HS256"]`, e o `decode` recebe `algorithms=[...]` com esse único valor. Tokens `alg=none` ou HS512 são rejeitados. RS256 fica fora do MVP: só existe um emissor/validador e não há serviço externo que precise verificar o token. Se isso mudar, uma nova ADR troca o algoritmo.
- Segredo: `JWT_SECRET_KEY` (`SecretStr`), obrigatório via ambiente ou `.env`, sem valor padrão. A aplicação não sobe com segredo ausente, com espaços nas extremidades, com menos de 32 bytes, com placeholder (valor igual ou só repetição de `changeme` / `change_me_local` / `your-secret-key` etc.) ou com baixa entropia (poucos caracteres distintos). A mensagem de erro não ecoa o valor (`hide_input_in_errors=True`). O `.env.example` deixa o campo vazio e documenta a geração: `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Nos testes, o `conftest.py` define um segredo aleatório antes de importar a configuração.
- Claims obrigatórias: `sub`, `iat`, `exp`, `iss`, `aud` e `token_type="access"`. `sub` é `str(user.id)` e deve ser inteiro positivo. `iss="nexus-ai-workspace"` e `aud="nexus-api"`. Todas as claims são exigidas e conferidas na validação; qualquer falha vira a mesma `InvalidTokenError`, sem detalhe do motivo.
- Validação defensiva das claims: `sub` é string só com dígitos ASCII (sem sinal, espaço ou ponto), com no máximo 10 caracteres e valor entre 1 e 2147483647, o limite de `users.id` (`Integer`/INT4). `iat` e `exp` devem ser `int` (não `bool`, `float` nem string numérica, que o PyJWT aceitaria), entre 1 e 253402300799 (9999-12-31T23:59:59Z, máximo de `datetime`) e com `exp > iat`. Qualquer falha vira `InvalidTokenError`, sem detalhe. `create_access_token` rejeita `user_id` não inteiro, `bool` ou fora de 1..2147483647 com `ValueError`.
- Expiração: 30 minutos (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`), calculada pelo backend em UTC.
- Sem roles, email ou dados de workspace no token. Permissões são lidas do banco quando necessárias, então mudanças valem de imediato.
- Sem refresh token no MVP. Depois de expirar, o usuário faz login de novo.

## Limitações

- Não há revogação individual nem logout: um token de conta **ativa** vale até `exp`. Desativar ou remover o usuário faz `get_current_user` responder 401 na próxima requisição. Reset de senha (ainda inexistente) não invalidaria tokens já emitidos.
- JWT assinado não é criptografado. Qualquer um com o token lê as claims, por isso não colocamos email nem dados sensíveis.
- Vazar o segredo permite forjar tokens de qualquer usuário. A rotação do segredo invalida todos os tokens existentes.
- Rate limit de login/cadastro e o cadastro genérico estão no [ADR 0007](0007-rate-limit-proxy-e-cadastro-generico.md). O teto de concorrência do Argon2id (executor padrão do asyncio) continua implícito; precisa de benchmark na VPS de destino.
- Redis não será introduzido agora.
- Produção exige `DEBUG=false`. `Settings.environment` é `Literal["development", "test", "production"]` (`ENVIRONMENT`, padrão `development`). `DEBUG=true` só liga o modo debug do FastAPI quando `ENVIRONMENT=development`; em production a combinação é recusada. Em production as rotas `/docs`, `/redoc` e `/openapi.json` ficam desligadas. O middleware de erro interno responde 500 JSON sem relançar a exceção, então o traceback do uvicorn não vai ao cliente.
