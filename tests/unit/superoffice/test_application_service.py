"""Unit tests for SuperOfficeApplicationService field selection and PII sanitization."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from platform_security.models import AttachmentMetadata
from platform_security.sanitization import RecursiveOutputSanitizer
from so_mcp.contracts.dtos import (
    CompanyDomainDTO,
    CompanySearchCriteriaDTO,
    MinimizedCompanyDTO,
    MinimizedPersonDTO,
    MinimizedTicketDetailDTO,
    MinimizedTicketMessageDTO,
    MinimizedTicketSummaryDTO,
    PersonDomainDTO,
    PersonSearchCriteriaDTO,
    SuperOfficePageResponse,
    TicketDetailDomainDTO,
    TicketMessageDomainDTO,
    TicketSearchCriteriaDTO,
    TicketSummaryDomainDTO,
)
from so_mcp.contracts.interfaces import SuperOfficeClient
from so_mcp.services.ticket_service import SuperOfficeApplicationService


@pytest.fixture
def mock_client() -> AsyncMock:
    """Fixture providing a mock SuperOfficeClient."""
    return AsyncMock(spec=SuperOfficeClient)


@pytest.fixture
def app_service(mock_client: AsyncMock) -> SuperOfficeApplicationService:
    """Fixture providing an instantiated SuperOfficeApplicationService."""
    sanitizer = RecursiveOutputSanitizer()
    return SuperOfficeApplicationService(client=mock_client, sanitizer=sanitizer)


async def test_get_ticket_masks_pii_in_description(
    app_service: SuperOfficeApplicationService, mock_client: AsyncMock
) -> None:
    """Test get_ticket performs field whitelisting and masks inline PII in ticket description."""
    raw_desc = (
        "Please reach out to support.contact@customer.com or phone +1-555-0199 for token abcdef."
    )
    mock_client.get_ticket.return_value = TicketDetailDomainDTO(
        ticket_id=101,
        title="VPN Gateway connectivity failure",
        status="Open",
        category="Networking",
        priority="High",
        description=raw_desc,
        assigned_to="agent_99",
        customer_id=501,
        customer_reference="CUST-REF-999",
        created_at=datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 20, 11, 0, 0, tzinfo=UTC),
    )

    result = await app_service.get_ticket(101)
    assert isinstance(result, MinimizedTicketDetailDTO)
    assert result.ticket_id == 101
    assert result.title == "VPN Gateway connectivity failure"
    assert result.status == "Open"
    assert result.category == "Networking"
    assert result.priority == "High"
    assert result.assigned_agent_id == "agent_99"
    assert result.sanitized_customer_reference == "CUST-REF-999"

    # PII Sanitization verification
    assert "support.contact@customer.com" not in result.sanitized_description
    assert "[REDACTED_EMAIL]" in result.sanitized_description
    assert "+1-555-0199" not in result.sanitized_description


async def test_search_tickets_preserves_pagination_metadata(
    app_service: SuperOfficeApplicationService, mock_client: AsyncMock
) -> None:
    """Test search_tickets returns MinimizedTicketSummaryDTOs while preserving pagination."""
    mock_client.search_tickets.return_value = SuperOfficePageResponse[TicketSummaryDomainDTO](
        items=(
            TicketSummaryDomainDTO(
                ticket_id=1,
                title="T1",
                status="Open",
                category="IT",
                priority="Low",
                created_at=datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 8, 20, 10, 0, 0, tzinfo=UTC),
            ),
        ),
        page=1,
        page_size=20,
        total_items=None,
        has_next_page=True,
    )

    criteria = TicketSearchCriteriaDTO(page=1, page_size=20)
    result = await app_service.search_tickets(criteria)

    assert isinstance(result, SuperOfficePageResponse)
    assert len(result.items) == 1
    assert isinstance(result.items[0], MinimizedTicketSummaryDTO)
    assert result.items[0].ticket_id == 1
    assert result.page == 1
    assert result.page_size == 20
    assert result.has_next_page is True
    assert result.total_items is None


async def test_company_operations_minimized_dtos(
    app_service: SuperOfficeApplicationService, mock_client: AsyncMock
) -> None:
    """Test get_company and find_companies return MinimizedCompanyDTOs."""
    mock_client.get_company.return_value = CompanyDomainDTO(
        company_id=501,
        name="Global Tech AS",
        department="Bergen",
        org_number="NO-999888777",
    )
    mock_client.find_companies.return_value = SuperOfficePageResponse[CompanyDomainDTO](
        items=(CompanyDomainDTO(company_id=501, name="Global Tech AS"),),
        page=1,
        page_size=10,
        total_items=None,
        has_next_page=False,
    )

    company = await app_service.get_company(501)
    assert isinstance(company, MinimizedCompanyDTO)
    assert company.company_id == 501
    assert company.name == "Global Tech AS"

    page_resp = await app_service.find_companies(CompanySearchCriteriaDTO(name="Global"))
    assert isinstance(page_resp, SuperOfficePageResponse)
    assert isinstance(page_resp.items[0], MinimizedCompanyDTO)


async def test_person_operations_omits_direct_contact_pii(
    app_service: SuperOfficeApplicationService, mock_client: AsyncMock
) -> None:
    """Test get_person and find_persons omit direct customer email/phone PII."""
    mock_client.get_person.return_value = PersonDomainDTO(
        person_id=801,
        first_name="Jane",
        last_name="Doe",
        email="jane.doe.private@acme.example.com",
        phone="+47 98765432",
        company_id=501,
    )
    mock_client.find_persons.return_value = SuperOfficePageResponse[PersonDomainDTO](
        items=(
            PersonDomainDTO(
                person_id=801,
                first_name="Jane",
                last_name="Doe",
                email="jane.doe.private@acme.example.com",
                phone="+47 98765432",
                company_id=501,
            ),
        ),
        page=1,
        page_size=10,
        total_items=None,
        has_next_page=False,
    )

    person = await app_service.get_person(801)
    assert isinstance(person, MinimizedPersonDTO)
    assert person.person_id == 801
    assert person.display_name == "Jane Doe"
    assert person.company_id == 501
    # Verify email and phone are omitted from MinimizedPersonDTO
    assert not hasattr(person, "email")
    assert not hasattr(person, "phone")

    page_resp = await app_service.find_persons(PersonSearchCriteriaDTO(name="Jane"))
    assert isinstance(page_resp.items[0], MinimizedPersonDTO)
    assert page_resp.items[0].display_name == "Jane Doe"


async def test_get_ticket_messages_sanitizes_bodies(
    app_service: SuperOfficeApplicationService, mock_client: AsyncMock
) -> None:
    """Test get_ticket_messages scrubs message bodies."""
    mock_client.get_ticket_messages.return_value = [
        TicketMessageDomainDTO(
            message_id=1,
            ticket_id=101,
            author="Support Lead",
            author_type="AGENT",
            body="Config updated. Notified admin at root@internal.corp and phone +1-555-0144.",
            created_at=datetime(2026, 8, 20, 10, 30, 0, tzinfo=UTC),
            attachments=(),
        )
    ]

    messages = await app_service.get_ticket_messages(101)
    assert len(messages) == 1
    assert isinstance(messages[0], MinimizedTicketMessageDTO)
    assert messages[0].message_id == 1
    assert "root@internal.corp" not in messages[0].sanitized_body
    assert "[REDACTED_EMAIL]" in messages[0].sanitized_body


async def test_list_attachments_metadata_only(
    app_service: SuperOfficeApplicationService, mock_client: AsyncMock
) -> None:
    """Test list_attachments returns metadata records only."""
    mock_client.list_attachments.return_value = [
        AttachmentMetadata(
            attachment_id="att_1",
            filename="system_diag.log",
            mime_type="text/plain",
            size_bytes=4096,
            md5_hash="",
        )
    ]

    attachments = await app_service.list_attachments(101)
    assert len(attachments) == 1
    assert attachments[0].attachment_id == "att_1"
    assert attachments[0].filename == "system_diag.log"
    assert attachments[0].size_bytes == 4096
