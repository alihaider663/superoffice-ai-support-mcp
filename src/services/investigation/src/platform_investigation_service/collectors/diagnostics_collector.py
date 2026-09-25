"""MSSQL Diagnostics evidence collector adapter.

Consumes a DiagnosticsServicePort to execute opt-in database health,
slow query, deadlock searches, ticket database diagnostic telemetry,
and active blocking session checks, transforming results into
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
    - include_ticket_diagnostic: get_ticket_diagnostic_record(ticket_id)
    - include_blocking_sessions: find_blocking_sessions()

    If zero operations are selected, returns SUCCESS with empty evidence (0 backend calls).
    If ANY operation fails, returns FAILED with empty evidence (atomic source semantics).
    """

    def __init__(
        self,
        service: DiagnosticsServicePort | None = None,
        *,
        selection: DiagnosticsSelectionDTO | None = None,
        ticket_id: int | None = None,
    ) -> None:
        self._service = service
        self._selection = selection or DiagnosticsSelectionDTO()
        self._ticket_id = ticket_id

    @property
    def source_type(self) -> EvidenceSourceType:
        """System origin identifier for this collector."""
        return EvidenceSourceType.MSSQL_DIAGNOSTICS

    async def collect(  # noqa: PLR0912
        self,
        investigation_id: str,
        correlation_key: str,
    ) -> SourceCollectionResult:
        """Collect MSSQL diagnostic evidence based on explicit opt-in selection."""
        _ = correlation_key
        has_ticket_diag = self._selection.include_ticket_diagnostic and self._ticket_id is not None
        has_selections = (
            self._selection.include_database_health
            or self._selection.deadlock_criteria is not None
            or self._selection.slow_query_criteria is not None
            or has_ticket_diag
            or self._selection.include_blocking_sessions
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

        now = datetime.now(UTC)

        tasks: list[Any] = []
        # 1. Health
        if self._selection.include_database_health:
            tasks.append(self._service.get_database_health())
        else:
            tasks.append(None)

        # 2. Deadlocks
        if self._selection.deadlock_criteria is not None:
            tasks.append(self._service.find_deadlocks(self._selection.deadlock_criteria))
        else:
            tasks.append(None)

        # 3. Slow queries
        if self._selection.slow_query_criteria is not None:
            tasks.append(self._service.find_slow_queries(self._selection.slow_query_criteria))
        else:
            tasks.append(None)

        # 4. Ticket diagnostics
        if has_ticket_diag and self._ticket_id is not None:
            tasks.append(self._service.get_ticket_diagnostic_record(self._ticket_id))
        else:
            tasks.append(None)

        # 5. Blocking sessions
        if self._selection.include_blocking_sessions:
            tasks.append(self._service.find_blocking_sessions())
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

        health_res, deadlock_res, slow_query_res, ticket_diag_res, blocking_res = raw_results

        err_result = self._check_task_errors(
            health_res, deadlock_res, slow_query_res, ticket_diag_res, blocking_res
        )
        if err_result is not None:
            return err_result

        evidence_items = self._map_results(
            investigation_id,
            now,
            health_res,
            deadlock_res,
            slow_query_res,
            ticket_diag_res,
            blocking_res,
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
        ticket_diag_res: Any,
        blocking_res: Any,
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
        if isinstance(ticket_diag_res, Exception):
            logger.error("Ticket diagnostics failed", error_code="DIAG_TICKET_FAILED")
            return self._build_failure_result()
        if isinstance(blocking_res, Exception):
            logger.error("Blocking sessions check failed", error_code="DIAG_BLOCKING_FAILED")
            return self._build_failure_result()
        return None

    def _map_results(  # noqa: PLR0912, PLR0917
        self,
        investigation_id: str,
        now: datetime,
        health_res: Any,
        deadlock_res: Any,
        slow_query_res: Any,
        ticket_diag_res: Any,
        blocking_res: Any,
    ) -> list[DiagnosticEvidence]:
        items: list[DiagnosticEvidence] = []
        if health_res is not None:
            ts = health_res.collected_at if isinstance(health_res.collected_at, datetime) else now
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
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
                if dlk_ts.tzinfo is None:
                    dlk_ts = dlk_ts.replace(tzinfo=UTC)
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
                    sq.last_execution_time if isinstance(sq.last_execution_time, datetime) else now
                )
                if sq_ts.tzinfo is None:
                    sq_ts = sq_ts.replace(tzinfo=UTC)
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

        if ticket_diag_res is not None:
            td_ts = (
                ticket_diag_res.last_activity_time
                if isinstance(ticket_diag_res.last_activity_time, datetime)
                else now
            )
            if td_ts.tzinfo is None:
                td_ts = td_ts.replace(tzinfo=UTC)
            items.append(
                DiagnosticEvidence(
                    evidence_id=f"diag:ticket_diagnostic:{ticket_diag_res.ticket_id}",
                    source_type=self.source_type,
                    title="Ticket database diagnostic observation",
                    timestamp=td_ts,
                    data={
                        "ticket_id": ticket_diag_res.ticket_id,
                        "has_db_activity": ticket_diag_res.has_db_activity,
                        "recent_error_count": ticket_diag_res.recent_error_count,
                        "last_activity_time": ticket_diag_res.last_activity_time,
                        "diagnostic_summary": ticket_diag_res.diagnostic_summary,
                    },
                    tags=("diagnostics", "database", "ticket_diagnostic"),
                    correlation_references=(
                        CorrelationReference(
                            namespace="ticket",
                            value=str(ticket_diag_res.ticket_id),
                        ),
                    ),
                )
            )

        if blocking_res is not None:
            for idx, bs in enumerate(blocking_res.items):
                bs_ts = bs.detected_at if isinstance(bs.detected_at, datetime) else now
                if bs_ts.tzinfo is None:
                    bs_ts = bs_ts.replace(tzinfo=UTC)
                items.append(
                    DiagnosticEvidence(
                        evidence_id=f"diag:blocking:{bs.blocking_session_id}:{bs.blocked_session_id}:{idx}",
                        source_type=self.source_type,
                        title="Active blocking session observation",
                        timestamp=bs_ts,
                        data={
                            "blocking_session_id": bs.blocking_session_id,
                            "blocked_session_id": bs.blocked_session_id,
                            "wait_duration_ms": bs.wait_duration_ms,
                            "wait_type": bs.wait_type,
                        },
                        tags=("diagnostics", "database", "blocking_session"),
                        correlation_references=(
                            CorrelationReference(
                                namespace="session_id",
                                value=str(bs.blocking_session_id),
                            ),
                            CorrelationReference(
                                namespace="session_id",
                                value=str(bs.blocked_session_id),
                            ),
                        ),
                    )
                )

        return items
