"""Diagnostics Application Service coordinating database and log diagnostics."""

from diag_mcp.contracts.dtos import (
    BlockingSessionCriteriaDTO,
    BlockingSessionDomainDTO,
    BoundedDiagnosticResultDTO,
    DatabaseHealthDomainDTO,
    DeadlockCriteriaDTO,
    DeadlockDomainDTO,
    SlowQueryCriteriaDTO,
    SlowQueryDomainDTO,
    TicketDiagnosticCriteriaDTO,
    TicketDiagnosticRecordDomainDTO,
)
from diag_mcp.contracts.interfaces import DiagnosticRepository
from platform_security.sanitization import RecursiveOutputSanitizer


class DiagnosticsApplicationService:
    """Application Service orchestrating read-only MSSQL diagnostics and output sanitization."""

    def __init__(
        self,
        repository: DiagnosticRepository,
        sanitizer: RecursiveOutputSanitizer | None = None,
    ) -> None:
        self._repository = repository
        self._sanitizer = sanitizer or RecursiveOutputSanitizer()

    def _sanitize_string(self, text: str) -> str:
        """Sanitize a free-text string using RecursiveOutputSanitizer."""
        if not text:
            return text
        result = self._sanitizer.pii_filter.redact(text)
        return result.sanitized_text

    async def get_database_health(self) -> DatabaseHealthDomainDTO:
        """Fetch sanitized database health status."""
        health = await self._repository.get_database_health()
        return DatabaseHealthDomainDTO(
            is_healthy=health.is_healthy,
            status_summary=self._sanitize_string(health.status_summary),
            active_connections=health.active_connections,
            latency_ms=health.latency_ms,
            collected_at=health.collected_at,
        )

    async def find_slow_queries(
        self, criteria: SlowQueryCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[SlowQueryDomainDTO]:
        """Find slow queries with bounded results and sanitized summary text."""
        result = await self._repository.find_slow_queries(criteria)
        sanitized_items = [
            SlowQueryDomainDTO(
                query_hash=item.query_hash,
                duration_ms=item.duration_ms,
                cpu_time_ms=item.cpu_time_ms,
                logical_reads=item.logical_reads,
                execution_count=item.execution_count,
                last_execution_time=item.last_execution_time,
                summary=self._sanitize_string(item.summary),
            )
            for item in result.items
        ]
        return BoundedDiagnosticResultDTO[SlowQueryDomainDTO](
            items=tuple(sanitized_items),
            returned_count=len(sanitized_items),
            total_matched=result.total_matched,
            is_truncated=result.is_truncated,
        )

    async def find_deadlocks(
        self, criteria: DeadlockCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[DeadlockDomainDTO]:
        """Find recent deadlock events with sanitized resource descriptions and summaries."""
        result = await self._repository.find_deadlocks(criteria)
        sanitized_items = [
            DeadlockDomainDTO(
                deadlock_id=item.deadlock_id,
                occurred_at=item.occurred_at,
                victim_session_id=item.victim_session_id,
                participating_session_count=item.participating_session_count,
                resource_description=self._sanitize_string(item.resource_description),
                summary=self._sanitize_string(item.summary),
            )
            for item in result.items
        ]
        return BoundedDiagnosticResultDTO[DeadlockDomainDTO](
            items=tuple(sanitized_items),
            returned_count=len(sanitized_items),
            total_matched=result.total_matched,
            is_truncated=result.is_truncated,
        )

    async def find_blocking_sessions(
        self, criteria: BlockingSessionCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[BlockingSessionDomainDTO]:
        """Find active blocking sessions."""
        return await self._repository.find_blocking_sessions(criteria)

    async def get_ticket_diagnostic_record(
        self, criteria: TicketDiagnosticCriteriaDTO
    ) -> TicketDiagnosticRecordDomainDTO | None:
        """Fetch ticket-scoped diagnostic record (fails closed if unconfigured)."""
        record = await self._repository.get_ticket_diagnostic_record(criteria)
        if record is None:
            return None
        return TicketDiagnosticRecordDomainDTO(
            ticket_id=record.ticket_id,
            has_db_activity=record.has_db_activity,
            recent_error_count=record.recent_error_count,
            last_activity_time=record.last_activity_time,
            diagnostic_summary=self._sanitize_string(record.diagnostic_summary),
        )
