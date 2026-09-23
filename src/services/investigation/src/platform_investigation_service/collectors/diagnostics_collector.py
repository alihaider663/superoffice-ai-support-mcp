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

import asyncio
from datetime import UTC, datetime
from typing import Any

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

        tasks: list[Any] = []
        if self._selection.include_database_health:
            tasks.append(self._service.get_database_health())
        else:
            tasks.append(None)

        if self._selection.deadlock_criteria is not None:
            tasks.append(self._service.find_deadlocks(self._selection.deadlock_criteria))
        else:
            tasks.append(None)

        if self._selection.slow_query_criteria is not None:
            tasks.append(self._service.find_slow_queries(self._selection.slow_query_criteria))
        else:
            tasks.append(None)

        async def _run_optional_task(task_coro: Any) -> Any:
            if task_coro is None:
                return None
            return await task_coro

        raw_results = await asyncio.gather(
            *[_run_optional_task(t) for t in tasks],
            return_exceptions=True,
        )

        health_res, deadlock_res, slow_query_res = raw_results

        err_result = self._check_task_errors(health_res, deadlock_res, slow_query_res)
        if err_result is not None:
            return err_result

        evidence_items = self._map_results(
            investigation_id, now, health_res, deadlock_res, slow_query_res
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

    def _build_failure_result(self) -> SourceCollectionResult:
        return SourceCollectionResult(
            source_type=self.source_type,
            status=SourceCollectionStatus.FAILED,
            evidence=(),
            error_code="DIAGNOSTICS_RETRIEVAL_FAILED",
            error_message="An unexpected error occurred retrieving MSSQL diagnostics data.",
        )

    def _check_task_errors(
        self,
        health_res: Any,
        deadlock_res: Any,
        slow_query_res: Any,
    ) -> SourceCollectionResult | None:
        if isinstance(health_res, Exception):
            logger.error("Database health check failed", error_code="DIAG_HEALTH_FAILED")
            return self._build_failure_result()
        if isinstance(deadlock_res, Exception):
            logger.error("Deadlock search failed", error_code="DIAG_DEADLOCK_FAILED")
            return self._build_failure_result()
        if isinstance(slow_query_res, Exception):
            logger.error("Slow query search failed", error_code="DIAG_SLOW_QUERY_FAILED")
            return self._build_failure_result()
        return None

    def _map_results(
        self,
        investigation_id: str,
        now: datetime,
        health_res: Any,
        deadlock_res: Any,
        slow_query_res: Any,
    ) -> list[DiagnosticEvidence]:
        items: list[DiagnosticEvidence] = []
        if health_res is not None:
            ts = health_res.collected_at if isinstance(health_res.collected_at, datetime) else now
            items.append(
                DiagnosticEvidence(
                    evidence_id=f"diag:health:{investigation_id}",
                    source_type=self.source_type,
                    title="Database health observation",
                    timestamp=ts,
                    data={
                        "is_healthy": health_res.is_healthy,
                        "active_connections": health_res.active_connections,
                        "latency_ms": health_res.latency_ms,
                    },
                    tags=("diagnostics", "database", "health"),
                )
            )

        if deadlock_res is not None:
            for dlk in deadlock_res.items:
                dlk_ts = dlk.occurred_at if isinstance(dlk.occurred_at, datetime) else now
                items.append(
                    DiagnosticEvidence(
                        evidence_id=f"diag:deadlock:{dlk.deadlock_id}",
                        source_type=self.source_type,
                        title="Database deadlock observation",
                        timestamp=dlk_ts,
                        data={
                            "deadlock_id": dlk.deadlock_id,
                            "victim_session_id": dlk.victim_session_id,
                            "participating_session_count": dlk.participating_session_count,
                        },
                        tags=("diagnostics", "database", "deadlock"),
                        correlation_references=(
                            CorrelationReference(
                                namespace="deadlock_id",
                                value=dlk.deadlock_id,
                            ),
                        ),
                    )
                )

        if slow_query_res is not None:
            for idx, sq in enumerate(slow_query_res.items):
                sq_ts = (
                    sq.last_execution_time
                    if isinstance(sq.last_execution_time, datetime)
                    else now
                )
                items.append(
                    DiagnosticEvidence(
                        evidence_id=f"diag:slow_query:{sq.query_hash}:{idx}",
                        source_type=self.source_type,
                        title="Slow query observation",
                        timestamp=sq_ts,
                        data={
                            "query_hash": sq.query_hash,
                            "duration_ms": sq.duration_ms,
                            "cpu_time_ms": sq.cpu_time_ms,
                            "logical_reads": sq.logical_reads,
                            "execution_count": sq.execution_count,
                        },
                        tags=("diagnostics", "database", "slow_query"),
                        correlation_references=(
                            CorrelationReference(
                                namespace="query_hash",
                                value=sq.query_hash,
                            ),
                        ),
                    )
                )

        return items
