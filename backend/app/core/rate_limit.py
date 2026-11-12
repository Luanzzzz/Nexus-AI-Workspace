"""Limitador em memória por processo (janela deslizante)."""

from __future__ import annotations

import logging
from collections import defaultdict
from threading import Lock
from time import monotonic

_DEFAULT_MAX_KEYS = 4096
_PRUNE_EVERY = 32

logger = logging.getLogger(__name__)


class SlidingWindowLimiter:
    def __init__(self, max_keys: int = _DEFAULT_MAX_KEYS) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._max_keys = max_keys
        self._ops = 0

    def __len__(self) -> int:
        return len(self._hits)

    def hit(self, key: str, limit: int, window_seconds: float) -> tuple[bool, int]:
        """Registra um evento. Devolve (permitido, Retry-After em segundos)."""
        now = monotonic()
        with self._lock:
            self._ops += 1
            if self._ops % _PRUNE_EVERY == 0:
                self._drop_expired(now, window_seconds)
            cutoff = now - window_seconds
            stamps = self._hits.get(key)
            if stamps is not None:
                stamps[:] = [stamp for stamp in stamps if stamp > cutoff]
                if not stamps:
                    del self._hits[key]
                    stamps = None
            if stamps is None:
                if len(self._hits) >= self._max_keys:
                    self._drop_expired(now, window_seconds)
                if len(self._hits) >= self._max_keys:
                    logger.warning(
                        "limitador saturado; recusando chave nova (sem evict de janela ativa)"
                    )
                    return False, max(int(window_seconds), 1)
                stamps = self._hits[key]
            if len(stamps) >= limit:
                oldest = stamps[0]
                retry_after = int(window_seconds - (now - oldest)) + 1
                return False, max(retry_after, 1)
            stamps.append(now)
            return True, 0

    def _drop_expired(self, now: float, window_seconds: float) -> None:
        cutoff = now - window_seconds
        expired = [
            key
            for key, stamps in self._hits.items()
            if not stamps or stamps[-1] <= cutoff
        ]
        for key in expired:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._ops = 0


limiter = SlidingWindowLimiter()


# Instâncias separadas: o limite de upload e o de criação de workspace não
# dividem chaves nem janelas com o de login/cadastro.
upload_limiter = SlidingWindowLimiter()
workspace_create_limiter = SlidingWindowLimiter()


class ConcurrencyLimiter:
    """Teto de operações simultâneas por chave (em memória, por processo)."""

    def __init__(self) -> None:
        self._active: dict[str, int] = {}
        self._lock = Lock()

    def acquire(self, key: str, limit: int) -> bool:
        with self._lock:
            current = self._active.get(key, 0)
            if current >= limit:
                return False
            self._active[key] = current + 1
            return True

    def release(self, key: str) -> None:
        with self._lock:
            current = self._active.get(key, 0)
            if current <= 1:
                self._active.pop(key, None)
            else:
                self._active[key] = current - 1

    def active(self, key: str) -> int:
        with self._lock:
            return self._active.get(key, 0)

    def reset(self) -> None:
        with self._lock:
            self._active.clear()


upload_concurrency = ConcurrencyLimiter()
