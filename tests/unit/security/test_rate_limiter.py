"""Unit tests for SlidingWindowRateLimiter and RateLimitPolicy."""

import pytest

from platform_core.errors import RateLimitExceededError
from platform_security.rate_limiting import (
    RateLimitPolicy,
    SlidingWindowRateLimiter,
    format_rate_limit_key,
)


def test_rate_limiter_permits_within_capacity() -> None:
    limiter = SlidingWindowRateLimiter(requests_per_minute=5, burst_limit=5)
    t0 = 1000.0

    # 5 requests in same second
    for i in range(5):
        assert limiter.is_allowed("user_1", timestamp=t0 + i * 0.1) is True

    # 6th request rejected
    assert limiter.is_allowed("user_1", timestamp=t0 + 0.6) is False


def test_rate_limiter_enforces_burst_limit() -> None:
    limiter = SlidingWindowRateLimiter(requests_per_minute=60, burst_limit=3)
    t0 = 1000.0

    # 3 requests in same second
    assert limiter.is_allowed("user_2", timestamp=t0) is True
    assert limiter.is_allowed("user_2", timestamp=t0 + 0.2) is True
    assert limiter.is_allowed("user_2", timestamp=t0 + 0.4) is True

    # 4th request in same 1-second window rejected due to burst limit
    assert limiter.is_allowed("user_2", timestamp=t0 + 0.6) is False

    # 1.5 seconds later, burst clears
    assert limiter.is_allowed("user_2", timestamp=t0 + 1.5) is True


def test_rate_limiter_composite_identity_and_tool_key() -> None:
    limiter = SlidingWindowRateLimiter(requests_per_minute=2, burst_limit=2)
    t0 = 1000.0

    key_ticket = format_rate_limit_key("agent_01", "get_ticket")
    key_diagnostics = format_rate_limit_key("agent_01", "find_slow_queries")

    assert limiter.is_allowed(key_ticket, timestamp=t0) is True
    assert limiter.is_allowed(key_ticket, timestamp=t0 + 0.1) is True
    assert limiter.is_allowed(key_ticket, timestamp=t0 + 0.2) is False

    # Diagnostics tool has separate capacity for the same agent
    assert limiter.is_allowed(key_diagnostics, timestamp=t0) is True
    assert limiter.is_allowed(key_diagnostics, timestamp=t0 + 0.1) is True


def test_rate_limiter_window_sliding() -> None:
    limiter = SlidingWindowRateLimiter(requests_per_minute=2, burst_limit=2)
    t0 = 1000.0

    assert limiter.is_allowed("user_3", timestamp=t0) is True
    assert limiter.is_allowed("user_3", timestamp=t0 + 10.0) is True
    assert limiter.is_allowed("user_3", timestamp=t0 + 20.0) is False

    # 65 seconds after t0, first request drops out of the 60-second window
    assert limiter.is_allowed("user_3", timestamp=t0 + 65.0) is True


def test_rate_limiter_custom_policy_model() -> None:
    policy = RateLimitPolicy(
        requests_per_window=10,
        window_seconds=30.0,
        burst_limit=2,
        burst_window_seconds=0.5,
    )
    limiter = SlidingWindowRateLimiter(policy=policy)
    t0 = 2000.0

    assert limiter.is_allowed("client_x", timestamp=t0) is True
    assert limiter.is_allowed("client_x", timestamp=t0 + 0.1) is True
    assert limiter.is_allowed("client_x", timestamp=t0 + 0.2) is False  # burst hit

    # 0.6s later burst resets
    assert limiter.is_allowed("client_x", timestamp=t0 + 0.6) is True


def test_check_rate_limit_raises_rate_limit_exceeded_error() -> None:
    limiter = SlidingWindowRateLimiter(requests_per_minute=1, burst_limit=1)
    t0 = 1000.0

    limiter.check_rate_limit("user_4", timestamp=t0)

    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.check_rate_limit("user_4", timestamp=t0 + 0.5)

    assert "rate limit" in str(exc_info.value).lower()
    assert exc_info.value.error_code == "RATE_LIMIT_EXCEEDED"
