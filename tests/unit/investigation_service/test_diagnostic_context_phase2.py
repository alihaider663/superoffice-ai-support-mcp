"""Unit tests verifying Phase 2 sanitized diagnostic context in investigate_incident."""

from datetime import UTC, datetime

import pytest

from investigation_mcp.contracts.dtos import TicketObservationDTO
from investigation_mcp.contracts.mappers import InvestigationResponseMapper
from platform_investigation.models import (
    DiagnosticEvidence,
    EvidenceSourceType,
)
from platform_investigation_service.collectors.superoffice_collector import (
    SuperOfficeEvidenceCollector,
)
from so_mcp.contracts.dtos import MinimizedTicketDetailDTO


class _FakeSuperOfficePort:
    def __init__(self, ticket: MinimizedTicketDetailDTO) -> None:
        self._ticket = ticket

    async def get_ticket(self, ticket_id: int) -> MinimizedTicketDetailDTO:
        _ = ticket_id
        return self._ticket


@pytest.mark.asyncio
async def test_superoffice_evidence_collector_includes_sanitized_diagnostic_context() -> None:
    """Verify SuperOfficeEvidenceCollector preserves title, description, and customer ref."""
    now = datetime.now(UTC)
    desc = "Customer reports HTTP 504 when attempting to save recurring appointment."
    ticket = MinimizedTicketDetailDTO(
        ticket_id=90210,
        title="504 Gateway Timeout during Appointment Save",
        status="Open",
        category="Application Server",
        priority="Critical",
        sanitized_description=desc,
        sanitized_customer_reference="CUST-GLOBAL-CORP",
        assigned_agent_id="AGENT-L2-SECRET",
        created_at=now,
    )
    port = _FakeSuperOfficePort(ticket=ticket)
    collector = SuperOfficeEvidenceCollector(port, ticket_id=90210)

    result = await collector.collect("inv-test-phase2", "test-corr-key")

    assert len(result.evidence) == 1
    evidence = result.evidence[0]

    # Verify diagnostic context fields are present
    assert evidence.data["ticket_id"] == 90210
    assert evidence.data["title"] == "504 Gateway Timeout during Appointment Save"
    assert evidence.data["status"] == "Open"
    assert evidence.data["category"] == "Application Server"
    assert evidence.data["priority"] == "Critical"
    assert evidence.data["sanitized_description"] == desc
    assert evidence.data["sanitized_customer_reference"] == "CUST-GLOBAL-CORP"

    # Verify internal agent ID is still excluded for privacy
    assert "assigned_agent_id" not in evidence.data


def test_investigation_response_mapper_wire_preserves_ticket_diagnostic_context() -> None:
    """Verify InvestigationResponseMapper maps diagnostic context fields to public wire DTO."""
    now = datetime.now(UTC)
    desc = "Customer reports HTTP 504 when attempting to save recurring appointment."
    evidence = DiagnosticEvidence(
        evidence_id="so:ticket:90210",
        source_type=EvidenceSourceType.SUPEROFFICE_CRM,
        title="SuperOffice ticket observation",
        timestamp=now,
        data={
            "ticket_id": 90210,
            "title": "504 Gateway Timeout during Appointment Save",
            "status": "Open",
            "category": "Application Server",
            "priority": "Critical",
            "sanitized_description": desc,
            "sanitized_customer_reference": "CUST-GLOBAL-CORP",
        },
        tags=("crm", "ticket", "superoffice"),
    )

    src, obs = InvestigationResponseMapper._map_observation(evidence)

    assert src == "superoffice_crm"
    assert isinstance(obs, TicketObservationDTO)
    assert obs.ticket_id == 90210
    assert obs.title == "504 Gateway Timeout during Appointment Save"
    assert obs.status == "Open"
    assert obs.category == "Application Server"
    assert obs.priority == "Critical"
    assert obs.sanitized_description == desc
    assert obs.sanitized_customer_reference == "CUST-GLOBAL-CORP"
