"""Unit tests for SuperOffice FastMCP server tool registration and DNS rebinding."""

from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from so_mcp.audit.contracts import (
    TicketActionItemDTO,
    TicketAuditTrailDTO,
    TicketLogMilestoneDTO,
)
from so_mcp.contracts.dtos import TicketDetailDomainDTO
from so_mcp.contracts.errors import SuperOfficeIntegrationError
from so_mcp.extra_tables.contracts import (
    ExtraFieldDefinitionDTO,
    ExtraTableDetailSchemaDTO,
    ExtraTableQueryResultDTO,
    ExtraTableSummaryDTO,
)
from so_mcp.server import create_app, create_superoffice_mcp_server
from so_mcp.sync.contracts import SyncManifestDTO, SyncResultDTO
from tests.fakes.fake_superoffice_client import FakeSuperOfficeClient


def test_so_server_registers_all_approved_tools() -> None:
    """SuperOffice FastMCP server registers approved operations including sync_codebase."""
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
        "sync_codebase",
        "list_extra_tables",
        "get_extra_table_schema",
        "query_extra_table",
        "get_ticket_audit_trail",
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


@pytest.mark.asyncio
async def test_so_server_sync_codebase_invocation(tmp_path) -> None:
    """SuperOffice FastMCP server invokes sync_codebase and returns serialized manifest."""
    mock_sync_service = AsyncMock()
    manifest = SyncManifestDTO(
        generated_at="2026-09-23T12:00:00Z",
        source_mode="http",
        target_dir=str(tmp_path),
        total_scripts=3,
        total_screens=1,
        total_extra_tables=2,
    )
    mock_sync_service.sync.return_value = SyncResultDTO(success=True, manifest=manifest)

    server = create_superoffice_mcp_server(sync_service=mock_sync_service)
    tools = server._tool_manager._tools

    res = await tools["sync_codebase"].fn(mode="http", dry_run=True)
    assert res["success"] is True
    assert res["manifest"]["total_scripts"] == 3
    mock_sync_service.sync.assert_called_once_with(mode="http", tables=None, dry_run=True)


@pytest.mark.asyncio
async def test_so_server_extra_tables_tools_invocation() -> None:
    """SuperOffice FastMCP server invokes extra table tools with mocked service."""
    mock_extra_service = AsyncMock()
    mock_extra_service.list_extra_tables.return_value = [
        ExtraTableSummaryDTO(
            id=1,
            table_name="y_subscription",
            display_name="Subscription",
            description="Subs",
            field_count=2,
        )
    ]
    mock_extra_service.get_extra_table_schema.return_value = ExtraTableDetailSchemaDTO(
        id=1,
        table_name="y_subscription",
        display_name="Subscription",
        description="Subs",
        fields=(
            ExtraFieldDefinitionDTO(
                id=1,
                extra_table_id=1,
                field_name="x_msisdn",
                display_name="MSISDN",
                type_code=10,
                type_name="string",
            ),
        ),
    )
    mock_extra_service.query_extra_table.return_value = ExtraTableQueryResultDTO(
        table_name="y_subscription",
        total_rows_returned=1,
        limit=20,
        offset=0,
        columns=("id", "x_msisdn"),
        rows=({"id": 1, "x_msisdn": "12345678"},),
    )

    server = create_superoffice_mcp_server(extra_table_service=mock_extra_service)
    tools = server._tool_manager._tools

    # 1. list_extra_tables
    tables_res = await tools["list_extra_tables"].fn(search="sub")
    assert tables_res["total_count"] == 1
    assert tables_res["tables"][0]["table_name"] == "y_subscription"
    mock_extra_service.list_extra_tables.assert_called_once_with(search="sub")

    # 2. get_extra_table_schema
    schema_res = await tools["get_extra_table_schema"].fn(table_name="y_subscription")
    assert schema_res["table_name"] == "y_subscription"
    assert len(schema_res["fields"]) == 1

    # 3. query_extra_table
    query_res = await tools["query_extra_table"].fn(
        table_name="y_subscription",
        fields=["x_msisdn"],
        filters={"x_msisdn": "12345678"},
        limit=10,
    )
    assert query_res["total_rows_returned"] == 1
    assert query_res["rows"][0]["x_msisdn"] == "12345678"


@pytest.mark.asyncio
async def test_so_server_audit_trail_tools_invocation() -> None:
    """SuperOffice FastMCP server invokes get_ticket_audit_trail on TicketAuditService."""
    mock_audit_service = AsyncMock()
    mock_audit_service.get_ticket_audit_trail.return_value = TicketAuditTrailDTO(
        ticket_id=10209,
        milestone_logs=(
            TicketLogMilestoneDTO(
                id=1,
                occurred_at=None,
                actor="junaid.tariq",
                event_code=37,
                description="New request created",
            ),
        ),
        actions=(
            TicketActionItemDTO(
                action_id=10,
                occurred_at=None,
                actor="junaid.tariq",
                user_id=1606,
                customer_id=-1,
                action_code=13,
                action_name="Ticket updated",
                description="Status changed",
                details=None,
                changes=(),
            ),
        ),
        total_milestones=1,
        total_actions=1,
        total_changes=0,
    )

    server = create_superoffice_mcp_server(audit_service=mock_audit_service)
    tools = server._tool_manager._tools

    res = await tools["get_ticket_audit_trail"].fn(ticket_id=10209)
    assert res["ticket_id"] == 10209
    assert res["total_milestones"] == 1
    assert res["total_actions"] == 1
    assert res["milestone_logs"][0]["actor"] == "junaid.tariq"
    mock_audit_service.get_ticket_audit_trail.assert_called_once()
