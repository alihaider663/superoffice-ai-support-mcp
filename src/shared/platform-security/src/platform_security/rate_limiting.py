"""Sliding window rate limiting primitive for caller identity, tool, and IP throttling."""

import time
from collections import deque
from typing import Any

from pydantic import Field, PositiveFloat, PositiveInt

from platform_core.errors import RateLimitExceededError
from platform_core.models import PlatformBaseModel


class RateLimitPolicy(PlatformBaseModel):
    """Declarative configuration for rate limiting thresholds."""

    requests_per_window: PositiveInt = Field(
        default=60,
        description="Maximum requests allowed within the main sliding window",
    )
    window_seconds: PositiveFloat = Field(
        default=60.0,
        description="Main sliding window duration in seconds",
    )
    burst_limit: PositiveInt = Field(
        default=10,
        description="Maximum requests allowed within the short burst window",
    )
    burst_window_seconds: PositiveFloat = Field(
        default=1.0,
        description="Burst window duration in seconds",
    )


def format_rate_limit_key(
    identity: str,
    tool_name: str,
    client_ip: str | None = None,
) -> str:
    """Build a composite rate limit key for (identity, tool, [optional_ip])."""
    base = f"{identity.strip()}::{tool_name.strip()}"
    if client_ip is not None and client_ip.strip():
        return f"{base}::{client_ip.strip()}"
    return base


class SlidingWindowRateLimiter:
    """In-memory deterministic sliding-window rate limiter."""

    def __init__(
        self,
        policy: RateLimitPolicy | None = None,
        *,
        requests_per_minute: int | None = None,
        burst_limit: int | None = None,
        window_seconds: float = 60.0,
        burst_window_seconds: float = 1.0,
    ) -> None:
        if policy is not None:
            self.policy = policy
        else:
            self.policy = RateLimitPolicy(
                requests_per_window=requests_per_minute or 60,
                window_seconds=window_seconds,
                burst_limit=burst_limit or 10,
                burst_window_seconds=burst_window_seconds,
            )
        self._history: dict[str, deque[float]] = {}

    @property
    def requests_per_minute(self) -> int:
        """Backward-compatible property returning configured window requests limit."""
        return self.policy.requests_per_window

    @property
    def burst_limit(self) -> int:
        """Backward-compatible property returning configured burst limit."""
        return self.policy.burst_limit

    def _normalize_key(self, key: Any) -> str:
        """Normalize key representation from str or tuple."""
        if isinstance(key, tuple):
            return "::".join(str(part).strip() for part in key)
        return str(key).strip()

    def is_allowed(self, key: Any, timestamp: float | None = None) -> bool:
        """Check if request for key is allowed under rate limits and record timestamp."""
        norm_key = self._normalize_key(key)
        now = time.time() if timestamp is None else timestamp
        window_start = now - self.policy.window_seconds
        burst_start = now - self.policy.burst_window_seconds

        if norm_key not in self._history:
            self._history[norm_key] = deque()

        timestamps = self._history[norm_key]

        # Evict timestamps older than sliding window
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()

        # Check total window capacity
        if len(timestamps) >= self.policy.requests_per_window:
            return False

        # Check burst window capacity
        recent_burst_count = sum(1 for t in timestamps if t >= burst_start)
        if recent_burst_count >= self.policy.burst_limit:
            return False

        timestamps.append(now)
        return True

    def check_rate_limit(self, key: Any, timestamp: float | None = None) -> None:
        """Evaluate rate limit for key, raising RateLimitExceededError on denial."""
        norm_key = self._normalize_key(key)
        if not self.is_allowed(norm_key, timestamp):
            raise RateLimitExceededError(
                limit_per_minute=self.policy.requests_per_window,
                retry_after_seconds=self.policy.window_seconds,
            )

    def reset(self, key: Any | None = None) -> None:
        """Reset history for a specific key or all keys."""
        if key is not None:
            norm_key = self._normalize_key(key)
            self._history.pop(norm_key, None)
        else:
            self._history.clear()
