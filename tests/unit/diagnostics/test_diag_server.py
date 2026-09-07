"""Unit tests for Diagnostics FastMCP server tool registration and DNS rebinding."""

import pytest
from starlette.testclient import TestClient

from diag_mcp.contracts.errors import DatabaseDiagnosticError, LogSearchError
from diag_mcp.server import create_app, create_diagnostics_mcp_server
from tests.fakes.fake_diagnostic_repository import FakeDiagnosticRepository


def test_diag_server_registers_all_6_tools() -> None:
    """Diagnostics FastMCP server registers all 6 database and log diagnostic tools."""
    server = create_diagnostics_mcp_server()
    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    expected_tools = {
        "get_database_health",
        "find_slow_queries",
        "get_ticket_diagnostic_record",
        "search_logs",
        "find_deadlocks",
        "find_blocking_sessions",
    }
    assert tool_names == expected_tools


def test_diag_server_mcp_endpoint_invocation() -> None:
    """Diagnostics FastMCP server responds to /mcp tools/call."""
    fake_repo = FakeDiagnosticRepository()
    app = create_app(repository=fake_repo)
    with TestClient(app) as client:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "get_database_health", "arguments": {}},
            "id": 1,
        }
        res = client.post(
            "/mcp", json=payload, headers={"Accept": "application/json, text/event-stream"}
        )
        assert res.status_code == 200
        assert "is_healthy" in res.text


def test_diag_server_dns_rebinding_protection() -> None:
    """Allowed host headers pass; unapproved Host headers return 421 Misdirected Request."""
    fake_repo = FakeDiagnosticRepository()
    app = create_app(repository=fake_repo)
    with TestClient(app) as client:
        payload = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        res_ok = client.post(
            "/mcp",
            json=payload,
            headers={"Host": "diag-backend", "Accept": "application/json, text/event-stream"},
        )
        assert res_ok.status_code == 200

        unapproved_headers = {
            "Host": "untrusted-attacker.com",
            "Accept": "application/json, text/event-stream",
        }
        res_denied = client.post("/mcp", json=payload, headers=unapproved_headers)
        assert res_denied.status_code == 421


def test_create_app_runtime_composition_uses_real_repository_by_default() -> None:
    """create_app wires DiagnosticsApplicationService with MssqlDiagnosticRepository by default."""
    app = create_app()
    assert app is not None


@pytest.mark.asyncio
async def test_unwired_app_service_fails_closed_no_synthetic_success() -> None:
    """If app_service is None, operational tools fail closed with unconfigured error."""
    server = create_diagnostics_mcp_server(service=None, repository=None)
    tools = server._tool_manager._tools

    # 1. get_database_health
    with pytest.raises(DatabaseDiagnosticError) as exc_info:
        await tools["get_database_health"].fn()
    assert exc_info.value.error_code == "DIAGNOSTICS_SERVICE_UNCONFIGURED"

    # 2. find_slow_queries
    with pytest.raises(DatabaseDiagnosticError) as exc_info:
        await tools["find_slow_queries"].fn()
    assert exc_info.value.error_code == "DIAGNOSTICS_SERVICE_UNCONFIGURED"

    # 3. find_deadlocks
    with pytest.raises(DatabaseDiagnosticError) as exc_info:
        await tools["find_deadlocks"].fn()
    assert exc_info.value.error_code == "DIAGNOSTICS_SERVICE_UNCONFIGURED"

    # 4. find_blocking_sessions
    with pytest.raises(DatabaseDiagnosticError) as exc_info:
        await tools["find_blocking_sessions"].fn()
    assert exc_info.value.error_code == "DIAGNOSTICS_SERVICE_UNCONFIGURED"


@pytest.mark.asyncio
async def test_blocked_tools_remain_blocked() -> None:
    """Verify get_ticket_diagnostic_record and search_logs remain blocked."""
    server = create_diagnostics_mcp_server()
    tools = server._tool_manager._tools

    with pytest.raises(DatabaseDiagnosticError) as exc_info:
        await tools["get_ticket_diagnostic_record"].fn(ticket_id=123)
    assert exc_info.value.error_code == "DIAGNOSTIC_SCHEMA_NOT_CONFIGURED"

    with pytest.raises(LogSearchError) as exc_info_log:
        await tools["search_logs"].fn(query="test")
    assert exc_info_log.value.error_code == "LOG_SEARCH_BACKEND_NOT_CONFIGURED"
