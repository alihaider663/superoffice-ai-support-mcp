"""End-to-end wire integration tests connecting Gateway with backend FastMCP servers."""

import json
import time
from typing import Any

import httpx
import jwt
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import HttpUrl
from starlette.testclient import TestClient

from diag_mcp.server import create_diagnostics_mcp_server
from infra_mcp.server import create_infrastructure_mcp_server
from kb_mcp.server import create_knowledge_mcp_server
from platform_config.gateway import GatewaySettings
from platform_gateway.adapters.http_dispatcher import HttpToolDispatcher
from platform_gateway.contracts.dispatch import (
    GatewayDispatchRequest,
    GatewayDispatchResponse,
)
from platform_gateway.contracts.interfaces import StreamableHttpDispatcher
from platform_gateway.contracts.routing import TargetServer, ToolRouteDefinition
from platform_gateway.registry import GatewayBackendRegistry, create_default_routing_table
from platform_gateway.server.app import create_gateway_app
from platform_gateway.services.gateway_service import GatewayApplicationService
from platform_observability.audit import JsonStreamAuditSink
from platform_security.jwt import JwtAuthenticator
from platform_security.rate_limiting import SlidingWindowRateLimiter
from platform_security.rbac import YamlPolicyEngine
from platform_security.sanitization import RecursiveOutputSanitizer
from so_mcp.contracts.dtos import TicketDetailDomainDTO
from so_mcp.server import create_app as create_so_app
from so_mcp.server import create_superoffice_mcp_server
from tests.fakes.fake_diagnostic_repository import FakeDiagnosticRepository
from tests.fakes.fake_superoffice_client import FakeSuperOfficeClient

TEST_JWT_SECRET = "super-secret-e2e-signing-key-32bytes-long"


def _make_jwt(sub: str = "USR-E2E-01", role: str = "L1", prod_write: bool = False) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "role": role,
        "production_write": prod_write,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


class FastMCPDirectDispatcher(StreamableHttpDispatcher):
    """Direct dispatcher invoking registered FastMCP server instances in-process."""

    def __init__(
        self,
        backend_registry: GatewayBackendRegistry,
        servers: dict[TargetServer, Any],
    ) -> None:
        self._backend_registry = backend_registry
        self._servers = servers

    async def dispatch(
        self,
        route: ToolRouteDefinition,
        request: GatewayDispatchRequest,
    ) -> GatewayDispatchResponse:
        server = self._servers.get(route.target_server)
        if server is None:
            return GatewayDispatchResponse(
                tool_name=request.tool_name,
                success=False,
                result=None,
                correlation_id=request.correlation_id,
            )

        tool_fn = server._tool_manager._tools.get(request.tool_name)
        if tool_fn is not None:
            try:
                fn = tool_fn.fn
                result = await fn(**request.arguments)
                return GatewayDispatchResponse(
                    tool_name=request.tool_name,
                    success=True,
                    result=result,
                    error=None,
                    correlation_id=request.correlation_id,
                )
            except Exception:
                return GatewayDispatchResponse(
                    tool_name=request.tool_name,
                    success=False,
                    result=None,
                    error=None,
                    correlation_id=request.correlation_id,
                )

        return GatewayDispatchResponse(
            tool_name=request.tool_name,
            success=False,
            result=None,
            correlation_id=request.correlation_id,
        )


def e2e_gateway_client() -> TestClient:
    """Instantiate a Gateway test client wired to in-process FastMCP server instances."""
    fake_so_client = FakeSuperOfficeClient()
    fake_so_client.seed_ticket(
        TicketDetailDomainDTO(
            ticket_id=4567,
            title="Ticket #4567",
            status="Open",
            category="General",
            priority="Low",
        )
    )
    so_server = create_superoffice_mcp_server(client=fake_so_client)
    diag_server = create_diagnostics_mcp_server(repository=FakeDiagnosticRepository())
    kb_server = create_knowledge_mcp_server()
    infra_server = create_infrastructure_mcp_server()

    servers = {
        TargetServer.SUPEROFFICE: so_server,
        TargetServer.DIAGNOSTICS: diag_server,
        TargetServer.KNOWLEDGE: kb_server,
        TargetServer.INFRASTRUCTURE: infra_server,
    }

    settings = GatewaySettings(
        superoffice_mcp_url=HttpUrl("http://so-backend/mcp"),
        diagnostics_mcp_url=HttpUrl("http://diag-backend/mcp"),
        knowledge_mcp_url=HttpUrl("http://kb-backend/mcp"),
        infrastructure_mcp_url=HttpUrl("http://infra-backend/mcp"),
    )
    backend_registry = GatewayBackendRegistry(settings)
    dispatcher = FastMCPDirectDispatcher(
        backend_registry=backend_registry,
        servers=servers,
    )

    routing_table = create_default_routing_table()
    authenticator = JwtAuthenticator(secret_or_key=TEST_JWT_SECRET, algorithms=["HS256"])
    authorizer = YamlPolicyEngine()
    rate_limiter = SlidingWindowRateLimiter()
    sanitizer = RecursiveOutputSanitizer()
    audit_sink = JsonStreamAuditSink()

    service = GatewayApplicationService(
        routing_table=routing_table,
        dispatcher=dispatcher,
        authenticator=authenticator,
        authorizer=authorizer,
        rate_limiter=rate_limiter,
        sanitizer=sanitizer,
        audit_sink=audit_sink,
    )

    app = create_gateway_app(service=service, routing_table=routing_table)
    return TestClient(app)


def test_e2e_gateway_health_check() -> None:
    """Gateway health check returns 200 OK."""
    with e2e_gateway_client() as client:
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["service"] == "platform-gateway"


def _parse_mcp_response(res: httpx.Response) -> Any:
    """Extract JSON data structure from MCP response (handling both SSE and direct JSON)."""
    text = res.text.strip()
    if text.startswith("event:") or "data:" in text:
        for line in text.splitlines():
            line_s = line.strip()
            if line_s.startswith("data:"):
                return json.loads(line_s[5:].strip())
    try:
        return res.json()
    except Exception:
        return {"raw_text": text}


def test_e2e_mcp_initialize_negotiation() -> None:
    """Client initiates official initialize method to Gateway."""
    with e2e_gateway_client() as client:
        payload = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "claude-desktop-e2e", "version": "1.0.0"},
            },
            "id": "req-init-01",
        }
        res = client.post("/mcp", json=payload)
        assert res.status_code == 200
        data = _parse_mcp_response(res)
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "req-init-01"
        assert data["result"]["protocolVersion"] == "2024-11-05"
        assert data["result"]["serverInfo"]["name"] == "superoffice-ai-gateway"


def test_e2e_mcp_tools_list_discovery() -> None:
    """Client lists tools discovering exactly the 17 platform tool definitions."""
    with e2e_gateway_client() as client:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": "req-tools-list-01",
        }
        res = client.post("/mcp", json=payload)
        assert res.status_code == 200
        data = _parse_mcp_response(res)
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "req-tools-list-01"
        tools = data["result"]["tools"]
        assert len(tools) == 18
        assert any(t["name"] == "investigate_incident" for t in tools)


def test_e2e_superoffice_tool_dispatch_wire_flow() -> None:
    """Client calls tools/call; Gateway authenticates and dispatches to FastMCP backend."""
    with e2e_gateway_client() as client:
        token = _make_jwt(sub="USR-SUPPORT-L1", role="L1")
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "get_ticket",
                "arguments": {"ticket_id": 4567},
            },
            "id": "call-so-01",
        }
        res = client.post("/mcp", json=payload, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = _parse_mcp_response(res)
        assert data["id"] == "call-so-01"
        assert data["result"]["isError"] is False
        assert len(data["result"]["content"]) > 0


def test_e2e_rbac_denial_before_downstream_dispatch() -> None:
    """L1 caller invoking L3 tool find_deadlocks is denied by Gateway before hitting backend."""
    with e2e_gateway_client() as client:
        token = _make_jwt(sub="USR-SUPPORT-L1", role="L1")
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "find_deadlocks",
                "arguments": {},
            },
            "id": "call-diag-unauth",
        }
        res = client.post("/mcp", json=payload, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = _parse_mcp_response(res)
        assert data["result"]["isError"] is True
        assert "[INSUFFICIENT_ROLE]" in data["result"]["content"][0]["text"]


def test_e2e_knowledge_search_wire_flow() -> None:
    """Client calls tools/call for search_knowledge; Gateway dispatches to Knowledge server."""
    with e2e_gateway_client() as client:
        token = _make_jwt(sub="USR-SUPPORT-L1", role="L1")
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "search_knowledge",
                "arguments": {"query_text": "OAuth 2.0 configuration"},
            },
            "id": "call-kb-01",
        }
        res = client.post("/mcp", json=payload, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = _parse_mcp_response(res)
        assert data["result"]["isError"] is False


def test_e2e_diagnostics_deadlocks_l3_wire_flow() -> None:
    """L3 client calls tools/call for find_deadlocks; Gateway dispatches to Diagnostics server."""
    with e2e_gateway_client() as client:
        token = _make_jwt(sub="USR-DBA-L3", role="L3")
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "find_deadlocks",
                "arguments": {"hours_back": 12, "limit": 5},
            },
            "id": "call-diag-01",
        }
        res = client.post("/mcp", json=payload, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = _parse_mcp_response(res)
        assert data["result"]["isError"] is False


@pytest.mark.asyncio
async def test_full_sdk_wire_transport_e2e() -> None:
    """Verify full end-to-end wire transport using official MCP SDK Client."""
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
    so_client = httpx.AsyncClient(transport=so_transport, base_url="http://testserver")

    settings = GatewaySettings(
        superoffice_mcp_url=HttpUrl("http://testserver"),
        diagnostics_mcp_url=HttpUrl("http://testserver"),
        knowledge_mcp_url=HttpUrl("http://testserver"),
        infrastructure_mcp_url=HttpUrl("http://testserver"),
    )
    backend_reg = GatewayBackendRegistry(settings=settings)
    dispatcher = HttpToolDispatcher(backend_registry=backend_reg, http_client=so_client)

    token = _make_jwt(sub="USR-OFFICIAL-MCP-01", role="L1")
    authenticator = JwtAuthenticator(secret_or_key=TEST_JWT_SECRET, algorithms=["HS256"])
    service = GatewayApplicationService(
        routing_table=create_default_routing_table(),
        dispatcher=dispatcher,
        authenticator=authenticator,
        authorizer=YamlPolicyEngine(),
        sanitizer=RecursiveOutputSanitizer(),
    )
    gw_app = create_gateway_app(service=service)

    async with (
        so_app.router.lifespan_context(so_app),
        gw_app.router.lifespan_context(gw_app),
    ):
        gw_transport = httpx.ASGITransport(app=gw_app)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
        }
        async with (
            httpx.AsyncClient(
                transport=gw_transport,
                base_url="http://testserver",
                headers=headers,
                follow_redirects=True,
            ) as gw_client,
            streamable_http_client("http://testserver/mcp", http_client=gw_client) as (
                read_stream,
                write_stream,
                _,
            ),
            ClientSession(read_stream, write_stream) as session,
        ):
            init_res = await session.initialize()
            assert init_res.serverInfo.name == "superoffice-ai-gateway"

            tool_res = await session.call_tool(
                "get_ticket",
                arguments={"ticket_id": 999},
            )
            assert tool_res.isError is False
            assert len(tool_res.content) > 0
