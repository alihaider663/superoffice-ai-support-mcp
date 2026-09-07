"""Protocol interfaces for Diagnostics database and application log boundaries."""

from typing import Protocol, runtime_checkable

from diag_mcp.contracts.dtos import (
    BlockingSessionCriteriaDTO,
    BlockingSessionDomainDTO,
    BoundedDiagnosticResultDTO,
    DatabaseHealthDomainDTO,
    DeadlockCriteriaDTO,
    DeadlockDomainDTO,
    LogRecordDomainDTO,
    LogSearchCriteriaDTO,
    SlowQueryCriteriaDTO,
    SlowQueryDomainDTO,
    TicketDiagnosticCriteriaDTO,
    TicketDiagnosticRecordDomainDTO,
)


@runtime_checkable
class DiagnosticRepository(Protocol):
    """Protocol for MSSQL read-only diagnostic repository implementations."""

    async def get_database_health(self) -> DatabaseHealthDomainDTO:
        """Fetch high-level availability, active connection count, and latency.

        Raises:
            DatabaseDiagnosticError: If database is unreachable or health check fails.
        """
        ...

    async def find_slow_queries(
        self, criteria: SlowQueryCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[SlowQueryDomainDTO]:
        """Find slow query records matching execution time threshold and window.

        Raises:
            DatabaseDiagnosticError: If diagnostic query execution fails.
        """
        ...

    async def find_deadlocks(
        self, criteria: DeadlockCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[DeadlockDomainDTO]:
        """Query recent deadlock events within the requested time window.

        Raises:
            DatabaseDiagnosticError: If diagnostic query execution fails.
        """
        ...

    async def find_blocking_sessions(
        self, criteria: BlockingSessionCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[BlockingSessionDomainDTO]:
        """Query currently active blocking sessions exceeding duration threshold.

        Raises:
            DatabaseDiagnosticError: If diagnostic query execution fails.
        """
        ...

    async def get_ticket_diagnostic_record(
        self, criteria: TicketDiagnosticCriteriaDTO
    ) -> TicketDiagnosticRecordDomainDTO | None:
        """Fetch database diagnostic activity and error metrics for a specific ticket.

        Returns:
            TicketDiagnosticRecordDomainDTO if matching activity exists, or None if
            no diagnostic record is found for the ticket.

        Raises:
            DatabaseDiagnosticError: If diagnostic lookup fails.
        """
        ...


@runtime_checkable
class LogSearchClient(Protocol):
    """Protocol for Application and API log search client implementations."""

    async def search_logs(
        self, criteria: LogSearchCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[LogRecordDomainDTO]:
        """Search application/API logs matching structured filter criteria.

        Raises:
            LogSearchError: If log search operation fails.
        """
        ...
