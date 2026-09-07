"""Application logs evidence collector adapter.

Registered as APPLICATION_LOGS source. Returns BLOCKED
status because the logging backend is not yet configured (BLK-2B3-02).

Produces zero fake evidence and performs zero backend calls.

Import policy: NO server runtime/adapter imports.
"""

from platform_investigation.models import (
    EvidenceSourceType,
    SourceCollectionResult,
    SourceCollectionStatus,
)
from platform_observability.logging import get_logger

logger = get_logger(__name__)


class DiagnosticLogsEvidenceCollector:
    """Concrete OutcomeAwareEvidenceCollector for Application Logs (BLOCKED source).

    Phase 2B logging backend is not yet configured.
    This collector registers the BLOCKED source outcome deterministically.
    """

    @property
    def source_type(self) -> EvidenceSourceType:
        """System origin identifier for this collector."""
        return EvidenceSourceType.APPLICATION_LOGS

    async def collect(
        self,
        investigation_id: str,
        correlation_key: str,
    ) -> SourceCollectionResult:
        """Return BLOCKED status with safe generic code and message."""
        _ = correlation_key
        _ = investigation_id
        logger.info("Logs collector: BLOCKED")

        return SourceCollectionResult(
            source_type=self.source_type,
            status=SourceCollectionStatus.BLOCKED,
            evidence=(),
            error_code="DIAGNOSTIC_LOGS_BLOCKED",
            error_message="Application logging backend is blocked or not configured.",
        )


# Backward-compatible alias
LogsEvidenceCollector = DiagnosticLogsEvidenceCollector
