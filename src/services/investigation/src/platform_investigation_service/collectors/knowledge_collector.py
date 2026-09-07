"""Knowledge base evidence collector adapter.

Registered as KNOWLEDGE_BASE source. Returns NOT_CONFIGURED
status because the Supabase knowledge backend schema is not yet
configured (BLK-2B4-01).

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


class KnowledgeEvidenceCollector:
    """Concrete OutcomeAwareEvidenceCollector for Knowledge Base (BLOCKED source).

    Phase 2B knowledge backend (Supabase) is not yet configured.
    This collector registers the NOT_CONFIGURED source outcome deterministically.
    """

    @property
    def source_type(self) -> EvidenceSourceType:
        """System origin identifier for this collector."""
        return EvidenceSourceType.KNOWLEDGE_BASE

    async def collect(
        self,
        investigation_id: str,
        correlation_key: str,
    ) -> SourceCollectionResult:
        """Return NOT_CONFIGURED status with safe generic code and message."""
        _ = correlation_key
        _ = investigation_id
        logger.info("Knowledge collector: NOT_CONFIGURED")

        return SourceCollectionResult(
            source_type=self.source_type,
            status=SourceCollectionStatus.NOT_CONFIGURED,
            evidence=(),
            error_code="KNOWLEDGE_BASE_NOT_CONFIGURED",
            error_message="Knowledge store backend is not configured.",
        )
