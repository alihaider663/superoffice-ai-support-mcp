"""Resilient asynchronous HTTP client engine wrapping HTTPX with retry and timeout policies."""

import asyncio
import random
import time
from typing import Any, Protocol, runtime_checkable

import httpx

from platform_core.errors import IntegrationError, PlatformError, TimeoutError
from platform_http.models import (
    ConnectionPoolPolicy,
    HttpMethod,
    HttpRequest,
    HttpResponse,
    RetryPolicy,
    TimeoutPolicy,
)


@runtime_checkable
class HttpClient(Protocol):
    """Protocol for asynchronous HTTP clients."""

    async def send(self, request: HttpRequest) -> HttpResponse:
        """Asynchronously dispatch an HTTP request and return the normalized response."""
        ...

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: TimeoutPolicy | None = None,
        retry: RetryPolicy | None = None,
    ) -> HttpResponse:
        """Convenience GET request."""
        ...

    async def post(
        self,
        url: str,
        *,
        body: Any | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: TimeoutPolicy | None = None,
        retry: RetryPolicy | None = None,
        retry_safe: bool | None = None,
    ) -> HttpResponse:
        """Convenience POST request."""
        ...


class ResilientHttpClient(HttpClient):
    """Resilient HTTP client with configurable connection pools, retries, and timeouts."""

    def __init__(
        self,
        default_timeout: TimeoutPolicy | None = None,
        default_retry: RetryPolicy | None = None,
        pool_policy: ConnectionPoolPolicy | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        limits: httpx.Limits | None = None,
    ) -> None:
        self.default_timeout = default_timeout or TimeoutPolicy()
        self.default_retry = default_retry or RetryPolicy()
        self.pool_policy = pool_policy or ConnectionPoolPolicy()
        self._external_client = client
        self._limits = limits or httpx.Limits(
            max_connections=self.pool_policy.max_connections,
            max_keepalive_connections=self.pool_policy.max_keepalive_connections,
            keepalive_expiry=self.pool_policy.keepalive_expiry_seconds,
        )
        self._internal_client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or initialize active AsyncClient instance."""
        if self._external_client is not None:
            return self._external_client
        if self._internal_client is None or self._internal_client.is_closed:
            self._internal_client = httpx.AsyncClient(limits=self._limits)
        return self._internal_client

    async def close(self) -> None:
        """Close internal HTTP client pool if managed."""
        if self._internal_client is not None and not self._internal_client.is_closed:
            await self._internal_client.aclose()
            self._internal_client = None

    @classmethod
    def _calculate_backoff(cls, attempt: int, policy: RetryPolicy) -> float:
        """Calculate exponential backoff delay with optional jitter."""
        delay = float(
            min(
                policy.initial_backoff_seconds * (2 ** (attempt - 1)),
                policy.max_backoff_seconds,
            )
        )
        if policy.jitter:
            delay = delay * (0.5 + random.random() * 0.5)
        return float(delay)

    @classmethod
    def _format_payload(cls, body: Any) -> tuple[Any, Any]:
        """Separate JSON and content payloads."""
        if body is None:
            return None, None
        if isinstance(body, (dict, list)):
            return body, None
        if isinstance(body, (str, bytes)):
            return None, body
        return body, None

    async def _execute_attempt(
        self,
        client: httpx.AsyncClient,
        request: HttpRequest,
        timeout: httpx.Timeout,
    ) -> httpx.Response:
        """Dispatch a single HTTP network request."""
        json_payload, content_payload = self._format_payload(request.body)
        method_str = (
            request.method.value if isinstance(request.method, HttpMethod) else str(request.method)
        )
        return await client.request(
            method=method_str,
            url=request.url,
            params=request.params or None,
            headers=request.headers or None,
            json=json_payload,
            content=content_payload,
            timeout=timeout,
        )

    async def send(self, request: HttpRequest) -> HttpResponse:
        """Dispatch HTTP request with idempotency-aware retries and timeout enforcement."""
        client = await self._get_client()
        httpx_timeout = httpx.Timeout(
            connect=request.timeout.connect_timeout_seconds,
            read=request.timeout.read_timeout_seconds,
            write=request.timeout.write_timeout_seconds,
            pool=request.timeout.connect_timeout_seconds,
        )
        total_deadline = time.monotonic() + request.timeout.total_timeout_seconds
        last_error: Exception | None = None

        # Determine if this request is safe to retry across attempts
        is_retryable = request.is_retry_safe()
        max_attempts = request.retry.max_attempts if is_retryable else 1

        for attempt in range(1, max_attempts + 1):
            if time.monotonic() >= total_deadline:
                raise TimeoutError(
                    operation_name=f"HTTP {request.method} {request.url}",
                    timeout_seconds=request.timeout.total_timeout_seconds,
                )

            start_time = time.monotonic()
            try:
                raw_response = await self._execute_attempt(client, request, httpx_timeout)
                elapsed_ms = (time.monotonic() - start_time) * 1000.0

                # Check retryable status codes (only if request is safe to retry)
                if (
                    is_retryable
                    and raw_response.status_code in request.retry.retryable_status_codes
                    and attempt < max_attempts
                ):
                    backoff = self._calculate_backoff(attempt, request.retry)
                    if time.monotonic() + backoff >= total_deadline:
                        raise TimeoutError(
                            operation_name=f"HTTP {request.method} {request.url}",
                            timeout_seconds=request.timeout.total_timeout_seconds,
                        )
                    await asyncio.sleep(backoff)
                    continue

                return HttpResponse(
                    status_code=raw_response.status_code,
                    headers=dict(raw_response.headers),
                    body_text=raw_response.text,
                    is_success=raw_response.is_success,
                    elapsed_ms=elapsed_ms,
                )

            except httpx.TimeoutException as e:
                last_error = e
                if is_retryable and attempt < max_attempts:
                    backoff = self._calculate_backoff(attempt, request.retry)
                    if time.monotonic() + backoff < total_deadline:
                        await asyncio.sleep(backoff)
                        continue
                raise TimeoutError(
                    operation_name=f"HTTP {request.method} {request.url}",
                    timeout_seconds=request.timeout.total_timeout_seconds,
                ) from e

            except httpx.NetworkError as e:
                last_error = e
                if is_retryable and attempt < max_attempts:
                    backoff = self._calculate_backoff(attempt, request.retry)
                    if time.monotonic() + backoff < total_deadline:
                        await asyncio.sleep(backoff)
                        continue
                raise IntegrationError(
                    f"HTTP network failure contacting '{request.url}': {e}",
                    system_name="HTTP",
                    details={"url": request.url, "attempt": attempt, "error": str(e)},
                ) from e

            except Exception as e:
                if isinstance(e, PlatformError):
                    raise
                raise IntegrationError(
                    f"Unexpected HTTP client failure contacting '{request.url}': {e}",
                    system_name="HTTP",
                    details={"url": request.url, "error": str(e)},
                ) from e

        raise IntegrationError(
            f"HTTP request to '{request.url}' exhausted all {max_attempts} attempts.",
            system_name="HTTP",
            details={"url": request.url, "last_error": str(last_error)},
        )

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: TimeoutPolicy | None = None,
        retry: RetryPolicy | None = None,
    ) -> HttpResponse:
        """Convenience GET dispatch."""
        request = HttpRequest(
            url=url,
            method=HttpMethod.GET,
            params=params or {},
            headers=headers or {},
            timeout=timeout or self.default_timeout,
            retry=retry or self.default_retry,
        )
        return await self.send(request)

    async def post(
        self,
        url: str,
        *,
        body: Any | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: TimeoutPolicy | None = None,
        retry: RetryPolicy | None = None,
        retry_safe: bool | None = None,
    ) -> HttpResponse:
        """Convenience POST dispatch."""
        request = HttpRequest(
            url=url,
            method=HttpMethod.POST,
            body=body,
            params=params or {},
            headers=headers or {},
            timeout=timeout or self.default_timeout,
            retry=retry or self.default_retry,
            retry_safe=retry_safe,
        )
        return await self.send(request)
