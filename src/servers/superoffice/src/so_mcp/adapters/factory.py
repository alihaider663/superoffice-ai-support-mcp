"""Factory for instantiating SuperOfficeRestClient with resilient HTTP policies."""

import base64

import httpx

from platform_http.client import ResilientHttpClient
from platform_http.models import ConnectionPoolPolicy, RetryPolicy, TimeoutPolicy
from so_mcp.adapters.rest_client import SuperOfficeRestClient
from so_mcp.contracts.interfaces import SuperOfficeClient
from so_mcp.settings import SuperOfficeServerSettings


def create_superoffice_client(
    settings: SuperOfficeServerSettings,
    *,
    connection_pool: ConnectionPoolPolicy | None = None,
    timeout_policy: TimeoutPolicy | None = None,
    retry_policy: RetryPolicy | None = None,
) -> SuperOfficeClient:
    """Create a configured SuperOfficeClient instance reusing platform HTTP policies."""
    pool = connection_pool or ConnectionPoolPolicy()
    timeout = timeout_policy or TimeoutPolicy(total_timeout_seconds=settings.timeout_seconds)
    retry = retry_policy or RetryPolicy()

    limits = httpx.Limits(
        max_connections=pool.max_connections,
        max_keepalive_connections=pool.max_keepalive_connections,
        keepalive_expiry=pool.keepalive_expiry_seconds,
    )
    httpx_client = httpx.AsyncClient(
        limits=limits,
        verify=not settings.allow_self_signed_cert,
    )
    resilient_http = ResilientHttpClient(
        default_timeout=timeout,
        default_retry=retry,
        pool_policy=pool,
        client=httpx_client,
    )

    credentials = f"{settings.username}:{settings.password.get_secret_value()}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

    return SuperOfficeRestClient(
        client=resilient_http,
        base_url=str(settings.api_url),
        auth_header=f"Basic {encoded}",
    )
