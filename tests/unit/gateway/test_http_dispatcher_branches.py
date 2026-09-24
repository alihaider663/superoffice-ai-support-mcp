"""Additional unit tests for full branch coverage of HttpToolDispatcher and schemas."""

from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from mcp.types import CallToolResult, TextContent
from pydantic import HttpUrl

import platform_gateway.adapters.http_dispatcher as disp_mod
from platform_config.gateway import GatewaySettings
from platform_core.errors import ConfigurationError
from platform_core.models import PrincipalIdentity
from platform_gateway.adapters.http_dispatcher import HttpToolDispatcher
from platform_gateway.contracts.dispatch import GatewayDispatchRequest
from platform_gateway.contracts.routing import TargetServer, ToolRouteDefinition
from platform_gateway.registry import (
    GatewayBackendRegistry,
    create_default_routing_table,
    validate_3way_tool_inventory,
)
from platform_gateway.schemas import get_tool_schema_map
from platform_security.models import SecurityContext
from platform_security.rbac import RbacPolicySchema, ToolPermissionRule


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
        principal=PrincipalIdentity(user_id="USR-SUPPORT-01", role="L2"),
        token_id="tok_test_12345",
        is_authenticated=True,
        attributes={"production_write": True, "attachment_access": False},
    )


def test_schema_map_resolution() -> None:
    """get_tool_schema_map returns dict covering all 26 approved tools."""
    schema_map = get_tool_schema_map()
    assert len(schema_map) == 26
    assert "investigate_incident" in schema_map
    assert "get_ticket" in schema_map
    assert "sync_codebase" in schema_map
    assert "list_extra_tables" in schema_map
    assert "get_ticket_audit_trail" in schema_map
    assert "search_codebase" in schema_map
    assert "get_codebase_file" in schema_map
    assert "get_screen_details" in schema_map


def test_validate_3way_tool_inventory_unrouted_backend() -> None:
    """validate_3way_tool_inventory detects backend tools missing from gateway routing table."""
    table = create_default_routing_table()
    policy = RbacPolicySchema(
        tools={name: ToolPermissionRule(minimum_role="L1") for name in table.routes}
    )
    backend_with_extra = set(table.routes.keys()) | {"unrouted_extra_tool"}
    with pytest.raises(ConfigurationError) as exc_info:
        validate_3way_tool_inventory(table, policy, backend_with_extra)
    assert "Backend tools missing Gateway routes" in str(exc_info.value)


def test_http_dispatcher_result_and_error_extraction() -> None:
    """HttpToolDispatcher extracts structured data and human errors from CallToolResult."""
    settings = GatewaySettings(
        superoffice_mcp_url=HttpUrl("http://so-server:8001"),
        diagnostics_mcp_url=HttpUrl("http://diag-server:8002"),
        knowledge_mcp_url=HttpUrl("http://kb-server:8003"),
        infrastructure_mcp_url=HttpUrl("http://infra-server:8004"),
    )
    dispatcher = HttpToolDispatcher(backend_registry=GatewayBackendRegistry(settings))

    # Structured content extraction
    res_structured = CallToolResult(
        content=[],
        structuredContent={"ticket_id": 100, "status": "Open"},
        isError=False,
    )
    assert dispatcher._extract_tool_result_payload(res_structured) == {
        "ticket_id": 100,
        "status": "Open",
    }

    # JSON text content extraction
    res_json_text = CallToolResult(
        content=[TextContent(type="text", text='{"ticket_id": 200}')],
        isError=False,
    )
    assert dispatcher._extract_tool_result_payload(res_json_text) == {"ticket_id": 200}

    # Raw text content extraction
    res_raw_text = CallToolResult(
        content=[TextContent(type="text", text="plain raw string response")],
        isError=False,
    )
    assert dispatcher._extract_tool_result_payload(res_raw_text) == {
        "raw_text": "plain raw string response"
    }

    # Error message extraction
    res_err = CallToolResult(
        content=[TextContent(type="text", text="Database connection refused")],
        isError=True,
    )
    assert dispatcher._extract_tool_error_message(res_err) == "Database connection refused"


@pytest.mark.asyncio
async def test_dispatch_timeout_handling(
    mock_registry: GatewayBackendRegistry,
    sample_security_context: SecurityContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HttpToolDispatcher maps timeout into GATEWAY_DOWNSTREAM_TIMEOUT SanitizedErrorPayload."""
    dispatcher = HttpToolDispatcher(backend_registry=mock_registry)
    route = ToolRouteDefinition(tool_name="get_ticket", target_server=TargetServer.SUPEROFFICE)
    req = GatewayDispatchRequest(
        tool_name="get_ticket",
        arguments={"ticket_id": 1},
        security_context=sample_security_context,
        correlation_id="CORR-TIMEOUT",
    )

    @asynccontextmanager
    async def mock_streamable_client(*args: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        raise httpx.ReadTimeout("Downstream read timed out")
        yield

    monkeypatch.setattr(disp_mod, "streamable_http_client", mock_streamable_client)

    res = await dispatcher.dispatch(route=route, request=req)
    assert res.success is False
    assert res.error is not None
    assert res.error.error == "GATEWAY_DOWNSTREAM_TIMEOUT"
