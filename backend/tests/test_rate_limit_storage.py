"""O limitador em memória descarta chaves expiradas."""

import time

from app.core.rate_limit import SlidingWindowLimiter


def test_limiter_drops_expired_keys():
    limiter = SlidingWindowLimiter(max_keys=8)
    for index in range(6):
        allowed, _ = limiter.hit(f"k-{index}", limit=5, window_seconds=0.05)
        assert allowed is True
    assert len(limiter) == 6
    time.sleep(0.08)
    limiter.hit("fresh", limit=5, window_seconds=0.05)
    for _ in range(40):
        limiter.hit("fresh", limit=50, window_seconds=0.05)
    assert "k-0" not in limiter._hits
    assert len(limiter) <= 8


def test_limiter_enforces_max_keys():
    limiter = SlidingWindowLimiter(max_keys=3)
    for index in range(10):
        limiter.hit(f"cap-{index}", limit=5, window_seconds=60)
    assert len(limiter) <= 3
