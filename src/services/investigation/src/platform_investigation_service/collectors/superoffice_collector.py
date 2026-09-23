"""SuperOffice CRM evidence collector adapter.

Consumes a SuperOfficeServicePort to retrieve minimized ticket detail
and transform it into structured DiagnosticEvidence items.

Implements OutcomeAwareEvidenceCollector protocol for registration
with EvidenceAggregatorEngine.

Import policy: NO server runtime/adapter imports. Uses port protocol and contract DTOs only.
"""

from datetime import UTC, datetime

from platform_investigation.models import (
    CorrelationReference,
    DiagnosticEvidence,
    EvidenceSourceType,
    SourceCollectionResult,
    SourceCollectionStatus,
)
from platform_investigation_service.ports import SuperOfficeServicePort
from platform_observability.logging import get_logger

logger = get_logger(__name__)


class SuperOfficeEvidenceCollector:
    """Concrete OutcomeAwareEvidenceCollector for SuperOffice CRM ticket data.

    Criteria gating:
    - If ticket_id is None: returns SUCCESS with evidence=() and 0 backend calls.
    - If ticket_id is provided: executes exactly one get_ticket(ticket_id) call.

    Data minimization:
    - Structured diagnostic metadata: ticket_id, title, status, category, priority,
      sanitized_description, sanitized_customer_reference.
    - Title in evidence envelope is a safe fixed generic value: 'SuperOffice ticket observation'.
    - Tags are controlled fixed values: ('crm', 'ticket', 'superoffice').
    - NO internal agent ID or direct raw PII in evidence data.
    - Zero attachment access.
    """

    def __init__(
        self,
        service: SuperOfficeServicePort | None = None,
        *,
        ticket_id: int | None = None,
    ) -> None:
        self._service = service
        self._ticket_id = ticket_id

    @property
    def source_type(self) -> EvidenceSourceType:
        """System origin identifier for this collector."""
        return EvidenceSourceType.SUPEROFFICE_CRM

    async def collect(
        self,
        investigation_id: str,
        correlation_key: str,
    ) -> SourceCollectionResult:
        """Collect ticket evidence from SuperOffice CRM service."""
        _ = correlation_key
        _ = investigation_id
        if self._ticket_id is None:
            logger.info("SuperOffice collector skipped: no ticket_id specified")
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.SUCCESS,
                evidence=(),
            )

        if self._service is None:
            logger.error(
                "SuperOffice service not available",
                error_code="SUPEROFFICE_SERVICE_UNAVAILABLE",
            )
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.FAILED,
                evidence=(),
                error_code="SUPEROFFICE_SERVICE_UNAVAILABLE",
                error_message="SuperOffice service port is not configured.",
            )

        try:
            ticket = await self._service.get_ticket(self._ticket_id)
        except Exception:
            logger.error(
                "SuperOffice ticket retrieval failed",
                error_code="SUPEROFFICE_RETRIEVAL_FAILED",
            )
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.FAILED,
                evidence=(),
                error_code="SUPEROFFICE_RETRIEVAL_FAILED",
                error_message="An unexpected error occurred retrieving SuperOffice ticket data.",
            )

        now = datetime.now(UTC)
        evidence_id = f"so:ticket:{ticket.ticket_id}"

        evidence = DiagnosticEvidence(
            evidence_id=evidence_id,
            source_type=self.source_type,
            title="SuperOffice ticket observation",
            timestamp=ticket.created_at if isinstance(ticket.created_at, datetime) else now,
            data={
                "ticket_id": ticket.ticket_id,
                "title": ticket.title,
                "status": ticket.status,
                "category": ticket.category,
                "priority": ticket.priority,
                "sanitized_description": ticket.sanitized_description,
                "sanitized_customer_reference": ticket.sanitized_customer_reference,
            },
            tags=("crm", "ticket", "superoffice"),
            correlation_references=(
                CorrelationReference(namespace="ticket", value=str(ticket.ticket_id)),
            ),
        )

        logger.info(
            "SuperOffice evidence collected",
            evidence_count=1,
        )

        return SourceCollectionResult(
            source_type=self.source_type,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(evidence,),
            collected_at=now,
        )
