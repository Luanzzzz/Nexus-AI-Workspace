"""Limitador em memória por processo (janela deslizante)."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from time import monotonic


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def hit(self, key: str, limit: int, window_seconds: float) -> tuple[bool, int]:
        """Registra um evento. Devolve (permitido, Retry-After em segundos)."""
        now = monotonic()
        with self._lock:
            stamps = self._hits[key]
            cutoff = now - window_seconds
            stamps[:] = [stamp for stamp in stamps if stamp > cutoff]
            if len(stamps) >= limit:
                oldest = stamps[0]
                retry_after = int(window_seconds - (now - oldest)) + 1
                return False, max(retry_after, 1)
            stamps.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()
