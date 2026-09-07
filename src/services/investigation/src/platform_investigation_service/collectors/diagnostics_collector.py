"""MSSQL Diagnostics evidence collector adapter.

Consumes a DiagnosticsServicePort to execute opt-in database health,
slow query, and deadlock searches, transforming results into
structured DiagnosticEvidence items.

Implements OutcomeAwareEvidenceCollector protocol for registration
with EvidenceAggregatorEngine.

Atomic source semantics:
- Zero selected operations: SUCCESS with empty evidence
- All selected operations succeed: SUCCESS with all mapped evidence
- ANY selected operation fails: FAILED with empty evidence (zero intermediate leak)

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
from platform_investigation_service.models import DiagnosticsSelectionDTO
from platform_investigation_service.ports import DiagnosticsServicePort
from platform_observability.logging import get_logger

logger = get_logger(__name__)


class DiagnosticsEvidenceCollector:
    """Concrete OutcomeAwareEvidenceCollector for MSSQL database diagnostics.

    Executes ONLY the diagnostic operations explicitly enabled in
    DiagnosticsSelectionDTO (all default to False/None).

    Operations:
    - include_database_health: get_database_health()
    - deadlock_criteria: find_deadlocks(deadlock_criteria)
    - slow_query_criteria: find_slow_queries(slow_query_criteria)

    Excluded from collector:
    - find_blocking_sessions
    - get_ticket_diagnostic_record
    - search_logs

    If zero operations are selected, returns SUCCESS with empty evidence (0 backend calls).
    If ANY operation fails, returns FAILED with empty evidence (atomic source semantics).
    """

    def __init__(
        self,
        service: DiagnosticsServicePort | None = None,
        *,
        selection: DiagnosticsSelectionDTO | None = None,
    ) -> None:
        self._service = service
        self._selection = selection or DiagnosticsSelectionDTO()

    @property
    def source_type(self) -> EvidenceSourceType:
        """System origin identifier for this collector."""
        return EvidenceSourceType.MSSQL_DIAGNOSTICS

    async def collect(
        self,
        investigation_id: str,
        correlation_key: str,
    ) -> SourceCollectionResult:
        """Collect MSSQL diagnostic evidence based on explicit opt-in selection."""
        _ = correlation_key
        has_selections = (
            self._selection.include_database_health
            or self._selection.deadlock_criteria is not None
            or self._selection.slow_query_criteria is not None
        )

        if not has_selections:
            logger.info("Diagnostics collector skipped: no operations selected")
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.SUCCESS,
                evidence=(),
            )

        if self._service is None:
            logger.error(
                "Diagnostics service not available",
                error_code="DIAGNOSTICS_SERVICE_UNAVAILABLE",
            )
            return SourceCollectionResult(
                source_type=self.source_type,
                status=SourceCollectionStatus.FAILED,
                evidence=(),
                error_code="DIAGNOSTICS_SERVICE_UNAVAILABLE",
                error_message="Diagnostics service port is not configured.",
            )

        evidence_items: list[DiagnosticEvidence] = []
        now = datetime.now(UTC)

        # 1. Database health check
        if self._selection.include_database_health:
            try:
                health = await self._service.get_database_health()
            except Exception:
                logger.error(
                    "Database health check failed",
                    error_code="DIAG_HEALTH_FAILED",
                )
                return SourceCollectionResult(
                    source_type=self.source_type,
                    status=SourceCollectionStatus.FAILED,
                    evidence=(),
                    error_code="DIAGNOSTICS_RETRIEVAL_FAILED",
                    error_message="An unexpected error occurred retrieving MSSQL diagnostics data.",
                )

            ts = health.collected_at if isinstance(health.collected_at, datetime) else now
            evidence_items.append(
                DiagnosticEvidence(
                    evidence_id=f"diag:health:{investigation_id}",
                    source_type=self.source_type,
                    title="Database health observation",
                    timestamp=ts,
                    data={
                        "is_healthy": health.is_healthy,
                        "active_connections": health.active_connections,
                        "latency_ms": health.latency_ms,
                    },
                    tags=("diagnostics", "database", "health"),
                )
            )

        # 2. Deadlock search
        if self._selection.deadlock_criteria is not None:
            try:
                deadlock_result = await self._service.find_deadlocks(
                    self._selection.deadlock_criteria
                )
            except Exception:
                logger.error(
                    "Deadlock search failed",
                    error_code="DIAG_DEADLOCK_FAILED",
                )
                return SourceCollectionResult(
                    source_type=self.source_type,
                    status=SourceCollectionStatus.FAILED,
                    evidence=(),
                    error_code="DIAGNOSTICS_RETRIEVAL_FAILED",
                    error_message="An unexpected error occurred retrieving MSSQL diagnostics data.",
                )

            for deadlock_item in deadlock_result.items:
                deadlock_ts = (
                    deadlock_item.occurred_at
                    if isinstance(deadlock_item.occurred_at, datetime)
                    else now
                )
                evidence_items.append(
                    DiagnosticEvidence(
                        evidence_id=f"diag:deadlock:{deadlock_item.deadlock_id}",
                        source_type=self.source_type,
                        title="Database deadlock observation",
                        timestamp=deadlock_ts,
                        data={
                            "deadlock_id": deadlock_item.deadlock_id,
                            "victim_session_id": deadlock_item.victim_session_id,
                            "participating_session_count": (
                                deadlock_item.participating_session_count
                            ),
                        },
                        tags=("diagnostics", "database", "deadlock"),
                        correlation_references=(
                            CorrelationReference(
                                namespace="deadlock_id",
                                value=deadlock_item.deadlock_id,
                            ),
                        ),
                    )
                )

        # 3. Slow query search
        if self._selection.slow_query_criteria is not None:
            try:
                slow_query_result = await self._service.find_slow_queries(
                    self._selection.slow_query_criteria
                )
            except Exception:
                logger.error(
                    "Slow query search failed",
                    error_code="DIAG_SLOW_QUERY_FAILED",
                )
                return SourceCollectionResult(
                    source_type=self.source_type,
                    status=SourceCollectionStatus.FAILED,
                    evidence=(),
                    error_code="DIAGNOSTICS_RETRIEVAL_FAILED",
                    error_message="An unexpected error occurred retrieving MSSQL diagnostics data.",
                )

            for idx, slow_item in enumerate(slow_query_result.items):
                query_ts = (
                    slow_item.last_execution_time
                    if isinstance(slow_item.last_execution_time, datetime)
                    else now
                )
                evidence_items.append(
                    DiagnosticEvidence(
                        evidence_id=f"diag:slow_query:{slow_item.query_hash}:{idx}",
                        source_type=self.source_type,
                        title="Slow query observation",
                        timestamp=query_ts,
                        data={
                            "query_hash": slow_item.query_hash,
                            "duration_ms": slow_item.duration_ms,
                            "cpu_time_ms": slow_item.cpu_time_ms,
                            "logical_reads": slow_item.logical_reads,
                            "execution_count": slow_item.execution_count,
                        },
                        tags=("diagnostics", "database", "slow_query"),
                        correlation_references=(
                            CorrelationReference(
                                namespace="query_hash",
                                value=slow_item.query_hash,
                            ),
                        ),
                    )
                )

        logger.info(
            "Diagnostics evidence collected",
            evidence_count=len(evidence_items),
        )

        return SourceCollectionResult(
            source_type=self.source_type,
            status=SourceCollectionStatus.SUCCESS,
            evidence=tuple(evidence_items),
            collected_at=now,
        )
