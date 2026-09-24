"""Unit tests for Starlette ASGI Gateway endpoints using official MCP SDK models."""

import json
import time
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock

import httpx
import jwt
import pytest
from starlette.testclient import TestClient

from platform_gateway.contracts.dispatch import (
    GatewayDispatchRequest,
    GatewayDispatchResponse,
)
from platform_gateway.contracts.interfaces import StreamableHttpDispatcher
from platform_gateway.contracts.routing import ToolRouteDefinition
from platform_gateway.registry import create_default_routing_table
from platform_gateway.server.app import create_gateway_app
from platform_gateway.services.gateway_service import GatewayApplicationService
from platform_gateway.settings import GatewayAppSettings
from platform_security.jwt import JwtAuthenticator
from platform_security.rbac import YamlPolicyEngine
from platform_security.sanitization import RecursiveOutputSanitizer

TEST_JWT_SECRET = "test-secret-key-gateway-server-99-32bytes-long"


def _make_token(sub: str = "USR-001", role: str = "L1", prod_write: bool = False) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "role": role,
        "production_write": prod_write,
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


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


@pytest.fixture
def test_client() -> Generator[TestClient, None, None]:
    """Create test Starlette client with mocked dispatcher."""
    mock_dispatcher = AsyncMock(spec=StreamableHttpDispatcher)

    async def _mock_dispatch(
        route: ToolRouteDefinition,
        request: GatewayDispatchRequest,
    ) -> GatewayDispatchResponse:
        result_payload: dict[str, Any]
        if request.tool_name == "investigate_incident":
            result_payload = {"source_outcomes": [], "evidence": []}
        else:
            result_payload = {"echo_tool": request.tool_name, "server": route.target_server.value}
        return GatewayDispatchResponse(
            tool_name=request.tool_name,
            success=True,
            result=result_payload,
            error=None,
            correlation_id=request.correlation_id,
        )

    mock_dispatcher.dispatch = AsyncMock(side_effect=_mock_dispatch)
    routing_table = create_default_routing_table()
    authenticator = JwtAuthenticator(secret_or_key=TEST_JWT_SECRET, algorithms=["HS256"])
    authorizer = YamlPolicyEngine()
    sanitizer = RecursiveOutputSanitizer()

    service = GatewayApplicationService(
        routing_table=routing_table,
        dispatcher=mock_dispatcher,
        authenticator=authenticator,
        authorizer=authorizer,
        sanitizer=sanitizer,
    )

    app = create_gateway_app(service=service, routing_table=routing_table)
    with TestClient(app) as client:
        yield client


def test_health_check_endpoint(test_client: TestClient) -> None:
    """GET /health returns 200 OK and healthy service payload."""
    res = test_client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["service"] == "platform-gateway"


def test_mcp_initialize_method(test_client: TestClient) -> None:
    """POST /mcp with initialize method returns official MCP InitializeResult."""
    payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        },
        "id": 1,
    }
    res = test_client.post("/mcp", json=payload)
    assert res.status_code == 200
    data = _parse_mcp_response(res)
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 1
    assert data["result"]["protocolVersion"] == "2024-11-05"
    assert data["result"]["serverInfo"]["name"] == "superoffice-ai-gateway"
    assert "tools" in data["result"]["capabilities"]


def test_mcp_ping_method(test_client: TestClient) -> None:
    """POST /mcp with ping method returns EmptyResult."""
    payload = {
        "jsonrpc": "2.0",
        "method": "ping",
        "id": "ping-1",
    }
    res = test_client.post("/mcp", json=payload)
    assert res.status_code == 200
    data = _parse_mcp_response(res)
    assert data["id"] == "ping-1"
    assert data["result"] == {}


def test_mcp_tools_list_method(test_client: TestClient) -> None:
    """POST /mcp with tools/list returns official ListToolsResult with full Tool schemas."""
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 2,
    }
    res = test_client.post("/mcp", json=payload)
    assert res.status_code == 200
    data = _parse_mcp_response(res)
    tools = data["result"]["tools"]
    assert len(tools) == 26
    assert any(t["name"] == "investigate_incident" for t in tools)
    assert any(t["name"] == "sync_codebase" for t in tools)
    assert any(t["name"] == "list_extra_tables" for t in tools)
    assert any(t["name"] == "get_ticket_audit_trail" for t in tools)
    assert any(t["name"] == "search_codebase" for t in tools)
    assert any(t["name"] == "get_codebase_file" for t in tools)
    assert any(t["name"] == "get_screen_details" for t in tools)
    tool_map = {t["name"]: t for t in tools}

    # Verify Knowledge schema
    assert "search_knowledge" in tool_map
    assert "inputSchema" in tool_map["search_knowledge"]
    assert tool_map["search_knowledge"]["inputSchema"]["type"] == "object"
    assert "query_text" in tool_map["search_knowledge"]["inputSchema"]["properties"]

    # Verify SuperOffice schema
    assert "get_ticket" in tool_map
    assert "ticket_id" in tool_map["get_ticket"]["inputSchema"]["properties"]

    # Verify Diagnostics schema
    assert "find_slow_queries" in tool_map
    assert "min_duration_ms" in tool_map["find_slow_queries"]["inputSchema"]["properties"]


def test_mcp_tools_call_success(test_client: TestClient) -> None:
    """POST /mcp with tools/call for authorized tool returns CallToolResult with TextContent."""
    token = _make_token(role="L1")
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_ticket",
            "arguments": {"ticket_id": 1234},
        },
        "id": 10,
    }
    res = test_client.post("/mcp", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = _parse_mcp_response(res)
    assert data["id"] == 10
    assert data["result"]["isError"] is False
    assert len(data["result"]["content"]) == 1
    assert data["result"]["content"][0]["type"] == "text"


def test_mcp_tools_call_unauthenticated_returns_tool_error(test_client: TestClient) -> None:
    """POST /mcp without Authorization header returns isError=True with AUTHENTICATION_REQUIRED."""
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_ticket",
            "arguments": {"ticket_id": 123},
        },
        "id": 11,
    }
    res = test_client.post("/mcp", json=payload)
    assert res.status_code == 200
    data = _parse_mcp_response(res)
    assert data["result"]["isError"] is True
    assert "[AUTHENTICATION_REQUIRED]" in data["result"]["content"][0]["text"]


def test_mcp_tools_call_unauthorized_returns_role_error(test_client: TestClient) -> None:
    """POST /mcp with L1 token for L2 tool returns isError=True with INSUFFICIENT_ROLE."""
    token = _make_token(role="L1")
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_database_health",
            "arguments": {},
        },
        "id": 12,
    }
    res = test_client.post("/mcp", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = _parse_mcp_response(res)
    assert data["result"]["isError"] is True
    assert "[INSUFFICIENT_ROLE]" in data["result"]["content"][0]["text"]


def test_mcp_unrecognized_method_returns_error(test_client: TestClient) -> None:
    """POST /mcp with unknown method name returns error response."""
    payload = {
        "jsonrpc": "2.0",
        "method": "unknown/method",
        "id": 88,
    }
    res = test_client.post("/mcp", json=payload)
    data = _parse_mcp_response(res)
    assert "error" in data


def test_mcp_invalid_json_returns_400(test_client: TestClient) -> None:
    """POST /mcp with invalid JSON body returns PARSE_ERROR (-32700)."""
    res = test_client.post(
        "/mcp", content=b"invalid {json", headers={"Content-Type": "application/json"}
    )
    assert res.status_code == 400
    data = _parse_mcp_response(res)
    assert data["error"]["code"] == -32700


def test_create_gateway_app_default_wiring() -> None:
    """create_gateway_app initializes default service and routes cleanly without explicit args."""
    settings = GatewayAppSettings()
    app = create_gateway_app(settings=settings)
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200


def test_investigate_incident_structured_content_preservation(test_client: TestClient) -> None:
    """Verify call_tool on investigate_incident returns structuredContent matching DTO.

    And verifies content[0].text is derived from the same sanitized structured dictionary.
    """
    token = _make_token(sub="USR-APP-L3", role="L3")
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "investigate_incident",
            "arguments": {"initial_hypothesis": "Database latency spike"},
        },
        "id": 999,
    }

    res = test_client.post(
        "/mcp",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = _parse_mcp_response(res)
    result = data["result"]

    assert result["isError"] is False
    assert "structuredContent" in result
    structured = result["structuredContent"]
    assert isinstance(structured, dict)
    assert "source_outcomes" in structured
    assert "evidence" in structured

    # Verify compatibility text is serialized from the exact same structured dictionary
    text_content = result["content"][0]["text"]
    assert json.loads(text_content) == structured


def test_existing_tool_wire_behavior_preserved_text_only(test_client: TestClient) -> None:
    """Verify official call_tool on existing 17 tools (e.g. get_ticket) retains text-only result.

    Asserts structuredContent is None / omitted, preventing silent wire-contract migration.
    """
    token = _make_token(sub="USR-APP-L1", role="L1")
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_ticket",
            "arguments": {"ticket_id": 42},
        },
        "id": 1001,
    }

    res = test_client.post(
        "/mcp",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = _parse_mcp_response(res)
    result = data["result"]

    assert result["isError"] is False
    # Existing tool must NOT return structuredContent (preserving pre-Phase-4.3 wire contract)
    assert result.get("structuredContent") is None
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"
    text_content = result["content"][0]["text"]
    parsed_text = json.loads(text_content)
    assert parsed_text == {"echo_tool": "get_ticket", "server": "SUPEROFFICE"}
