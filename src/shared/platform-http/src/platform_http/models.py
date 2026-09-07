"""HTTP request/response models and resilience policy definitions."""

from enum import StrEnum
from typing import Any

from pydantic import Field, PositiveFloat, PositiveInt

from platform_core.models import PlatformBaseModel


class HttpMethod(StrEnum):
    """Supported HTTP request methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"


class TimeoutPolicy(PlatformBaseModel):
    """Timeout configuration for network socket operations."""

    connect_timeout_seconds: PositiveFloat = Field(
        default=5.0,
        description="Socket connection establishment limit",
    )
    read_timeout_seconds: PositiveFloat = Field(
        default=25.0,
        description="Socket read limit per frame",
    )
    write_timeout_seconds: PositiveFloat = Field(
        default=10.0,
        description="Socket write limit",
    )
    total_timeout_seconds: PositiveFloat = Field(
        default=30.0,
        description="Total end-to-end request budget",
    )


class ConnectionPoolPolicy(PlatformBaseModel):
    """Connection pool and keep-alive configuration for HTTP transport."""

    max_connections: PositiveInt = Field(
        default=50,
        description="Maximum total simultaneous connections in pool",
    )
    max_keepalive_connections: PositiveInt = Field(
        default=20,
        description="Maximum idle keepalive connections in pool",
    )
    keepalive_expiry_seconds: PositiveFloat = Field(
        default=30.0,
        description="Keepalive connection idle timeout in seconds",
    )


class RetryPolicy(PlatformBaseModel):
    """Exponential backoff and jitter retry policy configuration."""

    max_attempts: PositiveInt = Field(
        default=3,
        description="Maximum execution attempts",
    )
    initial_backoff_seconds: PositiveFloat = Field(
        default=0.5,
        description="Initial retry backoff delay",
    )
    max_backoff_seconds: PositiveFloat = Field(
        default=5.0,
        description="Upper bound for exponential delay",
    )
    jitter: bool = Field(
        default=True,
        description="Apply randomized jitter to avoid thundering herds",
    )
    retryable_status_codes: tuple[int, ...] = Field(
        default=(500, 502, 503, 504),
        description="HTTP status codes eligible for automatic retry (transient server errors)",
    )


class HttpRequest(PlatformBaseModel):
    """Normalized outbound HTTP request envelope."""

    url: str
    method: HttpMethod = HttpMethod.GET
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    body: Any | None = None
    timeout: TimeoutPolicy = Field(default_factory=TimeoutPolicy)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    retry_safe: bool | None = Field(
        default=None,
        description="Explicit override for whether this request is safe to retry automatically",
    )

    def is_retry_safe(self) -> bool:
        """Evaluate if request is safe to retry based on explicit flag or idempotent method."""
        if self.retry_safe is not None:
            return self.retry_safe
        return self.method in (HttpMethod.GET, HttpMethod.HEAD)


class HttpResponse(PlatformBaseModel):
    """Normalized inbound HTTP response representation."""

    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)
    body_text: str = ""
    is_success: bool = True
    elapsed_ms: float = 0.0
