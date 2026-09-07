"""Offline contract tests for Diagnostics MSSQL, Application Logs, DTOs, and test fakes."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from diag_mcp.contracts.dtos import (
    BlockingSessionCriteriaDTO,
    BlockingSessionDomainDTO,
    BoundedDiagnosticResultDTO,
    DatabaseHealthDomainDTO,
    DeadlockCriteriaDTO,
    DeadlockDomainDTO,
    LogRecordDomainDTO,
    LogSearchCriteriaDTO,
    SanitizedLogExcerptDTO,
    SlowQueryCriteriaDTO,
    SlowQueryDomainDTO,
    TicketDiagnosticCriteriaDTO,
    TicketDiagnosticRecordDomainDTO,
)
from diag_mcp.contracts.errors import (
    DatabaseDiagnosticError,
    LogSearchError,
)
from diag_mcp.contracts.interfaces import (
    DiagnosticRepository,
    LogSearchClient,
)
from tests.fakes.fake_diagnostic_repository import FakeDiagnosticRepository
from tests.fakes.fake_log_search_client import FakeLogSearchClient

# ============================================================================
# 1. DTO Validation & Immutability Tests
# ============================================================================


def test_database_health_dto_valid() -> None:
    """Verify DatabaseHealthDomainDTO initialization and constraints."""
    now = datetime.now(UTC)
    health = DatabaseHealthDomainDTO(
        is_healthy=True,
        status_summary="ONLINE",
        active_connections=25,
        latency_ms=2.4,
        collected_at=now,
    )
    assert health.is_healthy is True
    assert health.status_summary == "ONLINE"
    assert health.active_connections == 25
    assert health.latency_ms == 2.4


def test_dto_immutability_and_extra_forbid() -> None:
    """Verify diagnostic models are frozen and forbid unexpected fields."""
    now = datetime.now(UTC)
    slow_q = SlowQueryDomainDTO(
        query_hash="0xABCD1234",
        duration_ms=2500,
        cpu_time_ms=1200,
        logical_reads=45000,
        execution_count=5,
        last_execution_time=now,
        summary="Ticket contact lookup indexing delay",
    )
    # Frozen mutation check
    field_to_mutate = "duration_ms"
    with pytest.raises(ValidationError):
        setattr(slow_q, field_to_mutate, 9999)

    # Extra field forbid check
    extra_payload = {
        "query_hash": "0xABCD1234",
        "duration_ms": 2500,
        "cpu_time_ms": 1200,
        "logical_reads": 45000,
        "execution_count": 5,
        "last_execution_time": now.isoformat(),
        "summary": "Valid summary",
        "unauthorized_raw_sql": "SELECT * FROM Users",
    }
    with pytest.raises(ValidationError):
        SlowQueryDomainDTO.model_validate(extra_payload)


def test_log_dtos_layering_and_classification() -> None:
    """Verify Internal Log DTO and AI-Safe Log Excerpt DTO structural separation."""
    now = datetime.now(UTC)
    # 1. Internal restricted log record
    internal_log = LogRecordDomainDTO(
        log_id="LOG-8812",
        timestamp=now,
        service_name="so-web-api",
        severity="ERROR",
        message="Failed authentication for user=admin@acme.no from IP=10.0.4.12",
        correlation_id="CORR-9982",
        ticket_id=4040,
        raw_context={"client_ip": "10.0.4.12", "http_status": "401"},
    )
    assert internal_log.log_id == "LOG-8812"
    assert "admin@acme.no" in internal_log.message

    # 2. AI-facing sanitized log excerpt
    ai_log = SanitizedLogExcerptDTO(
        excerpt_id="LOG-8812",
        timestamp=now,
        service_name="so-web-api",
        severity="ERROR",
        sanitized_message="Failed authentication for user=[REDACTED_EMAIL] from IP=[REDACTED_IP]",
        correlation_id="CORR-9982",
    )
    assert ai_log.excerpt_id == "LOG-8812"
    assert "sanitized_message" in SanitizedLogExcerptDTO.model_fields


# ============================================================================
# 2. Bounded Diagnostic Result Envelope Tests
# ============================================================================


def test_bounded_envelope_invariants_valid() -> None:
    """Verify BoundedDiagnosticResultDTO invariants when valid."""
    now = datetime.now(UTC)
    q1 = SlowQueryDomainDTO(
        query_hash="0x1111",
        duration_ms=1500,
        last_execution_time=now,
    )
    envelope = BoundedDiagnosticResultDTO[SlowQueryDomainDTO](
        items=(q1,),
        returned_count=1,
        total_matched=10,
        is_truncated=True,
    )
    assert envelope.returned_count == 1
    assert envelope.total_matched == 10
    assert envelope.is_truncated is True


def test_bounded_envelope_invariants_rejected() -> None:
    """Verify BoundedDiagnosticResultDTO raises if envelope invariants are violated."""
    now = datetime.now(UTC)
    q1 = SlowQueryDomainDTO(
        query_hash="0x1111",
        duration_ms=1500,
        last_execution_time=now,
    )

    # 1. returned_count does not match len(items)
    with pytest.raises(ValidationError):
        BoundedDiagnosticResultDTO[SlowQueryDomainDTO](
            items=(q1,),
            returned_count=2,  # Invalid: items length is 1
            total_matched=2,
            is_truncated=False,
        )

    # 2. total_matched is less than returned_count
    with pytest.raises(ValidationError):
        BoundedDiagnosticResultDTO[SlowQueryDomainDTO](
            items=(q1,),
            returned_count=1,
            total_matched=0,  # Invalid: cannot be less than returned_count
            is_truncated=False,
        )


# ============================================================================
# 3. Error Sanitization Tests
# ============================================================================


def test_database_diagnostic_error_sanitization() -> None:
    """Verify DatabaseDiagnosticError sanitizes credentials and internal connection strings."""
    secret_conn = "Server=tcp:sql-prod.database.windows.net;User ID=sa;Password=SecretPassword123"
    err = DatabaseDiagnosticError(
        "MSSQL diagnostic query failed due to statement timeout.",
        details={"connection_string": secret_conn, "timeout_seconds": 10},
    )
    sanitized = err.to_sanitized_dict()
    assert sanitized["error"] == "DATABASE_DIAGNOSTIC_ERROR"
    assert sanitized["message"] == "MSSQL diagnostic query failed due to statement timeout."
    assert "SecretPassword123" not in sanitized.get("message", "")


def test_log_search_error_sanitization() -> None:
    """Verify LogSearchError sanitizes backend filesystem paths and cluster endpoints."""
    internal_path = "/var/log/superoffice/internal-cluster-node-03/auth.log"
    err = LogSearchError(
        "Failed to read application log slice.",
        details={"file_path": internal_path},
    )
    sanitized = err.to_sanitized_dict()
    assert sanitized["error"] == "LOG_SEARCH_ERROR"
    assert sanitized["message"] == "Failed to read application log slice."


# ============================================================================
# 4. FakeDiagnosticRepository & Protocol Conformance Tests
# ============================================================================


def test_fake_diagnostic_repository_is_instance_of_protocol() -> None:
    """Verify FakeDiagnosticRepository satisfies DiagnosticRepository Protocol."""
    fake = FakeDiagnosticRepository()
    assert isinstance(fake, DiagnosticRepository)


def test_fake_diagnostic_repository_operations() -> None:
    """Verify in-memory query, health, and bounded results in FakeDiagnosticRepository."""

    async def _run_async() -> None:
        fake = FakeDiagnosticRepository()
        now = datetime.now(UTC)

        # 1. Test Database Health
        health = await fake.get_database_health()
        assert health.is_healthy is True
        assert health.status_summary == "ONLINE"

        # 2. Seed and Query Slow Queries
        fake.seed_slow_query(
            SlowQueryDomainDTO(
                query_hash="0xAAA1",
                duration_ms=1200,
                last_execution_time=now - timedelta(minutes=5),
            )
        )
        fake.seed_slow_query(
            SlowQueryDomainDTO(
                query_hash="0xAAA2",
                duration_ms=4500,
                last_execution_time=now - timedelta(minutes=2),
            )
        )

        res_slow = await fake.find_slow_queries(SlowQueryCriteriaDTO(min_duration_ms=2000, limit=5))
        assert res_slow.returned_count == 1
        assert res_slow.items[0].query_hash == "0xAAA2"

        # 3. Seed and Query Deadlocks
        fake.seed_deadlock(
            DeadlockDomainDTO(
                deadlock_id="DLOCK-101",
                occurred_at=now - timedelta(minutes=10),
                victim_session_id=54,
                participating_session_count=2,
                resource_description="Page Lock on Tickets",
            )
        )
        res_deadlock = await fake.find_deadlocks(
            DeadlockCriteriaDTO(start_time=now - timedelta(hours=1))
        )
        assert res_deadlock.returned_count == 1
        assert res_deadlock.items[0].deadlock_id == "DLOCK-101"

        # 4. Seed and Query Blocking Sessions
        fake.seed_blocking_session(
            BlockingSessionDomainDTO(
                blocked_session_id=88,
                blocking_session_id=12,
                wait_duration_ms=15000,
                wait_type="LCK_M_X",
                detected_at=now,
            )
        )
        res_block = await fake.find_blocking_sessions(
            BlockingSessionCriteriaDTO(min_blocked_duration_ms=10000)
        )
        assert res_block.returned_count == 1
        assert res_block.items[0].blocked_session_id == 88

        # 5. Ticket Diagnostic Record (Present vs Missing)
        fake.seed_ticket_diagnostic(
            9001,
            TicketDiagnosticRecordDomainDTO(
                ticket_id=9001,
                has_db_activity=True,
                recent_error_count=3,
                last_activity_time=now,
                diagnostic_summary="Recent deadlocks associated with ticket update transaction.",
            ),
        )
        ticket_diag = await fake.get_ticket_diagnostic_record(
            TicketDiagnosticCriteriaDTO(ticket_id=9001)
        )
        assert ticket_diag is not None
        assert ticket_diag.ticket_id == 9001
        assert ticket_diag.has_db_activity is True
        assert ticket_diag.recent_error_count == 3

        # Unseeded ticket explicitly returns None
        unseeded_diag = await fake.get_ticket_diagnostic_record(
            TicketDiagnosticCriteriaDTO(ticket_id=99999)
        )
        assert unseeded_diag is None

        # 6. Simulated failure check
        fake.set_should_fail(True)
        with pytest.raises(DatabaseDiagnosticError):
            await fake.get_database_health()

    asyncio.run(_run_async())


# ============================================================================
# 5. FakeLogSearchClient & Protocol Conformance Tests
# ============================================================================


def test_fake_log_search_client_is_instance_of_protocol() -> None:
    """Verify FakeLogSearchClient satisfies LogSearchClient Protocol."""
    fake = FakeLogSearchClient()
    assert isinstance(fake, LogSearchClient)


def test_fake_log_search_filtering_and_bounding() -> None:
    """Verify structured filtering and bounded pagination in FakeLogSearchClient."""

    async def _run_async() -> None:
        fake = FakeLogSearchClient()
        now = datetime.now(UTC)

        fake.seed_log(
            LogRecordDomainDTO(
                log_id="L-01",
                timestamp=now - timedelta(minutes=30),
                service_name="so-web",
                severity="INFO",
                message="User login succeeded with pattern .*",
                correlation_id="CORR-1",
            )
        )
        fake.seed_log(
            LogRecordDomainDTO(
                log_id="L-02",
                timestamp=now - timedelta(minutes=15),
                service_name="so-api",
                severity="ERROR",
                message="Ticket synchronization failed with timeout",
                correlation_id="CORR-2",
                ticket_id=5005,
            )
        )
        fake.seed_log(
            LogRecordDomainDTO(
                log_id="L-03",
                timestamp=now - timedelta(minutes=5),
                service_name="so-api",
                severity="ERROR",
                message="Database connection pool exhausted",
                correlation_id="CORR-3",
            )
        )

        # 1. Filter by service name & severity
        res1 = await fake.search_logs(LogSearchCriteriaDTO(service_name="so-api", severity="ERROR"))
        assert res1.returned_count == 2
        assert res1.total_matched == 2
        assert res1.is_truncated is False

        # 2. Filter by ticket_id
        res2 = await fake.search_logs(LogSearchCriteriaDTO(ticket_id=5005))
        assert res2.returned_count == 1
        assert res2.items[0].log_id == "L-02"

        # 3. Filter by query_text literal data match (e.g. literal '.*' is matched as string)
        res_regex_lit = await fake.search_logs(LogSearchCriteriaDTO(query_text="pattern .*"))
        assert res_regex_lit.returned_count == 1
        assert res_regex_lit.items[0].log_id == "L-01"

        # '.*' alone does not match logs that do not contain the literal characters '.*'
        res_no_wildcard = await fake.search_logs(LogSearchCriteriaDTO(query_text="pool .*"))
        assert res_no_wildcard.returned_count == 0

        # 4. Limit and truncation check
        res4 = await fake.search_logs(LogSearchCriteriaDTO(severity="ERROR", limit=1))
        assert res4.returned_count == 1
        assert res4.total_matched == 2
        assert res4.is_truncated is True

        # 5. Simulated failure check
        fake.set_should_fail(True)
        with pytest.raises(LogSearchError):
            await fake.search_logs(LogSearchCriteriaDTO())

    asyncio.run(_run_async())
