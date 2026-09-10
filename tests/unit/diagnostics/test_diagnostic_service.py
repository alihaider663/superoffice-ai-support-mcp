"""Unit tests for DiagnosticsApplicationService coordination and PII sanitization."""

from datetime import UTC, datetime

import pytest

from diag_mcp.contracts.dtos import (
    BlockingSessionCriteriaDTO,
    BlockingSessionDomainDTO,
    BoundedDiagnosticResultDTO,
    DatabaseBackupStatusDTO,
    DatabaseConnectivityDTO,
    DatabaseHealthDomainDTO,
    DeadlockCriteriaDTO,
    DeadlockDomainDTO,
    SlowQueryCriteriaDTO,
    SlowQueryDomainDTO,
    TicketDiagnosticCriteriaDTO,
)
from diag_mcp.contracts.errors import DatabaseDiagnosticError
from diag_mcp.contracts.interfaces import DiagnosticRepository
from diag_mcp.services.diagnostic_service import DiagnosticsApplicationService
from platform_security.sanitization import RecursiveOutputSanitizer


class _MockDiagnosticRepository(DiagnosticRepository):
    """Test fake repository providing configurable responses."""

    def __init__(self) -> None:
        self.health_response = DatabaseHealthDomainDTO(
            is_healthy=True,
            status_summary="ONLINE (admin@superoffice.com)",
            active_connections=5,
            latency_ms=1.5,
            collected_at=datetime.now(UTC),
        )
        self.slow_queries_response = BoundedDiagnosticResultDTO[SlowQueryDomainDTO](
            items=(
                SlowQueryDomainDTO(
                    query_hash="0xABCD",
                    duration_ms=3000,
                    cpu_time_ms=1500,
                    logical_reads=800,
                    execution_count=10,
                    last_execution_time=datetime.now(UTC),
                    summary=(
                        "SELECT * FROM users WHERE email = 'john.doe@example.com' "
                        "AND secret = 'Bearer token123'"
                    ),
                ),
            ),
            returned_count=1,
            total_matched=None,
            is_truncated=False,
        )
        self.deadlocks_response = BoundedDiagnosticResultDTO[DeadlockDomainDTO](
            items=(
                DeadlockDomainDTO(
                    deadlock_id="DLOCK-101",
                    occurred_at=datetime.now(UTC),
                    victim_session_id=55,
                    participating_session_count=2,
                    resource_description="Lock on table customer_records (owner: admin@corp.local)",
                    summary="Deadlock involving user john@example.com",
                ),
            ),
            returned_count=1,
            total_matched=None,
            is_truncated=False,
        )
        self.blocking_response = BoundedDiagnosticResultDTO[BlockingSessionDomainDTO](
            items=(
                BlockingSessionDomainDTO(
                    blocked_session_id=10,
                    blocking_session_id=20,
                    wait_duration_ms=8000,
                    wait_type="LCK_M_X",
                    detected_at=datetime.now(UTC),
                ),
            ),
            returned_count=1,
            total_matched=None,
            is_truncated=False,
        )

    async def get_database_health(self) -> DatabaseHealthDomainDTO:
        return self.health_response

    async def find_slow_queries(
        self, criteria: SlowQueryCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[SlowQueryDomainDTO]:
        _ = criteria
        return self.slow_queries_response

    async def find_deadlocks(
        self, criteria: DeadlockCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[DeadlockDomainDTO]:
        _ = criteria
        return self.deadlocks_response

    async def find_blocking_sessions(
        self, criteria: BlockingSessionCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[BlockingSessionDomainDTO]:
        _ = criteria
        return self.blocking_response

    async def get_ticket_diagnostic_record(self, criteria: TicketDiagnosticCriteriaDTO) -> None:
        _ = criteria
        raise DatabaseDiagnosticError(
            message="Unconfigured",
            error_code="DIAGNOSTIC_SCHEMA_NOT_CONFIGURED",
        )


@pytest.mark.asyncio
async def test_application_service_health_sanitization() -> None:
    """Service scrubs PII from health status summary."""
    repo = _MockDiagnosticRepository()
    service = DiagnosticsApplicationService(repo, RecursiveOutputSanitizer())

    health = await service.get_database_health()
    assert health.is_healthy is True
    assert "[REDACTED_EMAIL]" in health.status_summary
    assert "admin@superoffice.com" not in health.status_summary


@pytest.mark.asyncio
async def test_application_service_slow_queries_sanitization() -> None:
    """Service scrubs emails and tokens from slow query summaries."""
    repo = _MockDiagnosticRepository()
    service = DiagnosticsApplicationService(repo, RecursiveOutputSanitizer())

    result = await service.find_slow_queries(SlowQueryCriteriaDTO())
    assert result.returned_count == 1
    summary = result.items[0].summary
    assert "[REDACTED_EMAIL]" in summary
    assert "john.doe@example.com" not in summary
    assert "[REDACTED_TOKEN]" in summary or "Bearer" in summary


@pytest.mark.asyncio
async def test_application_service_deadlocks_sanitization() -> None:
    """Service scrubs emails from deadlock summaries and resource descriptions."""
    repo = _MockDiagnosticRepository()
    service = DiagnosticsApplicationService(repo, RecursiveOutputSanitizer())

    result = await service.find_deadlocks(DeadlockCriteriaDTO())
    assert result.returned_count == 1
    item = result.items[0]
    assert "[REDACTED_EMAIL]" in item.resource_description
    assert "[REDACTED_EMAIL]" in item.summary
    assert "john@example.com" not in item.summary


@pytest.mark.asyncio
async def test_application_service_blocking_sessions_passthrough() -> None:
    """Service returns blocking session records."""
    repo = _MockDiagnosticRepository()
    service = DiagnosticsApplicationService(repo)

    result = await service.find_blocking_sessions(BlockingSessionCriteriaDTO())
    assert result.returned_count == 1
    assert result.items[0].blocked_session_id == 10
    assert result.items[0].blocking_session_id == 20


@pytest.mark.asyncio
async def test_application_service_ticket_diagnostic_fails_closed() -> None:
    """Service propagates DIAGNOSTIC_SCHEMA_NOT_CONFIGURED error."""
    repo = _MockDiagnosticRepository()
    service = DiagnosticsApplicationService(repo)

    with pytest.raises(DatabaseDiagnosticError) as exc_info:
        await service.get_ticket_diagnostic_record(TicketDiagnosticCriteriaDTO(ticket_id=123))

    assert exc_info.value.error_code == "DIAGNOSTIC_SCHEMA_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_application_service_health_backup_status_sanitization() -> None:
    """Service preserves backup_status and sanitizes any sensitive error_message text."""
    repo = _MockDiagnosticRepository()
    now = datetime.now(UTC)
    repo.health_response = DatabaseHealthDomainDTO(
        is_healthy=True,
        status_summary="ONLINE",
        active_connections=5,
        latency_ms=1.5,
        collected_at=now,
        backup_status=DatabaseBackupStatusDTO(
            backup_found=None,
            status="UNAVAILABLE",
            error_message="Query failed for admin@superoffice.com on host 10.0.0.1",
        ),
    )
    service = DiagnosticsApplicationService(repo, RecursiveOutputSanitizer())

    health = await service.get_database_health()
    assert health.backup_status is not None
    assert health.backup_status.status == "UNAVAILABLE"
    assert health.backup_status.backup_found is None
    assert health.backup_status.error_message is not None
    assert "[REDACTED_EMAIL]" in health.backup_status.error_message
    assert "admin@superoffice.com" not in health.backup_status.error_message


@pytest.mark.asyncio
async def test_application_service_connectivity_sanitization() -> None:
    """Service preserves connectivity and sanitizes observed_failure text."""
    repo = _MockDiagnosticRepository()
    now = datetime.now(UTC)
    repo.health_response = DatabaseHealthDomainDTO(
        is_healthy=False,
        status_summary="UNAVAILABLE",
        active_connections=0,
        latency_ms=2.1,
        collected_at=now,
        connectivity=DatabaseConnectivityDTO(
            state="DATABASE_CONNECTION_FAILURE",
            observed_failure="Failed connect for user admin@superoffice.com on server 10.0.0.1",
        ),
    )
    service = DiagnosticsApplicationService(repo, RecursiveOutputSanitizer())

    health = await service.get_database_health()
    assert health.connectivity is not None
    assert health.connectivity.state == "DATABASE_CONNECTION_FAILURE"
    assert health.connectivity.observed_failure is not None
    assert "[REDACTED_EMAIL]" in health.connectivity.observed_failure
    assert "admin@superoffice.com" not in health.connectivity.observed_failure
