"""Unit tests verifying Phase 1 tool contracts and argument propagation."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    DeadlockCriteriaDTO,
    DeadlockDomainDTO,
)
from diag_mcp.server import create_diagnostics_mcp_server
from diag_mcp.services.diagnostic_service import DiagnosticsApplicationService
from platform_security.sanitization import RecursiveOutputSanitizer
from so_mcp.contracts.dtos import (
    CompanyDomainDTO,
    CompanySearchCriteriaDTO,
    PersonDomainDTO,
    PersonSearchCriteriaDTO,
    SuperOfficePageResponse,
    TicketDetailDomainDTO,
    TicketMessageDomainDTO,
    TicketSearchCriteriaDTO,
    TicketSummaryDomainDTO,
)
from so_mcp.server import create_superoffice_mcp_server
from so_mcp.services.ticket_service import SuperOfficeApplicationService


class _RecordingSuperOfficeClient:
    """Mock client recording exact criteria passed by application service."""

    def __init__(self) -> None:
        self.recorded_ticket_criteria: TicketSearchCriteriaDTO | None = None
        self.recorded_company_criteria: CompanySearchCriteriaDTO | None = None
        self.recorded_person_criteria: PersonSearchCriteriaDTO | None = None
        self.recorded_ticket_id_for_messages: int | None = None

    async def get_ticket(self, ticket_id: int) -> TicketDetailDomainDTO:
        return TicketDetailDomainDTO(
            ticket_id=ticket_id,
            title="Test Ticket",
            status="Open",
            category="Support",
            priority="Normal",
        )

    async def search_tickets(
        self, criteria: TicketSearchCriteriaDTO
    ) -> SuperOfficePageResponse[TicketSummaryDomainDTO]:
        self.recorded_ticket_criteria = criteria
        return SuperOfficePageResponse[TicketSummaryDomainDTO](
            items=(
                TicketSummaryDomainDTO(
                    ticket_id=101,
                    title="Database Timeout in Customer Portal",
                    status="Open",
                    category="Database",
                    priority="High",
                ),
            ),
            page=criteria.page,
            page_size=criteria.page_size,
            total_items=1,
            has_next_page=False,
        )

    async def get_ticket_messages(self, ticket_id: int) -> list[TicketMessageDomainDTO]:
        self.recorded_ticket_id_for_messages = ticket_id
        return [
            TicketMessageDomainDTO(
                message_id=i,
                ticket_id=ticket_id,
                author=f"Customer {i}",
                author_type="CUSTOMER",
                body=f"Message body {i}",
                created_at=datetime.now(UTC),
            )
            for i in range(1, 10)  # 9 messages
        ]

    async def list_attachments(self, ticket_id: int) -> list[Any]:
        _ = ticket_id
        return []

    async def get_company(self, company_id: int) -> CompanyDomainDTO:
        return CompanyDomainDTO(company_id=company_id, name="Acme Corp")

    async def find_companies(
        self, criteria: CompanySearchCriteriaDTO
    ) -> SuperOfficePageResponse[CompanyDomainDTO]:
        self.recorded_company_criteria = criteria
        return SuperOfficePageResponse[CompanyDomainDTO](
            items=(CompanyDomainDTO(company_id=1, name="Acme Corp"),),
            page=criteria.page,
            page_size=criteria.page_size,
            total_items=1,
            has_next_page=False,
        )

    async def get_person(self, person_id: int) -> PersonDomainDTO:
        return PersonDomainDTO(person_id=person_id, first_name="John", last_name="Doe")

    async def find_persons(
        self, criteria: PersonSearchCriteriaDTO
    ) -> SuperOfficePageResponse[PersonDomainDTO]:
        self.recorded_person_criteria = criteria
        return SuperOfficePageResponse[PersonDomainDTO](
            items=(PersonDomainDTO(person_id=1, first_name="John", last_name="Doe"),),
            page=criteria.page,
            page_size=criteria.page_size,
            total_items=1,
            has_next_page=False,
        )


@pytest.mark.asyncio
async def test_search_tickets_wires_title_and_category() -> None:
    """Verify search_tickets tool propagates title, category, and status to criteria."""
    client = _RecordingSuperOfficeClient()
    service = SuperOfficeApplicationService(client=client, sanitizer=RecursiveOutputSanitizer())
    server = create_superoffice_mcp_server(service=service)
    tools = server._tool_manager._tools

    result = await tools["search_tickets"].fn(
        title="Timeout",
        category="Database",
        status="Open",
        limit=5,
    )

    assert result is not None
    assert client.recorded_ticket_criteria is not None
    assert client.recorded_ticket_criteria.title == "Timeout"
    assert client.recorded_ticket_criteria.category == "Database"
    assert client.recorded_ticket_criteria.status == "Open"
    assert client.recorded_ticket_criteria.page_size == 5


@pytest.mark.asyncio
async def test_get_ticket_messages_bounds_by_limit() -> None:
    """Verify get_ticket_messages tool respects caller limit."""
    client = _RecordingSuperOfficeClient()
    service = SuperOfficeApplicationService(client=client, sanitizer=RecursiveOutputSanitizer())
    server = create_superoffice_mcp_server(service=service)
    tools = server._tool_manager._tools

    msgs = await tools["get_ticket_messages"].fn(ticket_id=456, limit=3)
    assert len(msgs) == 3
    assert client.recorded_ticket_id_for_messages == 456


@pytest.mark.asyncio
async def test_find_companies_wires_category() -> None:
    """Verify find_companies tool propagates category filter to criteria."""
    client = _RecordingSuperOfficeClient()
    service = SuperOfficeApplicationService(client=client, sanitizer=RecursiveOutputSanitizer())
    server = create_superoffice_mcp_server(service=service)
    tools = server._tool_manager._tools

    result = await tools["find_companies"].fn(name="Acme", category="Enterprise", limit=5)
    assert result is not None
    assert client.recorded_company_criteria is not None
    assert client.recorded_company_criteria.name == "Acme"
    assert client.recorded_company_criteria.category == "Enterprise"
    assert client.recorded_company_criteria.page_size == 5


@pytest.mark.asyncio
async def test_find_persons_wires_contact_id_to_company_id() -> None:
    """Verify find_persons tool maps contact_id argument to company_id criteria."""
    client = _RecordingSuperOfficeClient()
    service = SuperOfficeApplicationService(client=client, sanitizer=RecursiveOutputSanitizer())
    server = create_superoffice_mcp_server(service=service)
    tools = server._tool_manager._tools

    result = await tools["find_persons"].fn(
        first_name="Jane",
        last_name="Smith",
        contact_id=42,
        limit=5,
    )
    assert result is not None
    assert client.recorded_person_criteria is not None
    assert client.recorded_person_criteria.company_id == 42
    assert client.recorded_person_criteria.name == "Jane Smith"


@pytest.mark.asyncio
async def test_find_deadlocks_wires_hours_back_to_start_time() -> None:
    """Verify find_deadlocks tool computes start_time based on hours_back."""
    mock_service = AsyncMock(spec=DiagnosticsApplicationService)
    mock_service.find_deadlocks.return_value = BoundedDiagnosticResultDTO[DeadlockDomainDTO](
        items=(),
        returned_count=0,
        total_matched=0,
        is_truncated=False,
    )
    server = create_diagnostics_mcp_server(service=mock_service)
    tools = server._tool_manager._tools

    before = datetime.now(UTC)
    await tools["find_deadlocks"].fn(hours_back=12, limit=5)

    mock_service.find_deadlocks.assert_called_once()
    called_criteria: DeadlockCriteriaDTO = mock_service.find_deadlocks.call_args[0][0]
    assert called_criteria.limit == 5
    assert called_criteria.start_time is not None
    # Verify computed start_time is approximately 12 hours ago (within 5 seconds tolerance)
    expected_approx = before - timedelta(hours=12)
    diff = abs((called_criteria.start_time - expected_approx).total_seconds())
    assert diff < 5.0
