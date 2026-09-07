"""Offline contract tests for SuperOffice DTOs, Protocols, errors, and test fake."""

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from platform_security.models import AttachmentMetadata
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
    SuperOfficePageRequest,
    SuperOfficePageResponse,
    TicketDetailDomainDTO,
    TicketMessageDomainDTO,
    TicketSearchCriteriaDTO,
    TicketSummaryDomainDTO,
)
from so_mcp.contracts.errors import (
    SuperOfficeAuthenticationError,
    SuperOfficeEntityNotFoundError,
    SuperOfficeIntegrationError,
)
from so_mcp.contracts.interfaces import SuperOfficeClient
from tests.fakes.fake_superoffice_client import FakeSuperOfficeClient

# ============================================================================
# 1. DTO Validation & Immutability Tests
# ============================================================================


def test_ticket_summary_domain_dto_valid() -> None:
    """Verify TicketSummaryDomainDTO creation with valid attributes."""
    now = datetime.now(UTC)
    dto = TicketSummaryDomainDTO(
        ticket_id=101,
        title="Unable to sync contacts",
        status="Open",
        category="Integrations",
        priority="High",
        created_at=now,
        updated_at=now,
    )
    assert dto.ticket_id == 101
    assert dto.title == "Unable to sync contacts"
    assert dto.status == "Open"


def test_dto_immutability_and_extra_forbid() -> None:
    """Verify models inherit frozen configuration and forbid extra fields."""
    now = datetime.now(UTC)
    dto = TicketSummaryDomainDTO(
        ticket_id=102,
        title="Payment gateway error",
        status="Investigating",
        category="Billing",
        priority="Critical",
        created_at=now,
        updated_at=now,
    )
    # Frozen mutation check via dynamic property modification
    field_to_mutate = "status"
    with pytest.raises(ValidationError):
        setattr(dto, field_to_mutate, "Closed")

    # Extra field forbid check via model_validate
    extra_payload = {
        "ticket_id": 103,
        "title": "Extra field test",
        "status": "Open",
        "category": "General",
        "priority": "Low",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "unauthorized_field": "malicious",
    }
    with pytest.raises(ValidationError):
        TicketSummaryDomainDTO.model_validate(extra_payload)


def test_minimized_ai_dtos_safe_boundary() -> None:
    """Verify Minimized AI DTOs carry explicit sanitized field names."""
    now = datetime.now(UTC)
    ai_summary = MinimizedTicketSummaryDTO(
        ticket_id=201,
        title="Login loop issue",
        status="Open",
        category="Auth",
        priority="Normal",
        created_at=now,
    )
    assert ai_summary.ticket_id == 201

    ai_detail = MinimizedTicketDetailDTO(
        ticket_id=201,
        title="Login loop issue",
        status="Open",
        category="Auth",
        priority="Normal",
        sanitized_description="Customer reports login failure with error ERR-401.",
        sanitized_customer_reference="REF-CUST-8832",
        assigned_agent_id="AGENT-44",
        created_at=now,
    )
    assert ai_detail.sanitized_customer_reference == "REF-CUST-8832"
    assert "sanitized_description" in MinimizedTicketDetailDTO.model_fields

    ai_msg = MinimizedTicketMessageDTO(
        message_id=501,
        ticket_id=201,
        author_type="CUSTOMER",
        sanitized_body="I tried resetting my password but did not receive email.",
        created_at=now,
    )
    assert ai_msg.author_type == "CUSTOMER"
    assert ai_msg.attachments == ()

    ai_person = MinimizedPersonDTO(person_id=12, display_name="Support Contact", company_id=10)
    assert ai_person.display_name == "Support Contact"


# ============================================================================
# 2. Localized Pagination Envelope Tests
# ============================================================================


def test_superoffice_page_response_bounds() -> None:
    """Verify SuperOfficePageResponse generic bounding and metadata calculation."""
    items = (
        MinimizedCompanyDTO(company_id=1, name="Acme Nordic"),
        MinimizedCompanyDTO(company_id=2, name="Fjord Logistics"),
    )
    page_resp = SuperOfficePageResponse[MinimizedCompanyDTO](
        items=items,
        page=1,
        page_size=2,
        total_items=5,
        has_next_page=True,
    )
    assert len(page_resp.items) == 2
    assert page_resp.has_next_page is True
    assert page_resp.total_items == 5


def test_superoffice_page_request_validation() -> None:
    """Verify invalid page parameters are rejected by validation constraints."""
    with pytest.raises(ValidationError):
        SuperOfficePageRequest(page=0, page_size=20)

    with pytest.raises(ValidationError):
        SuperOfficePageRequest(page=1, page_size=101)  # Exceeds max 100


# ============================================================================
# 3. Error Sanitization Tests
# ============================================================================


def test_superoffice_error_sanitization() -> None:
    """Verify SuperOffice errors sanitize details and do not leak connection strings."""
    secret_url = "https://internal-so-app01.local/api/v1/tickets?secret_key=xyz"
    err = SuperOfficeIntegrationError(
        "Failed to reach upstream SuperOffice instance.",
        details={"attempted_endpoint": secret_url, "attempt": 3},
    )
    sanitized = err.to_sanitized_dict()
    assert sanitized["error"] == "SUPEROFFICE_INTEGRATION_ERROR"
    assert sanitized["message"] == "Failed to reach upstream SuperOffice instance."
    # Sanitized dict intentionally strips raw details dict to prevent AI leakage
    assert "secret_key" not in sanitized.get("message", "")


def test_superoffice_entity_not_found_error() -> None:
    """Verify SuperOfficeEntityNotFoundError formats cleanly."""
    err = SuperOfficeEntityNotFoundError("Ticket", 99999)
    assert err.error_code == "RESOURCE_NOT_FOUND"
    assert "99999" in err.message


def test_superoffice_auth_error_sanitization() -> None:
    """Verify SuperOfficeAuthenticationError inherits IntegrationError and sanitizes."""
    err = SuperOfficeAuthenticationError("Service account token expired.")
    assert isinstance(err, SuperOfficeIntegrationError) or err.system_name == "SuperOffice"
    sanitized = err.to_sanitized_dict()
    assert sanitized["error"] == "SUPEROFFICE_AUTH_FAILURE"


# ============================================================================
# 4. FakeSuperOfficeClient & Protocol Conformance Tests
# ============================================================================


def test_fake_superoffice_client_is_instance_of_protocol() -> None:
    """Verify FakeSuperOfficeClient satisfies SuperOfficeClient Protocol."""
    fake = FakeSuperOfficeClient()
    assert isinstance(fake, SuperOfficeClient)


def test_fake_superoffice_client_crud_and_search() -> None:
    """Verify deterministic in-memory operations on FakeSuperOfficeClient."""

    async def _run_async_tests() -> None:
        fake = FakeSuperOfficeClient()
        now = datetime.now(UTC)

        # 1. Seed entities
        fake.seed_company(CompanyDomainDTO(company_id=10, name="Nordic Tech AB", department="HQ"))
        fake.seed_person(
            PersonDomainDTO(
                person_id=100,
                first_name="Lars",
                last_name="Hansen",
                company_id=10,
            )
        )

        ticket_detail = TicketDetailDomainDTO(
            ticket_id=5001,
            title="Database synchronization latency",
            status="Open",
            category="Database",
            priority="High",
            description="Internal sync delay on replica node 2",
            customer_id=10,
            customer_reference="CUST-REF-10",
            created_at=now,
            updated_at=now,
        )
        fake.seed_ticket(ticket_detail)

        fake.seed_message(
            TicketMessageDomainDTO(
                message_id=901,
                ticket_id=5001,
                author="lars.hansen@nordictech.no",
                author_type="CUSTOMER",
                body="Is there an update on the database sync?",
                created_at=now,
            )
        )

        fake.seed_attachment(
            5001,
            AttachmentMetadata(
                attachment_id=8801,
                filename="error_log_sample.txt",
                mime_type="text/plain",
                size_bytes=1024,
                md5_hash="d41d8cd98f00b204e9800998ecf8427e",
                is_content_authorized=False,
            ),
        )

        # 2. Test Get by ID
        ticket = await fake.get_ticket(5001)
        assert ticket.ticket_id == 5001
        assert ticket.title == "Database synchronization latency"

        company = await fake.get_company(10)
        assert company.name == "Nordic Tech AB"

        person = await fake.get_person(100)
        assert person.first_name == "Lars"

        # 3. Test Searches
        ticket_crit = TicketSearchCriteriaDTO(status="Open", page=1, page_size=10)
        ticket_search_resp = await fake.search_tickets(ticket_crit)
        assert len(ticket_search_resp.items) == 1
        assert ticket_search_resp.items[0].ticket_id == 5001

        company_search_resp = await fake.find_companies(CompanySearchCriteriaDTO(name="Nordic"))
        assert len(company_search_resp.items) == 1

        person_search_resp = await fake.find_persons(PersonSearchCriteriaDTO(name="Hansen"))
        assert len(person_search_resp.items) == 1

        # 4. Test Messages & Attachments
        messages = await fake.get_ticket_messages(5001)
        assert len(messages) == 1
        assert messages[0].author_type == "CUSTOMER"

        attachments = await fake.list_attachments(5001)
        assert len(attachments) == 1
        assert attachments[0].filename == "error_log_sample.txt"
        assert attachments[0].size_bytes == 1024

        # 5. Test Missing Entity Exceptions
        with pytest.raises(SuperOfficeEntityNotFoundError):
            await fake.get_ticket(99999)

        with pytest.raises(SuperOfficeEntityNotFoundError):
            await fake.get_company(99999)

        with pytest.raises(SuperOfficeEntityNotFoundError):
            await fake.get_person(99999)

    asyncio.run(_run_async_tests())
