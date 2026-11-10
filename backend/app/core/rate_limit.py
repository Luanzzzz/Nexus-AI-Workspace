"""Limitador em memória por processo (janela deslizante)."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from time import monotonic

_DEFAULT_MAX_KEYS = 4096
_PRUNE_EVERY = 32


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
            stamps = self._hits[key]
            cutoff = now - window_seconds
            stamps[:] = [stamp for stamp in stamps if stamp > cutoff]
            if len(stamps) >= limit:
                oldest = stamps[0]
                retry_after = int(window_seconds - (now - oldest)) + 1
                return False, max(retry_after, 1)
            stamps.append(now)
            self._enforce_cap()
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

    def _enforce_cap(self) -> None:
        overflow = len(self._hits) - self._max_keys
        if overflow <= 0:
            return
        oldest_keys = sorted(
            self._hits,
            key=lambda item: self._hits[item][-1] if self._hits[item] else 0,
        )[:overflow]
        for key in oldest_keys:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._ops = 0


limiter = SlidingWindowLimiter()
