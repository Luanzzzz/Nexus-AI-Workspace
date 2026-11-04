# ADR 0001: unicidade global do slug de Workspace

## Problema

O documento técnico define `slug` como identificador legível do workspace, sem dizer se ele é único na plataforma ou apenas entre os workspaces de um mesmo dono.

## Opções

- `UNIQUE(slug)`: um slug identifica um único workspace em toda a tabela.
- `UNIQUE(owner_id, slug)`: o mesmo slug pode existir para proprietários diferentes.

## Decisão

O slug é único globalmente, com `UNIQUE(slug)`.

As rotas atuais usam `workspace_id`, não o slug. Ainda assim, o slug é o identificador legível do workspace. Se a unicidade fosse só por proprietário, dois workspaces poderiam compartilhar o mesmo slug e uma busca ou URL futura ficaria ambígua. A unicidade global mantém esse identificador inequívoco.
