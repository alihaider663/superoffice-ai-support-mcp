"""Deterministic in-memory FakeDiagnosticRepository for offline contract testing."""

from datetime import UTC, datetime

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
from diag_mcp.contracts.errors import DatabaseDiagnosticError


class FakeDiagnosticRepository:
    """Deterministic in-memory implementation of DiagnosticRepository Protocol."""

    def __init__(self) -> None:
        self._health: DatabaseHealthDomainDTO = DatabaseHealthDomainDTO(
            is_healthy=True,
            status_summary="ONLINE",
            active_connections=12,
            latency_ms=1.5,
            collected_at=datetime.now(UTC),
        )
        self._slow_queries: list[SlowQueryDomainDTO] = []
        self._deadlocks: list[DeadlockDomainDTO] = []
        self._blocking_sessions: list[BlockingSessionDomainDTO] = []
        self._ticket_diagnostics: dict[int, TicketDiagnosticRecordDomainDTO] = {}
        self._should_fail: bool = False

    # Seed helpers for test setup
    def set_health(self, health: DatabaseHealthDomainDTO) -> None:
        """Seed the database health status."""
        self._health = health

    def seed_slow_query(self, query: SlowQueryDomainDTO) -> None:
        """Seed a slow query record."""
        self._slow_queries.append(query)

    def seed_deadlock(self, deadlock: DeadlockDomainDTO) -> None:
        """Seed a deadlock event."""
        self._deadlocks.append(deadlock)

    def seed_blocking_session(self, session: BlockingSessionDomainDTO) -> None:
        """Seed a blocking session record."""
        self._blocking_sessions.append(session)

    def seed_ticket_diagnostic(
        self, ticket_id: int, record: TicketDiagnosticRecordDomainDTO
    ) -> None:
        """Seed a ticket diagnostic activity record."""
        self._ticket_diagnostics[ticket_id] = record

    def set_should_fail(self, should_fail: bool) -> None:
        """Simulate a database diagnostic failure."""
        self._should_fail = should_fail

    # Protocol implementation
    async def get_database_health(self) -> DatabaseHealthDomainDTO:
        """Fetch database health."""
        if self._should_fail:
            raise DatabaseDiagnosticError("Simulated database health check failure.")
        return self._health

    async def find_slow_queries(
        self, criteria: SlowQueryCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[SlowQueryDomainDTO]:
        """Find slow queries matching criteria."""
        if self._should_fail:
            raise DatabaseDiagnosticError("Simulated query execution failure.")

        matched: list[SlowQueryDomainDTO] = []
        for q in self._slow_queries:
            if q.duration_ms < criteria.min_duration_ms:
                continue
            if criteria.start_time and q.last_execution_time < criteria.start_time:
                continue
            if criteria.end_time and q.last_execution_time > criteria.end_time:
                continue
            matched.append(q)

        total_matched = len(matched)
        limit = criteria.limit if criteria.limit is not None else total_matched
        items_slice = tuple(matched[:limit])
        is_truncated = limit < total_matched

        return BoundedDiagnosticResultDTO[SlowQueryDomainDTO](
            items=items_slice,
            returned_count=len(items_slice),
            total_matched=total_matched,
            is_truncated=is_truncated,
        )

    async def find_deadlocks(
        self, criteria: DeadlockCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[DeadlockDomainDTO]:
        """Query deadlock events matching time window."""
        if self._should_fail:
            raise DatabaseDiagnosticError("Simulated deadlock query failure.")

        matched: list[DeadlockDomainDTO] = []
        for d in self._deadlocks:
            if criteria.start_time and d.occurred_at < criteria.start_time:
                continue
            if criteria.end_time and d.occurred_at > criteria.end_time:
                continue
            matched.append(d)

        total_matched = len(matched)
        limit = criteria.limit if criteria.limit is not None else total_matched
        items_slice = tuple(matched[:limit])
        is_truncated = limit < total_matched

        return BoundedDiagnosticResultDTO[DeadlockDomainDTO](
            items=items_slice,
            returned_count=len(items_slice),
            total_matched=total_matched,
            is_truncated=is_truncated,
        )

    async def find_blocking_sessions(
        self, criteria: BlockingSessionCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[BlockingSessionDomainDTO]:
        """Query blocking sessions exceeding threshold."""
        if self._should_fail:
            raise DatabaseDiagnosticError("Simulated blocking session query failure.")

        matched: list[BlockingSessionDomainDTO] = []
        for s in self._blocking_sessions:
            if s.wait_duration_ms < criteria.min_blocked_duration_ms:
                continue
            matched.append(s)

        total_matched = len(matched)
        limit = criteria.limit if criteria.limit is not None else total_matched
        items_slice = tuple(matched[:limit])
        is_truncated = limit < total_matched

        return BoundedDiagnosticResultDTO[BlockingSessionDomainDTO](
            items=items_slice,
            returned_count=len(items_slice),
            total_matched=total_matched,
            is_truncated=is_truncated,
        )

    async def get_ticket_diagnostic_record(
        self, criteria: TicketDiagnosticCriteriaDTO
    ) -> TicketDiagnosticRecordDomainDTO | None:
        """Fetch ticket diagnostic record by ticket_id or None if not found."""
        if self._should_fail:
            raise DatabaseDiagnosticError("Simulated ticket diagnostic lookup failure.")

        return self._ticket_diagnostics.get(criteria.ticket_id)
