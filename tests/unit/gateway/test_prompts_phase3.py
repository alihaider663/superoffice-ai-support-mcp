"""Unit tests verifying Phase 3 MCP Prompts and Runtime AI Guardrails."""

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.testclient import TestClient

from platform_gateway.contracts.dispatch import (
    GatewayDispatchRequest,
    GatewayDispatchResponse,
)
from platform_gateway.contracts.interfaces import StreamableHttpDispatcher
from platform_gateway.contracts.routing import ToolRouteDefinition
from platform_gateway.prompts import (
    get_platform_prompt_result,
    get_platform_prompts,
)
from platform_gateway.registry import create_default_routing_table
from platform_gateway.server.app import create_gateway_app
from platform_gateway.services.gateway_service import GatewayApplicationService
from platform_security.jwt import JwtAuthenticator
from platform_security.rbac import YamlPolicyEngine
from platform_security.sanitization import RecursiveOutputSanitizer

TEST_JWT_SECRET = "test-secret-key-prompts-phase3-32bytes-min"


def _parse_mcp_response(res: httpx.Response) -> Any:
    """Extract JSON data from MCP response supporting SSE and direct JSON formats."""
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
def prompt_test_client() -> Generator[TestClient, None, None]:
    """Create test client configured for MCP Prompt inspection."""
    mock_dispatcher = AsyncMock(spec=StreamableHttpDispatcher)

    async def _mock_dispatch(
        route: ToolRouteDefinition,  # noqa: ARG001
        request: GatewayDispatchRequest,
    ) -> GatewayDispatchResponse:
        return GatewayDispatchResponse(
            tool_name=request.tool_name,
            success=True,
            result={"echo": request.tool_name},
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


def test_get_platform_prompts_definitions() -> None:
    """Verify platform prompts expose required tools, names, and argument schemas."""
    prompts = get_platform_prompts()
    assert len(prompts) == 3
    prompt_map = {p.name: p for p in prompts}

    assert "investigate_support_ticket" in prompt_map
    assert "diagnose_database_performance" in prompt_map
    assert "remediate_incident" in prompt_map

    # Verify investigate_support_ticket arguments
    inv_args = {arg.name: arg for arg in (prompt_map["investigate_support_ticket"].arguments or [])}
    assert "ticket_id" in inv_args
    assert inv_args["ticket_id"].required is True
    assert "include_db_diagnostics" in inv_args
    assert inv_args["include_db_diagnostics"].required is False
    assert "hours_back" in inv_args


def test_get_platform_prompt_result_content() -> None:
    """Verify prompt result renders guardrail invariants and template arguments."""
    res = get_platform_prompt_result(
        "investigate_support_ticket",
        {"ticket_id": "9942", "hours_back": "12", "include_db_diagnostics": "true"},
    )
    assert res.description == "Investigate SuperOffice incident for Ticket #9942"
    assert len(res.messages) == 1
    assert res.messages[0].role == "user"

    content_text = res.messages[0].content.text
    assert "Ticket #9942" in content_text
    assert "FACTUAL GROUNDING (ANTI-HALLUCINATION)" in content_text
    assert "NEGATIVE EVIDENCE INTERPRETATION" in content_text
    assert "PREVENT TOOL RETRY LOOPS (LOOP PREVENTION)" in content_text
    assert "COMPOSITE INVESTIGATION FIRST (LATENCY OPTIMIZATION)" in content_text
    assert "EVIDENCE CLASSIFICATION LEVELS" in content_text
    assert "CONFIRMED" in content_text
    assert "PROBABLE" in content_text
    assert "UNKNOWN" in content_text
    assert "search_logs" in content_text
    assert "get_ticket_diagnostic_record" in content_text


def test_get_platform_prompt_result_unknown_name_raises_value_error() -> None:
    """Unknown prompt name raises descriptive ValueError."""
    with pytest.raises(ValueError, match="Unknown prompt 'nonexistent_prompt'"):
        get_platform_prompt_result("nonexistent_prompt")


def test_mcp_streamable_prompts_list(prompt_test_client: TestClient) -> None:
    """POST /mcp with prompts/list returns registered prompts via MCP session."""
    headers = {"Accept": "application/json, text/event-stream"}
    payload = {
        "jsonrpc": "2.0",
        "method": "prompts/list",
        "id": "p-list-1",
    }
    res = prompt_test_client.post("/mcp", json=payload, headers=headers)
    assert res.status_code == 200
    data = _parse_mcp_response(res)
    assert data["id"] == "p-list-1"
    prompts = data["result"]["prompts"]
    assert len(prompts) == 3
    names = [p["name"] for p in prompts]
    assert "investigate_support_ticket" in names
    assert "diagnose_database_performance" in names
    assert "remediate_incident" in names


def test_mcp_streamable_prompts_get(prompt_test_client: TestClient) -> None:
    """POST /mcp with prompts/get returns resolved prompt messages."""
    headers = {"Accept": "application/json, text/event-stream"}
    payload = {
        "jsonrpc": "2.0",
        "method": "prompts/get",
        "params": {
            "name": "investigate_support_ticket",
            "arguments": {"ticket_id": "1001"},
        },
        "id": "p-get-1",
    }
    res = prompt_test_client.post("/mcp", json=payload, headers=headers)
    assert res.status_code == 200
    data = _parse_mcp_response(res)
    assert data["id"] == "p-get-1"
    result = data["result"]
    assert "messages" in result
    assert len(result["messages"]) == 1
    assert "Ticket #1001" in result["messages"][0]["content"]["text"]


def test_mcp_streamable_initialize_advertises_prompts_capability(
    prompt_test_client: TestClient,
) -> None:
    """POST /mcp with initialize includes prompts capability."""
    headers = {"Accept": "application/json, text/event-stream"}
    payload = {
        "jsonrpc": "2.0",
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
        "id": "init-p",
    }
    res = prompt_test_client.post("/mcp", json=payload, headers=headers)
    assert res.status_code == 200
    data = _parse_mcp_response(res)
    capabilities = data["result"]["capabilities"]
    assert "prompts" in capabilities
    assert capabilities["prompts"]["listChanged"] is False


def test_mcp_json_fallback_prompts_list_and_get(prompt_test_client: TestClient) -> None:
    """POST /mcp/json supports prompts/list and prompts/get for fallback clients."""
    # Test prompts/list
    res_list = prompt_test_client.post(
        "/mcp/json",
        json={"jsonrpc": "2.0", "id": 101, "method": "prompts/list"},
    )
    assert res_list.status_code == 200
    data_list = res_list.json()
    assert len(data_list["result"]["prompts"]) == 3

    # Test prompts/get valid
    res_get = prompt_test_client.post(
        "/mcp/json",
        json={
            "jsonrpc": "2.0",
            "id": 102,
            "method": "prompts/get",
            "params": {
                "name": "remediate_incident",
                "arguments": {"incident_summary": "Deadlocks observed"},
            },
        },
    )
    assert res_get.status_code == 200
    data_get = res_get.json()
    assert "messages" in data_get["result"]
    assert "Deadlocks observed" in data_get["result"]["messages"][0]["content"]["text"]

    # Test prompts/get invalid prompt name
    res_invalid = prompt_test_client.post(
        "/mcp/json",
        json={
            "jsonrpc": "2.0",
            "id": 103,
            "method": "prompts/get",
            "params": {"name": "unknown_prompt"},
        },
    )
    assert res_invalid.status_code == 404
    data_invalid = res_invalid.json()
    assert data_invalid["error"]["code"] == -32602
    assert "Unknown prompt 'unknown_prompt'" in data_invalid["error"]["message"]
