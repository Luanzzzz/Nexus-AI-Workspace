"""Reconciliação entre linhas de `documents` e blobs no storage local.

A exclusão e o upload não são atômicos entre Postgres e filesystem; falhas
parciais podem deixar blobs órfãos (sem linha) e temporários `.part` antigos.
Estas funções são manuais: nenhuma CLI nem agendador as chama ainda (fase
futura). `dry_run=True` (padrão) só reporta.

Garantias de segurança:
- só atua sobre arquivos regulares com nome de chave válida dentro do storage
  (varredura por descritores com O_NOFOLLOW; symlinks e nomes estranhos são
  ignorados);
- um blob com linha em `documents` nunca é removido (a existência é consultada
  no banco por chave antes de cada lote);
- só considera blobs mais antigos que `min_age_seconds` (padrão 1 h): um upload
  em andamento publica o blob antes de confirmar a linha e não pode ser
  confundido com órfão;
- logs não carregam chaves nem caminhos, só contagens.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.storage.local import LocalDocumentStorage

logger = logging.getLogger(__name__)

DEFAULT_MIN_AGE_SECONDS = 3600
DEFAULT_TMP_MAX_AGE_SECONDS = 3600
_BATCH = 500


@dataclass(frozen=True)
class ReconciliationReport:
    orphan_blobs: tuple[str, ...]
    stale_tmp: tuple[str, ...]
    removed_blobs: int
    removed_tmp: int
    dry_run: bool


async def find_orphan_blobs(
    session: AsyncSession,
    storage: LocalDocumentStorage,
    *,
    min_age_seconds: float = DEFAULT_MIN_AGE_SECONDS,
    now: float | None = None,
) -> list[str]:
    """Chaves de blobs antigos o bastante e sem linha em `documents`."""
    cutoff = (time.time() if now is None else now) - min_age_seconds
    candidates = [
        key
        for key, mtime in await asyncio.to_thread(storage.list_blobs)
        if mtime <= cutoff
    ]
    orphans: list[str] = []
    for start in range(0, len(candidates), _BATCH):
        batch = candidates[start : start + _BATCH]
        known = set(
            await session.scalars(
                select(Document.storage_key).where(Document.storage_key.in_(batch))
            )
        )
        orphans.extend(key for key in batch if key not in known)
    return sorted(orphans)


async def find_stale_tmp(
    storage: LocalDocumentStorage,
    *,
    max_age_seconds: float = DEFAULT_TMP_MAX_AGE_SECONDS,
    now: float | None = None,
) -> list[str]:
    cutoff = (time.time() if now is None else now) - max_age_seconds
    return sorted(
        name
        for name, mtime in await asyncio.to_thread(storage.list_tmp)
        if mtime <= cutoff
    )


async def reconcile_orphans(
    session: AsyncSession,
    storage: LocalDocumentStorage,
    *,
    dry_run: bool = True,
    min_age_seconds: float = DEFAULT_MIN_AGE_SECONDS,
    tmp_max_age_seconds: float = DEFAULT_TMP_MAX_AGE_SECONDS,
    now: float | None = None,
) -> ReconciliationReport:
    orphans = await find_orphan_blobs(
        session, storage, min_age_seconds=min_age_seconds, now=now
    )
    stale = await find_stale_tmp(storage, max_age_seconds=tmp_max_age_seconds, now=now)
    removed_blobs = removed_tmp = 0
    if not dry_run:
        for key in orphans:
            try:
                if await asyncio.to_thread(storage.delete, key):
                    removed_blobs += 1
            except Exception as exc:
                logger.error(
                    "Falha na reconciliação stage=blob type=%s", type(exc).__name__
                )
        for name in stale:
            try:
                if await asyncio.to_thread(storage.delete_tmp, name):
                    removed_tmp += 1
            except Exception as exc:
                logger.error(
                    "Falha na reconciliação stage=tmp type=%s", type(exc).__name__
                )
    logger.info(
        "Reconciliação orphans=%d stale_tmp=%d removed_blobs=%d "
        "removed_tmp=%d dry_run=%s",
        len(orphans),
        len(stale),
        removed_blobs,
        removed_tmp,
        dry_run,
    )
    return ReconciliationReport(
        orphan_blobs=tuple(orphans),
        stale_tmp=tuple(stale),
        removed_blobs=removed_blobs,
        removed_tmp=removed_tmp,
        dry_run=dry_run,
    )
