"""Unit tests for SuperOfficeEvidenceCollector."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from platform_investigation.models import (
    EvidenceSourceType,
    SourceCollectionStatus,
)
from platform_investigation_service.collectors.superoffice_collector import (
    SuperOfficeEvidenceCollector,
)
from so_mcp.contracts.dtos import MinimizedTicketDetailDTO


class _FakeSuperOfficePort:
    """Fake SuperOfficeServicePort for testing."""

    def __init__(
        self,
        ticket: MinimizedTicketDetailDTO | None = None,
        *,
        raise_error: bool = False,
    ) -> None:
        self._ticket = ticket or MinimizedTicketDetailDTO(
            ticket_id=10209,
            title="Login timeout on production",
            status="Open",
            category="Technical",
            priority="High",
            sanitized_description="User reports login failures.",
            sanitized_customer_reference="CUST-REF-100",
            assigned_agent_id="AGENT-42",
            created_at=datetime.now(UTC),
        )
        self._raise_error = raise_error
        self.get_ticket_calls: list[int] = []

    async def get_ticket(self, ticket_id: int) -> MinimizedTicketDetailDTO:
        self.get_ticket_calls.append(ticket_id)
        if self._raise_error:
            raise RuntimeError("Simulated SuperOffice failure: secret host 192.168.1.50")
        return self._ticket


class TestSuperOfficeEvidenceCollector:
    """Tests for SuperOfficeEvidenceCollector."""

    def test_source_type_is_superoffice_crm(self) -> None:
        port = _FakeSuperOfficePort()
        collector = SuperOfficeEvidenceCollector(port)
        assert collector.source_type == EvidenceSourceType.SUPEROFFICE_CRM

    @pytest.mark.asyncio
    async def test_collect_with_ticket_id_none_makes_zero_backend_calls(self) -> None:
        port = _FakeSuperOfficePort()
        collector = SuperOfficeEvidenceCollector(port, ticket_id=None)

        result = await collector.collect("inv-001", "opaque-corr-key")

        assert result.status == SourceCollectionStatus.SUCCESS
        assert result.source_type == EvidenceSourceType.SUPEROFFICE_CRM
        assert len(result.evidence) == 0
        assert len(port.get_ticket_calls) == 0

    @pytest.mark.asyncio
    async def test_collect_with_ticket_id_makes_exactly_one_call(self) -> None:
        port = _FakeSuperOfficePort()
        collector = SuperOfficeEvidenceCollector(port, ticket_id=10209)

        result = await collector.collect("inv-002", "opaque-corr-key")

        assert result.status == SourceCollectionStatus.SUCCESS
        assert len(result.evidence) == 1
        assert port.get_ticket_calls == [10209]

    @pytest.mark.asyncio
    async def test_evidence_mapping_and_data_minimization(self) -> None:
        """Verify strict data minimization: no description, customer ref, agent ID, or title."""
        now = datetime.now(UTC)
        ticket = MinimizedTicketDetailDTO(
            ticket_id=42,
            title="Secret Free Text Customer Subject",
            status="In Progress",
            category="Billing",
            priority="Medium",
            sanitized_description="Sensitive description text",
            sanitized_customer_reference="CUST-SECRET-999",
            assigned_agent_id="AGENT-SECRET-007",
            created_at=now,
        )
        port = _FakeSuperOfficePort(ticket=ticket)
        collector = SuperOfficeEvidenceCollector(port, ticket_id=42)

        result = await collector.collect("inv-003", "opaque-key")

        assert len(result.evidence) == 1
        evidence = result.evidence[0]

        # Single-execution evidence ID
        assert evidence.evidence_id == "so:ticket:42"
        # Safe fixed generic title
        assert evidence.title == "SuperOffice ticket observation"
        assert evidence.source_type == EvidenceSourceType.SUPEROFFICE_CRM

        # Controlled tags
        assert evidence.tags == ("crm", "ticket", "superoffice")

        # Correlation reference
        assert len(evidence.correlation_references) == 1
        ref = evidence.correlation_references[0]
        assert ref.namespace == "ticket"
        assert ref.value == "42"

        # Structured diagnostic data payload with sanitized context
        assert evidence.data == {
            "ticket_id": 42,
            "title": "Secret Free Text Customer Subject",
            "status": "In Progress",
            "category": "Billing",
            "priority": "Medium",
            "sanitized_description": "Sensitive description text",
            "sanitized_customer_reference": "CUST-SECRET-999",
        }
        assert "assigned_agent_id" not in evidence.data

    @pytest.mark.asyncio
    async def test_collect_failed_on_port_exception(self) -> None:
        port = _FakeSuperOfficePort(raise_error=True)
        collector = SuperOfficeEvidenceCollector(port, ticket_id=10209)

        result = await collector.collect("inv-004", "opaque-key")

        assert result.status == SourceCollectionStatus.FAILED
        assert result.error_code == "SUPEROFFICE_RETRIEVAL_FAILED"
        msg = "An unexpected error occurred retrieving SuperOffice ticket data."
        assert result.error_message == msg
        assert len(result.evidence) == 0

    @pytest.mark.asyncio
    async def test_collect_failed_when_service_is_none_with_ticket_id(self) -> None:
        collector = SuperOfficeEvidenceCollector(service=None, ticket_id=10209)

        result = await collector.collect("inv-005", "opaque-key")

        assert result.status == SourceCollectionStatus.FAILED
        assert result.error_code == "SUPEROFFICE_SERVICE_UNAVAILABLE"
        assert len(result.evidence) == 0

    @pytest.mark.asyncio
    async def test_default_confidence_score_applied(self) -> None:
        port = _FakeSuperOfficePort()
        collector = SuperOfficeEvidenceCollector(port, ticket_id=10209)

        result = await collector.collect("inv-006", "opaque-key")

        # Default confidence score from DiagnosticEvidence model (1.0) applies
        assert result.evidence[0].confidence_score == 1.0

    @pytest.mark.asyncio
    async def test_mapping_failure_propagates_validation_error(self) -> None:
        """Integrity failure during model construction must propagate and NOT convert to FAILED."""
        # Create a mock ticket object whose values cause model validation failure
        mock_ticket = MagicMock()
        # Empty string causes empty CorrelationReference value validation failure
        mock_ticket.ticket_id = ""
        mock_ticket.status = "Open"
        mock_ticket.category = "Technical"
        mock_ticket.priority = "High"
        mock_ticket.created_at = datetime.now(UTC)

        mock_port = MagicMock()
        mock_port.get_ticket = AsyncMock(return_value=mock_ticket)

        collector = SuperOfficeEvidenceCollector(mock_port, ticket_id=10209)

        with pytest.raises(ValidationError):
            await collector.collect("inv-map-fail", "opaque-key")

    @pytest.mark.asyncio
    async def test_error_logging_contains_no_sensitive_metadata_or_investigation_id(self) -> None:
        """Collector error logs must not contain investigation_id, ticket_id, or raw exception."""
        port = _FakeSuperOfficePort(raise_error=True)
        collector = SuperOfficeEvidenceCollector(port, ticket_id=999888)

        patch_target = "platform_investigation_service.collectors.superoffice_collector.logger"
        with patch(patch_target) as mock_logger:
            result = await collector.collect("secret-inv-id-777", "secret-corr-key-888")

            assert result.status == SourceCollectionStatus.FAILED
            mock_logger.error.assert_called_once()
            call_args, call_kwargs = mock_logger.error.call_args

            # Check message
            assert "SuperOffice ticket retrieval failed" in call_args[0]
            # Check kwargs
            assert call_kwargs.get("error_code") == "SUPEROFFICE_RETRIEVAL_FAILED"
            assert "investigation_id" not in call_kwargs
            assert "ticket_id" not in call_kwargs
            assert "secret-inv-id-777" not in str(call_kwargs)
            assert "999888" not in str(call_kwargs)
            assert "secret host" not in str(call_kwargs)
