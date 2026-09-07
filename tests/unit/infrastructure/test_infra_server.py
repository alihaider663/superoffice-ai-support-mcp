"""Unit tests for Infrastructure FastMCP server skeleton (2A-D07 DEFERRED) and DNS rebinding."""

from starlette.testclient import TestClient

from infra_mcp.server import create_app, create_infrastructure_mcp_server


def test_infra_server_registers_0_tools_deferred() -> None:
    """Infrastructure FastMCP server registers 0 operational tools per Decision 2A-D07."""
    server = create_infrastructure_mcp_server()
    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    assert tool_names == set()


def test_infra_server_mcp_endpoint_tools_list() -> None:
    """Infrastructure FastMCP server responds to /mcp tools/list with empty list."""
    app = create_app()
    with TestClient(app) as client:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1,
        }
        res = client.post(
            "/mcp", json=payload, headers={"Accept": "application/json, text/event-stream"}
        )
        assert res.status_code == 200
        assert "tools" in res.text


def test_infra_server_dns_rebinding_protection() -> None:
    """Allowed host headers pass; unapproved Host headers return 421 Misdirected Request."""
    app = create_app()
    with TestClient(app) as client:
        payload = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        res_ok = client.post(
            "/mcp",
            json=payload,
            headers={"Host": "infra-backend", "Accept": "application/json, text/event-stream"},
        )
        assert res_ok.status_code == 200

        unapproved_headers = {
            "Host": "untrusted-attacker.com",
            "Accept": "application/json, text/event-stream",
        }
        res_denied = client.post("/mcp", json=payload, headers=unapproved_headers)
        assert res_denied.status_code == 421
