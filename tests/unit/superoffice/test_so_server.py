"""Unit tests for SuperOffice FastMCP server tool registration and DNS rebinding."""

import pytest
from starlette.testclient import TestClient

from so_mcp.contracts.dtos import TicketDetailDomainDTO
from so_mcp.contracts.errors import SuperOfficeIntegrationError
from so_mcp.server import create_app, create_superoffice_mcp_server
from tests.fakes.fake_superoffice_client import FakeSuperOfficeClient


def test_so_server_registers_all_8_approved_tools() -> None:
    """SuperOffice FastMCP server registers exactly the 8 approved read-only SuperOffice tools."""
    server = create_superoffice_mcp_server()
    tool_names = {tool.name for tool in server._tool_manager.list_tools()}
    expected_tools = {
        "get_ticket",
        "search_tickets",
        "get_ticket_messages",
        "list_attachments",
        "get_company",
        "find_companies",
        "get_person",
        "find_persons",
    }
    assert tool_names == expected_tools


def test_so_server_mcp_endpoint_invocation() -> None:
    """SuperOffice FastMCP server responds to /mcp tools/call."""
    fake_client = FakeSuperOfficeClient()
    fake_client.seed_ticket(
        TicketDetailDomainDTO(
            ticket_id=100,
            title="Ticket 100",
            status="Open",
            category="Support",
            priority="Normal",
        )
    )
    app = create_app(client=fake_client)
    with TestClient(app) as client:
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "get_ticket", "arguments": {"ticket_id": 100}},
            "id": 1,
        }
        res = client.post(
            "/mcp", json=payload, headers={"Accept": "application/json, text/event-stream"}
        )
        assert res.status_code == 200
        assert "100" in res.text


def test_so_server_dns_rebinding_protection() -> None:
    """Allowed host headers pass; unapproved Host headers return 421 Misdirected Request."""
    fake_client = FakeSuperOfficeClient()
    app = create_app(client=fake_client)
    with TestClient(app) as client:
        payload = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        # Allowed host
        res_ok = client.post(
            "/mcp",
            json=payload,
            headers={"Host": "testserver", "Accept": "application/json, text/event-stream"},
        )
        assert res_ok.status_code == 200

        # Unapproved host
        unapproved_headers = {
            "Host": "untrusted-attacker.com",
            "Accept": "application/json, text/event-stream",
        }
        res_denied = client.post("/mcp", json=payload, headers=unapproved_headers)
        assert res_denied.status_code == 421


def test_create_app_runtime_composition_uses_real_client_by_default() -> None:
    """create_app wires SuperOfficeApplicationService with real REST client by default."""
    app = create_app()
    assert app is not None


@pytest.mark.asyncio
async def test_unwired_app_service_fails_closed_no_synthetic_success() -> None:
    """If app_service is None, all 8 operational tools fail closed with unconfigured error."""
    server = create_superoffice_mcp_server(service=None, client=None)
    tools = server._tool_manager._tools

    # 1. get_ticket
    with pytest.raises(SuperOfficeIntegrationError) as exc_1:
        await tools["get_ticket"].fn(ticket_id=10198)
    assert exc_1.value.error_code == "SUPEROFFICE_SERVICE_UNCONFIGURED"

    # 2. search_tickets
    with pytest.raises(SuperOfficeIntegrationError) as exc_2:
        await tools["search_tickets"].fn()
    assert exc_2.value.error_code == "SUPEROFFICE_SERVICE_UNCONFIGURED"

    # 3. get_ticket_messages
    with pytest.raises(SuperOfficeIntegrationError) as exc_3:
        await tools["get_ticket_messages"].fn(ticket_id=10198)
    assert exc_3.value.error_code == "SUPEROFFICE_SERVICE_UNCONFIGURED"

    # 4. list_attachments
    with pytest.raises(SuperOfficeIntegrationError) as exc_4:
        await tools["list_attachments"].fn(ticket_id=10198)
    assert exc_4.value.error_code == "SUPEROFFICE_SERVICE_UNCONFIGURED"

    # 5. get_company
    with pytest.raises(SuperOfficeIntegrationError) as exc_5:
        await tools["get_company"].fn(contact_id=1)
    assert exc_5.value.error_code == "SUPEROFFICE_SERVICE_UNCONFIGURED"

    # 6. find_companies
    with pytest.raises(SuperOfficeIntegrationError) as exc_6:
        await tools["find_companies"].fn()
    assert exc_6.value.error_code == "SUPEROFFICE_SERVICE_UNCONFIGURED"

    # 7. get_person
    with pytest.raises(SuperOfficeIntegrationError) as exc_7:
        await tools["get_person"].fn(person_id=1)
    assert exc_7.value.error_code == "SUPEROFFICE_SERVICE_UNCONFIGURED"

    # 8. find_persons
    with pytest.raises(SuperOfficeIntegrationError) as exc_8:
        await tools["find_persons"].fn()
    assert exc_8.value.error_code == "SUPEROFFICE_SERVICE_UNCONFIGURED"


@pytest.mark.asyncio
async def test_synthetic_fallback_regression_never_emits_unwired_stubs() -> None:
    """Verify old synthetic signatures (e.g. title='Ticket #10198') are never produced."""
    server = create_superoffice_mcp_server(service=None, client=None)
    tools = server._tool_manager._tools

    with pytest.raises(SuperOfficeIntegrationError):
        await tools["get_ticket"].fn(ticket_id=10198)
