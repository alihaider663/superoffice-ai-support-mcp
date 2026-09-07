"""Unit tests for ResilientHttpClient, ConnectionPoolPolicy, and idempotency-aware retries."""

import json

import httpx
import pytest
import respx

from platform_core.errors import IntegrationError, TimeoutError
from platform_http.client import HttpClient, ResilientHttpClient
from platform_http.models import (
    ConnectionPoolPolicy,
    HttpMethod,
    HttpRequest,
    RetryPolicy,
    TimeoutPolicy,
)


@pytest.fixture
def fast_retry_policy() -> RetryPolicy:
    return RetryPolicy(
        max_attempts=3,
        initial_backoff_seconds=0.01,
        max_backoff_seconds=0.05,
        jitter=False,
        retryable_status_codes=(500, 502, 503, 504),
    )


@pytest.fixture
def fast_timeout_policy() -> TimeoutPolicy:
    return TimeoutPolicy(
        connect_timeout_seconds=1.0,
        read_timeout_seconds=2.0,
        write_timeout_seconds=1.0,
        total_timeout_seconds=5.0,
    )


@pytest.fixture
def pool_policy() -> ConnectionPoolPolicy:
    return ConnectionPoolPolicy(
        max_connections=25,
        max_keepalive_connections=10,
        keepalive_expiry_seconds=15.0,
    )


@pytest.fixture
def resilient_client(
    fast_timeout_policy: TimeoutPolicy,
    fast_retry_policy: RetryPolicy,
    pool_policy: ConnectionPoolPolicy,
) -> ResilientHttpClient:
    return ResilientHttpClient(
        default_timeout=fast_timeout_policy,
        default_retry=fast_retry_policy,
        pool_policy=pool_policy,
    )


def test_client_implements_protocol(resilient_client: ResilientHttpClient) -> None:
    assert isinstance(resilient_client, HttpClient)


@pytest.mark.asyncio
@respx.mock
async def test_successful_get_request(resilient_client: ResilientHttpClient) -> None:
    respx.get("https://api.example.com/tickets/101").respond(
        status_code=200,
        json={"ticket_id": 101, "status": "OPEN"},
        headers={"Content-Type": "application/json"},
    )

    response = await resilient_client.get("https://api.example.com/tickets/101")
    assert response.status_code == 200
    assert response.is_success is True
    data = json.loads(response.body_text)
    assert data["ticket_id"] == 101
    assert data["status"] == "OPEN"


@pytest.mark.asyncio
@respx.mock
async def test_successful_post_request(resilient_client: ResilientHttpClient) -> None:
    respx.post("https://api.example.com/search").respond(
        status_code=201,
        json={"count": 5},
    )

    response = await resilient_client.post(
        "https://api.example.com/search",
        body={"query": "slow query"},
    )
    assert response.status_code == 201
    assert response.is_success is True
    data = json.loads(response.body_text)
    assert data["count"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_non_retryable_client_error_fails_immediately(
    resilient_client: ResilientHttpClient,
) -> None:
    route = respx.get("https://api.example.com/tickets/999").respond(
        status_code=404,
        json={"error": "Not Found"},
    )

    response = await resilient_client.get("https://api.example.com/tickets/999")
    assert response.status_code == 404
    assert response.is_success is False
    assert route.call_count == 1  # No retries on 404


@pytest.mark.asyncio
@respx.mock
async def test_retryable_get_request_retries_and_succeeds(
    resilient_client: ResilientHttpClient,
) -> None:
    route = respx.get("https://api.example.com/health")
    route.side_effect = [
        httpx.Response(503, text="Service Unavailable"),
        httpx.Response(200, text="OK"),
    ]

    response = await resilient_client.get("https://api.example.com/health")
    assert response.status_code == 200
    assert response.body_text == "OK"
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_non_idempotent_post_does_not_retry_on_server_error(
    resilient_client: ResilientHttpClient,
    fast_timeout_policy: TimeoutPolicy,
    fast_retry_policy: RetryPolicy,
) -> None:
    route = respx.post("https://api.example.com/tickets/101/comments").respond(
        status_code=500,
        text="Internal Server Error",
    )

    request = HttpRequest(
        url="https://api.example.com/tickets/101/comments",
        method=HttpMethod.POST,
        body={"comment": "Investigating deadlock"},
        timeout=fast_timeout_policy,
        retry=fast_retry_policy,
        retry_safe=False,  # Explicit side-effect write
    )

    response = await resilient_client.send(request)
    assert response.status_code == 500
    assert route.call_count == 1  # Exactly 1 attempt, zero retries


@pytest.mark.asyncio
@respx.mock
async def test_explicit_idempotent_post_retries(
    resilient_client: ResilientHttpClient,
    fast_timeout_policy: TimeoutPolicy,
    fast_retry_policy: RetryPolicy,
) -> None:
    route = respx.post("https://api.example.com/search/idempotent")
    route.side_effect = [
        httpx.Response(502, text="Bad Gateway"),
        httpx.Response(200, json={"items": []}),
    ]

    request = HttpRequest(
        url="https://api.example.com/search/idempotent",
        method=HttpMethod.POST,
        body={"query": "term"},
        timeout=fast_timeout_policy,
        retry=fast_retry_policy,
        retry_safe=True,  # Idempotent search POST
    )

    response = await resilient_client.send(request)
    assert response.status_code == 200
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_socket_timeout_raises_timeout_error(
    resilient_client: ResilientHttpClient,
) -> None:
    route = respx.get("https://api.example.com/slow")
    route.side_effect = httpx.ConnectTimeout("Connection timed out")

    with pytest.raises(TimeoutError) as exc_info:
        await resilient_client.get("https://api.example.com/slow")

    assert "timed out" in str(exc_info.value).lower()
    assert route.call_count == 3  # GET is retryable up to max_attempts


@pytest.mark.asyncio
@respx.mock
async def test_network_connection_error_raises_integration_error(
    resilient_client: ResilientHttpClient,
) -> None:
    route = respx.get("https://api.example.com/down")
    route.side_effect = httpx.ConnectError("Connection refused")

    with pytest.raises(IntegrationError) as exc_info:
        await resilient_client.get("https://api.example.com/down")

    assert "network failure" in str(exc_info.value).lower()
    assert route.call_count == 3
