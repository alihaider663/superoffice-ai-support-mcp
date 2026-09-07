"""Unit tests for Knowledge FastMCP server tool registration and DNS rebinding."""

from starlette.testclient import TestClient

from kb_mcp.server import create_app, create_knowledge_mcp_server


def test_kb_server_registers_all_3_tools() -> None:
    """Knowledge FastMCP server registers all 3 knowledge and runbook tools."""
    server = create_knowledge_mcp_server()
    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    expected_tools = {
        "search_knowledge",
        "get_runbook",
        "find_known_issues",
    }
    assert tool_names == expected_tools


def test_kb_server_mcp_endpoint_invocation() -> None:
    """Knowledge FastMCP server responds to /mcp tools/call."""
    app = create_app()
    with TestClient(app) as client:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "search_knowledge", "arguments": {"query_text": "OAuth"}},
            "id": 1,
        }
        res = client.post(
            "/mcp", json=payload, headers={"Accept": "application/json, text/event-stream"}
        )
        assert res.status_code == 200
        assert "Knowledge Entry" in res.text


def test_kb_server_dns_rebinding_protection() -> None:
    """Allowed host headers pass; unapproved Host headers return 421 Misdirected Request."""
    app = create_app()
    with TestClient(app) as client:
        payload = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        res_ok = client.post(
            "/mcp",
            json=payload,
            headers={"Host": "kb-backend", "Accept": "application/json, text/event-stream"},
        )
        assert res_ok.status_code == 200

        unapproved_headers = {
            "Host": "untrusted-attacker.com",
            "Accept": "application/json, text/event-stream",
        }
        res_denied = client.post("/mcp", json=payload, headers=unapproved_headers)
        assert res_denied.status_code == 421
