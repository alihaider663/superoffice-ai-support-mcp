"""Unit tests for HttpToolDispatcher header injection, payload parsing, and error mapping."""

from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from mcp.types import CallToolResult, TextContent
from pydantic import HttpUrl

import platform_gateway.adapters.http_dispatcher as disp_mod
from platform_config.gateway import GatewaySettings
from platform_core.models import PrincipalIdentity
from platform_gateway.adapters.http_dispatcher import HttpToolDispatcher
from platform_gateway.constants import (
    INTERNAL_HEADER_ATTACHMENT_ACCESS,
    INTERNAL_HEADER_CORRELATION_ID,
    INTERNAL_HEADER_PRODUCTION_WRITE,
    INTERNAL_HEADER_USER_ID,
    INTERNAL_HEADER_USER_ROLE,
)
from platform_gateway.contracts.dispatch import GatewayDispatchRequest
from platform_gateway.contracts.routing import TargetServer, ToolRouteDefinition
from platform_gateway.registry import GatewayBackendRegistry
from platform_security.models import SecurityContext
from so_mcp.contracts.dtos import TicketDetailDomainDTO
from so_mcp.server import create_app as create_so_app
from tests.fakes.fake_superoffice_client import FakeSuperOfficeClient


@pytest.fixture
def mock_registry() -> GatewayBackendRegistry:
    """Create test gateway backend registry."""
    settings = GatewaySettings(
        superoffice_mcp_url=HttpUrl("http://so-server:8001"),
        diagnostics_mcp_url=HttpUrl("http://diag-server:8002"),
        knowledge_mcp_url=HttpUrl("http://kb-server:8003"),
        infrastructure_mcp_url=HttpUrl("http://infra-server:8004"),
    )
    return GatewayBackendRegistry(settings)


@pytest.fixture
def sample_security_context() -> SecurityContext:
    """Create test verified security context."""
    return SecurityContext(
        principal=PrincipalIdentity(
            user_id="USR-SUPPORT-01",
            role="L2",
        ),
        token_id="tok_test_12345",
        is_authenticated=True,
        attributes={
            "production_write": True,
            "attachment_access": False,
        },
    )


def test_trusted_headers_construction(
    mock_registry: GatewayBackendRegistry,
    sample_security_context: SecurityContext,
) -> None:
    """HttpToolDispatcher constructs trusted internal headers derived from SecurityContext."""
    dispatcher = HttpToolDispatcher(backend_registry=mock_registry)
    req = GatewayDispatchRequest(
        tool_name="get_ticket",
        arguments={"ticket_id": 999},
        security_context=sample_security_context,
        correlation_id="CORR-TR-8888",
    )

    headers = dispatcher._build_trusted_headers(req)
    assert headers[INTERNAL_HEADER_USER_ID] == "USR-SUPPORT-01"
    assert headers[INTERNAL_HEADER_USER_ROLE] == "L2"
    assert headers[INTERNAL_HEADER_PRODUCTION_WRITE] == "true"
    assert headers[INTERNAL_HEADER_ATTACHMENT_ACCESS] == "false"
    assert headers[INTERNAL_HEADER_CORRELATION_ID] == "CORR-TR-8888"
    assert headers["Accept"] == "application/json, text/event-stream"


@pytest.mark.asyncio
async def test_dispatch_e2e_with_fastmcp_backend(
    sample_security_context: SecurityContext,
) -> None:
    """HttpToolDispatcher executes downstream tool on live FastMCP backend via ASGI transport."""
    fake_so_client = FakeSuperOfficeClient()
    fake_so_client.seed_ticket(
        TicketDetailDomainDTO(
            ticket_id=999,
            title="Ticket #999",
            status="Open",
            category="General",
            priority="Low",
        )
    )
    so_app = create_so_app(client=fake_so_client)
    so_transport = httpx.ASGITransport(app=so_app)
    so_client = httpx.AsyncClient(transport=so_transport, base_url="http://so-server:8001")

    settings = GatewaySettings(
        superoffice_mcp_url=HttpUrl("http://so-server:8001"),
        diagnostics_mcp_url=HttpUrl("http://diag-server:8002"),
        knowledge_mcp_url=HttpUrl("http://kb-server:8003"),
        infrastructure_mcp_url=HttpUrl("http://infra-server:8004"),
    )
    backend_registry = GatewayBackendRegistry(settings)
    dispatcher = HttpToolDispatcher(
        backend_registry=backend_registry,
        http_client=so_client,
    )

    route = ToolRouteDefinition(
        tool_name="get_ticket",
        target_server=TargetServer.SUPEROFFICE,
        endpoint_path="/mcp",
    )
    req = GatewayDispatchRequest(
        tool_name="get_ticket",
        arguments={"ticket_id": 999},
        security_context=sample_security_context,
        correlation_id="CORR-TR-8888",
    )

    async with so_app.router.lifespan_context(so_app):
        res = await dispatcher.dispatch(route=route, request=req)

    assert res.success is True
    assert res.tool_name == "get_ticket"
    assert res.result is not None
    assert isinstance(res.result, dict)
    assert res.result.get("ticket_id") == 999


@pytest.mark.asyncio
async def test_dispatch_handles_timeout_gracefully(
    mock_registry: GatewayBackendRegistry,
    sample_security_context: SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HttpToolDispatcher maps downstream timeout exceptions into SanitizedErrorPayload."""
    dispatcher = HttpToolDispatcher(backend_registry=mock_registry)
    route = ToolRouteDefinition(
        tool_name="search_knowledge",
        target_server=TargetServer.KNOWLEDGE,
    )
    req = GatewayDispatchRequest(
        tool_name="search_knowledge",
        arguments={"query": "test"},
        security_context=sample_security_context,
        correlation_id="CORR-TO-TEST",
    )

    @asynccontextmanager
    async def mock_streamable_client(*args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        raise httpx.ReadTimeout("Read timed out")
        yield

    monkeypatch.setattr(disp_mod, "streamable_http_client", mock_streamable_client)

    res = await dispatcher.dispatch(route=route, request=req)

    assert res.success is False
    assert res.result is None
    assert res.error is not None
    assert res.error.error == "GATEWAY_DOWNSTREAM_TIMEOUT"
    assert "timed out" in res.error.message


@pytest.mark.asyncio
async def test_dispatch_handles_unreachable_server(
    mock_registry: GatewayBackendRegistry,
    sample_security_context: SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HttpToolDispatcher maps connection failure into GATEWAY_DOWNSTREAM_UNAVAILABLE error."""
    dispatcher = HttpToolDispatcher(backend_registry=mock_registry)
    route = ToolRouteDefinition(
        tool_name="get_database_health",
        target_server=TargetServer.DIAGNOSTICS,
    )
    req = GatewayDispatchRequest(
        tool_name="get_database_health",
        arguments={},
        security_context=sample_security_context,
        correlation_id="CORR-CONN-FAIL",
    )

    @asynccontextmanager
    async def mock_streamable_client(*args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        raise httpx.ConnectError("Connection refused")
        yield

    monkeypatch.setattr(disp_mod, "streamable_http_client", mock_streamable_client)

    res = await dispatcher.dispatch(route=route, request=req)

    assert res.success is False
    assert res.result is None
    assert res.error is not None
    assert res.error.error == "GATEWAY_DOWNSTREAM_UNAVAILABLE"
    assert res.error.message == "Downstream service is currently unavailable."
    # Leakage audit: ensure internal runtime/framework words are never exposed
    for forbidden in ("TaskGroup", "sub-exception", "ExceptionGroup", "ConnectError", "traceback"):
        assert forbidden not in res.error.message


@pytest.mark.asyncio
async def test_dispatch_maps_tool_is_error_flag(
    mock_registry: GatewayBackendRegistry,
    sample_security_context: SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HttpToolDispatcher maps isError=True downstream response into failed dispatch."""
    dispatcher = HttpToolDispatcher(backend_registry=mock_registry)
    route = ToolRouteDefinition(
        tool_name="get_database_health",
        target_server=TargetServer.DIAGNOSTICS,
    )
    req = GatewayDispatchRequest(
        tool_name="get_database_health",
        arguments={},
        security_context=sample_security_context,
        correlation_id="CORR-ISERROR-TEST",
    )

    class MockSession:
        async def initialize(self) -> None:
            pass

        async def call_tool(self, *args: Any, **kwargs: Any) -> CallToolResult:  # noqa: ARG002
            return CallToolResult(
                content=[TextContent(type="text", text="Database unreachable")],
                isError=True,
            )

    @asynccontextmanager
    async def mock_streamable_client(*args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        yield (None, None, None)

    class MockClientSessionCtx:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> MockSession:
            return MockSession()

        async def __aexit__(self, *args: Any) -> None:
            pass

    monkeypatch.setattr(disp_mod, "streamable_http_client", mock_streamable_client)
    monkeypatch.setattr(disp_mod, "ClientSession", MockClientSessionCtx)

    res = await dispatcher.dispatch(route=route, request=req)
    assert res.success is False
    assert res.error is not None
    assert res.error.error == "DOWNSTREAM_TOOL_ERROR"
    assert "Database unreachable" in res.error.message
