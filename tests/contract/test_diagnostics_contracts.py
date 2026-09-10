"""Offline contract tests for Diagnostics MSSQL, Application Logs, DTOs, and test fakes."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from diag_mcp.contracts.dtos import (
    BlockingSessionCriteriaDTO,
    BlockingSessionDomainDTO,
    BoundedDiagnosticResultDTO,
    DatabaseBackupStatusDTO,
    DatabaseConnectivityDTO,
    DatabaseConnectivityState,
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
from diag_mcp.server import create_diagnostics_mcp_server
from platform_gateway.schemas import get_tool_schema_map
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
    assert health.backup_status is None
    assert health.connectivity is None


def test_database_connectivity_dto_contract() -> None:
    """Verify DatabaseConnectivityDTO initialization, states, immutability, and serialization."""
    approved_states: list[DatabaseConnectivityState] = [
        "CONNECTED",
        "DNS_RESOLUTION_FAILURE",
        "TCP_CONNECTIVITY_FAILURE",
        "TCP_CONNECTIVITY_TIMEOUT",
        "DATABASE_AUTHENTICATION_FAILURE",
        "DATABASE_CONNECTION_FAILURE",
        "DATABASE_CONNECTION_TIMEOUT",
        "DATABASE_QUERY_FAILURE",
        "DATABASE_QUERY_TIMEOUT",
        "UNKNOWN",
    ]
    for st in approved_states:
        conn = DatabaseConnectivityDTO(state=st, observed_failure="Factual observed boundary")
        assert conn.state == st
        assert conn.observed_failure == "Factual observed boundary"

    # Connected state with None failure
    connected = DatabaseConnectivityDTO(state="CONNECTED", observed_failure=None)
    assert connected.state == "CONNECTED"
    assert connected.observed_failure is None

    # Frozen immutability check
    with pytest.raises(ValidationError):
        connected.state = "UNKNOWN"

    # Extra forbid check
    with pytest.raises(ValidationError):
        DatabaseConnectivityDTO.model_validate(
            {
                "state": "CONNECTED",
                "extra_field": 123,
            }
        )

    # Unapproved state check
    with pytest.raises(ValidationError):
        DatabaseConnectivityDTO.model_validate(
            {
                "state": "INVALID_STATE",
            }
        )

    # Embedded in DatabaseHealthDomainDTO serialization
    now = datetime.now(UTC)
    health = DatabaseHealthDomainDTO(
        is_healthy=True,
        status_summary="ONLINE",
        active_connections=5,
        latency_ms=1.1,
        collected_at=now,
        connectivity=connected,
    )
    dumped = health.model_dump(mode="json")
    assert "connectivity" in dumped
    assert dumped["connectivity"]["state"] == "CONNECTED"
    assert dumped["connectivity"]["observed_failure"] is None


def test_database_backup_status_dto_valid() -> None:
    """Verify DatabaseBackupStatusDTO initialization, serialization, and constraints."""
    recorded_time = datetime(2026, 9, 10, 8, 30, 0)
    backup_status = DatabaseBackupStatusDTO(
        backup_found=True,
        latest_backup_at=recorded_time,
        latest_backup_type="FULL",
        latest_full_backup_at=recorded_time,
        latest_differential_backup_at=None,
        latest_log_backup_at=None,
        status="AVAILABLE",
        error_message=None,
    )
    assert backup_status.backup_found is True
    assert backup_status.latest_backup_at == recorded_time
    assert backup_status.latest_backup_at.tzinfo is None
    assert backup_status.latest_backup_type == "FULL"
    assert backup_status.latest_full_backup_at == recorded_time
    assert backup_status.status == "AVAILABLE"

    # Verify JSON serialization has no trailing Z (SQL Server recorded time)
    dumped = backup_status.model_dump(mode="json")
    assert dumped["latest_backup_at"] == "2026-09-10T08:30:00"
    assert not dumped["latest_backup_at"].endswith("Z")

    # Frozen immutability check
    with pytest.raises(ValidationError):
        backup_status.backup_found = False

    # Extra forbid check
    with pytest.raises(ValidationError):
        DatabaseBackupStatusDTO.model_validate(
            {
                "backup_found": True,
                "unauthorized_field": 123,
            }
        )


def test_database_health_dto_with_backup_status() -> None:
    """Verify DatabaseHealthDomainDTO correctly embeds and serializes DatabaseBackupStatusDTO."""
    now = datetime.now(UTC)
    backup_status = DatabaseBackupStatusDTO(
        backup_found=False,
        latest_backup_at=None,
        latest_backup_type=None,
        latest_full_backup_at=None,
        latest_differential_backup_at=None,
        latest_log_backup_at=None,
        status="AVAILABLE",
    )
    health = DatabaseHealthDomainDTO(
        is_healthy=True,
        status_summary="ONLINE",
        active_connections=10,
        latency_ms=1.2,
        collected_at=now,
        backup_status=backup_status,
    )
    assert health.backup_status is not None
    assert health.backup_status.backup_found is False

    dumped = health.model_dump(mode="json")
    assert "backup_status" in dumped
    assert dumped["backup_status"]["backup_found"] is False
    assert dumped["backup_status"]["status"] == "AVAILABLE"


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


# ============================================================================
# Diagnostics Evidence Discipline Contract Tests
# ============================================================================


def test_database_health_tool_description_evidence_discipline() -> None:
    """Verify get_database_health descriptions enforce evidence discipline in MCP and Gateway."""
    # 1. Gateway public schema
    gateway_tools = get_tool_schema_map()
    assert "get_database_health" in gateway_tools
    gw_desc = gateway_tools["get_database_health"].description
    assert gw_desc is not None

    # 2. Server tool definition
    server = create_diagnostics_mcp_server()
    srv_tool = server._tool_manager.get_tool("get_database_health")
    assert srv_tool is not None
    srv_desc = srv_tool.description
    assert srv_desc is not None

    for desc in (gw_desc, srv_desc):
        assert "point-in-time" in desc.lower() or "current" in desc.lower()
        assert "not invalidate" in desc.lower()
        assert "unknown" in desc.lower()
        assert "latency_ms" in desc
        assert "not by itself prove" in desc.lower()
        assert "do not recommend" in desc.lower()


def test_backup_status_dto_descriptions_evidence_discipline() -> None:
    """Verify DatabaseBackupStatusDTO field descriptions mandate timezone and SLA discipline."""
    fields = DatabaseBackupStatusDTO.model_fields

    # status=AVAILABLE means inspection succeeded, NOT healthy/fresh/SLA compliant
    status_desc = fields["status"].description or ""
    assert "inspection succeeded" in status_desc
    assert "not mean" in status_desc.lower()
    assert "freshness sla" in status_desc.lower()

    # Timezone unasserted: clients must NOT append Z or label UTC
    for ts_field in (
        "latest_backup_at",
        "latest_full_backup_at",
        "latest_differential_backup_at",
        "latest_log_backup_at",
    ):
        desc = fields[ts_field].description or ""
        assert "TIMEZONE IS UNASSERTED" in desc
        assert "MUST NOT append 'Z'" in desc
        assert "label as UTC" in desc

    # error_message=null does not imply physical verification
    err_desc = fields["error_message"].description or ""
    assert "physical backup file verification" in err_desc


def test_blocking_deadlock_and_slow_query_tool_descriptions_evidence_discipline() -> None:
    """Verify blocking, deadlock, and slow query descriptions prevent over-interpretation."""
    gateway_tools = get_tool_schema_map()
    server = create_diagnostics_mcp_server()

    # Blocking: snapshot only, 0 does not prove no blocking before snapshot
    gw_blocking = gateway_tools["find_blocking_sessions"].description
    assert gw_blocking is not None
    srv_blocking_tool = server._tool_manager.get_tool("find_blocking_sessions")
    assert srv_blocking_tool is not None
    srv_blocking = srv_blocking_tool.description
    assert srv_blocking is not None
    for desc in (gw_blocking, srv_blocking):
        assert "snapshot" in desc.lower()
        assert "not prove absence of blocking prior" in desc.lower()

    # Deadlocks: windowed capture only, 0 does not prove historical absence outside window
    gw_deadlock = gateway_tools["find_deadlocks"].description
    assert gw_deadlock is not None
    srv_deadlock_tool = server._tool_manager.get_tool("find_deadlocks")
    assert srv_deadlock_tool is not None
    srv_deadlock = srv_deadlock_tool.description
    assert srv_deadlock is not None
    for desc in (gw_deadlock, srv_deadlock):
        assert "queried time window" in desc.lower() or "window" in desc.lower()
        assert "not prove historical absence" in desc.lower()

    # Slow queries: plan cache aggregated historical averages, not real-time query executions
    gw_slow = gateway_tools["find_slow_queries"].description
    assert gw_slow is not None
    srv_slow_tool = server._tool_manager.get_tool("find_slow_queries")
    assert srv_slow_tool is not None
    srv_slow = srv_slow_tool.description
    assert srv_slow is not None
    for desc in (gw_slow, srv_slow):
        assert "plan cache" in desc.lower()
        assert "aggregated" in desc.lower() or "averages" in desc.lower()
