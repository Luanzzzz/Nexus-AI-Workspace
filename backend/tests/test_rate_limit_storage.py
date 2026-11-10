"""O limitador em memória descarta só chaves expiradas."""

import logging
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


def test_limiter_keeps_active_key_when_at_capacity():
    limiter = SlidingWindowLimiter(max_keys=3)
    window = 60
    assert limiter.hit("tracked", limit=2, window_seconds=window)[0] is True
    assert limiter.hit("tracked", limit=2, window_seconds=window)[0] is True
    blocked, _ = limiter.hit("tracked", limit=2, window_seconds=window)
    assert blocked is False

    assert limiter.hit("other-1", limit=5, window_seconds=window)[0] is True
    assert limiter.hit("other-2", limit=5, window_seconds=window)[0] is True
    assert limiter.hit("new", limit=5, window_seconds=window)[0] is False
    still_blocked, _ = limiter.hit("tracked", limit=2, window_seconds=window)
    assert still_blocked is False
    assert "tracked" in limiter._hits
    assert len(limiter) == 3


def test_limiter_rejects_new_key_until_windows_expire(caplog):
    limiter = SlidingWindowLimiter(max_keys=2)
    caplog.set_level(logging.WARNING)
    assert limiter.hit("a", limit=5, window_seconds=0.08)[0] is True
    assert limiter.hit("b", limit=5, window_seconds=0.08)[0] is True
    denied, retry_after = limiter.hit("c", limit=5, window_seconds=0.08)
    assert denied is False
    assert retry_after >= 1
    messages = [record.getMessage() for record in caplog.records]
    assert any("limitador saturado" in message for message in messages)
    assert all("c" not in record.args for record in caplog.records if record.args)
    time.sleep(0.12)
    assert limiter.hit("c", limit=5, window_seconds=0.08)[0] is True
