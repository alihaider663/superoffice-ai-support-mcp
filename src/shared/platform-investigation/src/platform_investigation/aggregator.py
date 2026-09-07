"""Generic multi-source evidence aggregation runtime."""

from collections.abc import Sequence
from datetime import UTC, datetime

from platform_core.errors import DomainValidationError
from platform_investigation.errors import (
    DuplicateEvidenceIdError,
    EvidenceProvenanceMismatchError,
)
from platform_investigation.interfaces import (
    EvidenceAggregator,
    OutcomeAwareEvidenceCollector,
)
from platform_investigation.models import (
    EvidenceAggregationResult,
    SourceCollectionResult,
    SourceCollectionStatus,
)
from platform_observability.logging import get_logger

logger = get_logger(__name__)


class EvidenceAggregatorEngine(EvidenceAggregator):
    """Deterministic, sequential multi-source evidence aggregation engine.

    Enforces:
    - Dependency-injected sequence of OutcomeAwareEvidenceCollector instances.
    - Deterministic sequential execution in registration order (no concurrency in Phase 3.2).
    - Exception isolation: unexpected collector failures are safely normalized to FAILED outcomes.
    - Fail-closed duplicate evidence ID detection (DuplicateEvidenceIdError).
    - Strict provenance verification between collector, outcome, and evidence items.
    - Single authoritative stored source of evidence (derived flattened view on result).
    - Zero plan/step mutation (decoupled from InvestigationOrchestrator lifecycle).
    """

    def __init__(
        self,
        collectors: Sequence[OutcomeAwareEvidenceCollector] = (),
    ) -> None:
        self._collectors: tuple[OutcomeAwareEvidenceCollector, ...] = tuple(collectors)

    async def aggregate(
        self,
        investigation_id: str,
        correlation_key: str,
    ) -> EvidenceAggregationResult:
        """Aggregate evidence across all registered outcome-aware collectors."""
        if not investigation_id or not investigation_id.strip():
            raise DomainValidationError(
                "investigation_id cannot be empty.",
                field_name="investigation_id",
            )
        if not correlation_key or not correlation_key.strip():
            raise DomainValidationError(
                "correlation_key cannot be empty.",
                field_name="correlation_key",
            )

        inv_id = investigation_id.strip()
        corr_key = correlation_key.strip()

        seen_evidence_ids: set[str] = set()
        source_outcomes: list[SourceCollectionResult] = []

        # Execute collectors deterministically in registration order
        for collector in self._collectors:
            source_type = collector.source_type
            try:
                outcome = await collector.collect(inv_id, corr_key)
            except Exception:
                # Safe structured error logging without leaking raw exception string or traceback
                logger.error(
                    "Unexpected exception during source evidence collection",
                    investigation_id=inv_id,
                    correlation_key=corr_key,
                    source_type=source_type.value,
                    error_code="SOURCE_EXECUTION_FAILED",
                )
                outcome = SourceCollectionResult(
                    source_type=source_type,
                    status=SourceCollectionStatus.FAILED,
                    evidence=(),
                    error_code="SOURCE_EXECUTION_FAILED",
                    error_message="An unexpected error occurred during source collection.",
                )

            # Validate source identity match
            if outcome.source_type != source_type:
                raise EvidenceProvenanceMismatchError(
                    expected_source=source_type.value,
                    actual_source=outcome.source_type.value,
                    evidence_id="[OUTCOME_SOURCE_MISMATCH]",
                )

            # Validate individual evidence items and fail closed on duplicate IDs
            for item in outcome.evidence:
                if item.source_type != source_type:
                    raise EvidenceProvenanceMismatchError(
                        expected_source=source_type.value,
                        actual_source=item.source_type.value,
                        evidence_id=item.evidence_id,
                    )
                if item.evidence_id in seen_evidence_ids:
                    raise DuplicateEvidenceIdError(evidence_id=item.evidence_id)

                seen_evidence_ids.add(item.evidence_id)

            source_outcomes.append(outcome)

        now = datetime.now(UTC)
        result = EvidenceAggregationResult(
            investigation_id=inv_id,
            correlation_key=corr_key,
            source_outcomes=tuple(source_outcomes),
            collected_at=now,
        )

        logger.info(
            "Evidence aggregation completed",
            investigation_id=inv_id,
            correlation_key=corr_key,
            total_sources=result.total_sources,
            successful_sources=result.successful_sources_count,
            evidence_count=len(result.evidence),
            has_failures=result.has_failures,
            has_partial_failures=result.has_partial_failures,
            all_sources_failed=result.all_sources_failed,
        )
        return result
