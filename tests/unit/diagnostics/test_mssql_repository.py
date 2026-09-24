"""Unit tests for MssqlDiagnosticRepository offline operation and error boundaries."""

import inspect
import socket
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as SaTimeoutError

from diag_mcp.adapters import mssql_repository
from diag_mcp.adapters.mssql_repository import MssqlDiagnosticRepository
from diag_mcp.contracts.dtos import (
    BlockingSessionCriteriaDTO,
    DeadlockCriteriaDTO,
    SlowQueryCriteriaDTO,
    TicketDiagnosticCriteriaDTO,
)
from diag_mcp.contracts.errors import DatabaseDiagnosticError


def _create_mock_engine(mock_cursor_result: Any = None, side_effect: Any = None) -> MagicMock:
    """Create a mocked AsyncEngine returning a mock connection with controlled query execution."""
    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)

    if side_effect:
        mock_conn.execute = AsyncMock(side_effect=side_effect)
    else:
        mock_result = MagicMock()
        if isinstance(mock_cursor_result, list):
            mock_result.fetchall = MagicMock(return_value=mock_cursor_result)
            mock_result.fetchone = MagicMock(
                return_value=mock_cursor_result[0] if mock_cursor_result else None
            )
        elif mock_cursor_result is not None:
            mock_result.fetchone = MagicMock(return_value=mock_cursor_result)
            mock_result.fetchall = MagicMock(return_value=[mock_cursor_result])
        else:
            mock_result.fetchall = MagicMock(return_value=[])
            mock_result.fetchone = MagicMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=mock_result)

    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)
    return mock_engine


def _create_multi_query_engine(results: list[Any]) -> MagicMock:
    """Create a mocked AsyncEngine returning sequential results for successive queries."""
    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)

    execute_results = []
    for item in results:
        if isinstance(item, Exception):
            execute_results.append(item)
        else:
            mock_res = MagicMock()
            if isinstance(item, list):
                mock_res.fetchall = MagicMock(return_value=item)
                mock_res.fetchone = MagicMock(return_value=item[0] if item else None)
            elif item is not None:
                mock_res.fetchone = MagicMock(return_value=item)
                mock_res.fetchall = MagicMock(return_value=[item])
            else:
                mock_res.fetchall = MagicMock(return_value=[])
                mock_res.fetchone = MagicMock(return_value=None)
            execute_results.append(mock_res)

    mock_conn.execute = AsyncMock(side_effect=execute_results)
    mock_engine = MagicMock()
    mock_engine.connect = MagicMock(return_value=mock_conn)
    return mock_engine


@pytest.mark.asyncio
async def test_snapshot_readiness_state_1_success() -> None:
    """State 1 (ON) succeeds and allows repository operation."""
    engine = _create_mock_engine(mock_cursor_result=(1, "ON"))
    repo = MssqlDiagnosticRepository(engine)
    await repo.verify_snapshot_readiness()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "desc"),
    [
        (0, "OFF"),
        (2, "IN_TRANSITION_TO_OFF"),
        (3, "IN_TRANSITION_TO_ON"),
    ],
)
async def test_snapshot_readiness_fails_closed_on_non_ready_states(state: int, desc: str) -> None:
    """States 0, 2, 3 fail closed with DATABASE_CONFIG_ERROR."""
    engine = _create_mock_engine(mock_cursor_result=(state, desc))
    repo = MssqlDiagnosticRepository(engine)

    with pytest.raises(DatabaseDiagnosticError) as exc_info:
        await repo.verify_snapshot_readiness()

    assert exc_info.value.error_code == "DATABASE_CONFIG_ERROR"
    assert exc_info.value.details["snapshot_isolation_state"] == state


@pytest.mark.asyncio
async def test_timeout_mapping_driver_hyt00() -> None:
    """Driver timeout with SQLSTATE HYT00 maps to DATABASE_TIMEOUT."""
    orig_exc = Exception("('HYT00', '[HYT00] [Microsoft][ODBC Driver 18]Query timeout expired')")
    orig_exc.args = ("HYT00", "Query timeout expired")
    dbapi_err = DBAPIError("SELECT 1", {}, orig_exc)

    engine = _create_mock_engine(side_effect=dbapi_err)
    repo = MssqlDiagnosticRepository(engine)

    with pytest.raises(DatabaseDiagnosticError) as exc_info:
        await repo.find_slow_queries(SlowQueryCriteriaDTO())

    assert exc_info.value.error_code == "DATABASE_TIMEOUT"
    assert exc_info.value.details["timeout_seconds"] == 5


@pytest.mark.asyncio
async def test_timeout_mapping_asyncio_timeout() -> None:
    """Asyncio TimeoutError maps to DATABASE_TIMEOUT."""
    engine = _create_mock_engine(side_effect=TimeoutError())
    repo = MssqlDiagnosticRepository(engine)

    with pytest.raises(DatabaseDiagnosticError) as exc_info:
        await repo.find_slow_queries(SlowQueryCriteriaDTO())

    assert exc_info.value.error_code == "DATABASE_TIMEOUT"


@pytest.mark.asyncio
async def test_permission_denied_mapping() -> None:
    """Database permission denial (SQLSTATE 42000 / 28000) maps to DATABASE_ACCESS_DENIED."""
    orig_exc = Exception("('42000', '[42000] Permission denied on DMV sys.dm_exec_query_stats')")
    orig_exc.args = ("42000", "Permission denied")
    dbapi_err = DBAPIError("SELECT 1", {}, orig_exc)

    engine = _create_mock_engine(side_effect=dbapi_err)
    repo = MssqlDiagnosticRepository(engine)

    with pytest.raises(DatabaseDiagnosticError) as exc_info:
        await repo.find_slow_queries(SlowQueryCriteriaDTO())

    assert exc_info.value.error_code == "DATABASE_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_connection_failure_mapping() -> None:
    """Connection failure (SQLSTATE 08001) maps to DATABASE_CONNECTION_FAILURE."""
    orig_exc = Exception("('08001', '[08001] Client unable to establish connection')")
    orig_exc.args = ("08001", "Client unable to establish connection")
    dbapi_err = DBAPIError("SELECT 1", {}, orig_exc)

    engine = _create_mock_engine(side_effect=dbapi_err)
    repo = MssqlDiagnosticRepository(engine)

    with pytest.raises(DatabaseDiagnosticError) as exc_info:
        await repo.find_slow_queries(SlowQueryCriteriaDTO())

    assert exc_info.value.error_code == "DATABASE_CONNECTION_FAILURE"


@pytest.mark.asyncio
async def test_get_database_health_success() -> None:
    """get_database_health returns healthy status, active connection count, and CONNECTED state."""
    engine = _create_mock_engine(mock_cursor_result=(12,))
    repo = MssqlDiagnosticRepository(engine)

    health = await repo.get_database_health()
    assert health.is_healthy is True
    assert health.status_summary == "ONLINE"
    assert health.active_connections == 12
    assert health.latency_ms > 0.0
    assert health.connectivity is not None
    assert health.connectivity.state == "CONNECTED"
    assert health.connectivity.observed_failure is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested_limit", "returned_rows", "expected_count", "expected_truncated"),
    [
        (None, 10, 10, False),
        (5, 5, 5, True),
        (50, 50, 50, True),
        (100, 50, 50, True),
        (500, 50, 50, True),
    ],
)
async def test_find_slow_queries_hard_row_cap(
    requested_limit: int | None,
    returned_rows: int,
    expected_count: int,
    expected_truncated: bool,
) -> None:
    """find_slow_queries respects 50-row hard cap and calculates is_truncated accurately."""
    dummy_rows = [
        (
            b"\x12\x34",  # query_hash
            2500,  # avg_duration_ms
            1200,  # avg_cpu_time_ms
            450,  # avg_logical_reads
            15,  # execution_count
            datetime.now(UTC),  # last_execution_time
            f"SELECT ticket_id FROM ticket WHERE id = {i}",  # query_excerpt
        )
        for i in range(returned_rows)
    ]
    engine = _create_mock_engine(mock_cursor_result=dummy_rows)
    repo = MssqlDiagnosticRepository(engine)

    criteria = SlowQueryCriteriaDTO(limit=requested_limit)
    result = await repo.find_slow_queries(criteria)

    assert result.returned_count == expected_count
    assert len(result.items) == expected_count
    assert result.is_truncated is expected_truncated
    assert result.total_matched is None


@pytest.mark.asyncio
async def test_find_slow_queries_metric_semantics() -> None:
    """Verify metrics represent average per-execution values."""
    synthetic_row = (
        b"\xab\xcd",  # query_hash
        2000,  # avg_duration_ms (20,000,000 us total / 10 / 1000)
        500,  # avg_cpu_time_ms (5,000,000 us total / 10 / 1000)
        2000,  # avg_logical_reads (20,000 total / 10)
        10,  # execution_count
        datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC),  # last_execution_time
        "SELECT id FROM customer WHERE status = 1",  # query_excerpt
    )
    engine = _create_mock_engine(mock_cursor_result=[synthetic_row])
    repo = MssqlDiagnosticRepository(engine)

    result = await repo.find_slow_queries(SlowQueryCriteriaDTO(min_duration_ms=1000))
    assert result.returned_count == 1
    item = result.items[0]
    assert item.duration_ms == 2000
    assert item.cpu_time_ms == 500
    assert item.logical_reads == 2000
    assert item.execution_count == 10
    assert item.summary == "SELECT id FROM customer WHERE status = 1"


@pytest.mark.asyncio
async def test_find_deadlocks_ring_buffer_parsing() -> None:
    """find_deadlocks relationalizes deadlock events and parses required DTO fields."""
    sample_deadlock_xml = """
    <event name="xml_deadlock_report" timestamp="2026-08-29T10:00:00.000Z">
      <data name="xml_report">
        <value>
          <deadlock>
            <victim-list>
              <victimProcess id="process1234"/>
            </victim-list>
            <process-list>
              <process id="process1234"/>
              <process id="process5678"/>
            </process-list>
            <resource-list>
              <pagelock objectname="SuperOffice.dbo.ticket"/>
            </resource-list>
          </deadlock>
        </value>
      </data>
    </event>
    """
    dummy_rows = [(datetime(2026, 8, 29, 10, 0, 0, tzinfo=UTC), sample_deadlock_xml)]
    engine = _create_mock_engine(mock_cursor_result=dummy_rows)
    repo = MssqlDiagnosticRepository(engine)

    result = await repo.find_deadlocks(DeadlockCriteriaDTO())
    assert result.returned_count == 1
    item = result.items[0]
    assert item.victim_session_id == 1234
    assert item.participating_session_count == 2
    assert "SuperOffice.dbo.ticket" in item.resource_description
    assert not hasattr(item, "event_xml")  # Raw XML must NOT be present on DTO


@pytest.mark.asyncio
async def test_find_blocking_sessions_success() -> None:
    """find_blocking_sessions returns active blocked sessions."""
    dummy_rows = [(52, 108, 15000, "LCK_M_X")]
    engine = _create_mock_engine(mock_cursor_result=dummy_rows)
    repo = MssqlDiagnosticRepository(engine)

    result = await repo.find_blocking_sessions(BlockingSessionCriteriaDTO())
    assert result.returned_count == 1
    assert result.items[0].blocked_session_id == 52
    assert result.items[0].blocking_session_id == 108
    assert result.items[0].wait_duration_ms == 15000
    assert result.items[0].wait_type == "LCK_M_X"


@pytest.mark.asyncio
async def test_get_ticket_diagnostic_record_success_with_activity() -> None:
    """get_ticket_diagnostic_record parses activity counts, timestamps, and actor correctly."""
    now = datetime(2026, 5, 24, 14, 8, 31, tzinfo=UTC)
    stats_row = (2, 5, datetime(2026, 5, 24, 10, 29, 44), datetime(2026, 5, 24, 14, 8, 31))
    actor_row = (datetime(2026, 5, 24, 14, 8, 31), "junaid.tariq")

    engine = _create_multi_query_engine([stats_row, actor_row])
    repo = MssqlDiagnosticRepository(engine)

    rec = await repo.get_ticket_diagnostic_record(TicketDiagnosticCriteriaDTO(ticket_id=5005))
    assert rec is not None
    assert rec.ticket_id == 5005
    assert rec.has_db_activity is True
    assert rec.last_activity_time == now
    assert "junaid.tariq" in rec.diagnostic_summary
    assert "2 lifecycle log entries" in rec.diagnostic_summary
    assert "5 logged actions" in rec.diagnostic_summary


@pytest.mark.asyncio
async def test_get_ticket_diagnostic_record_no_activity() -> None:
    """get_ticket_diagnostic_record returns has_db_activity=False when no rows exist."""
    stats_row = (0, 0, None, None)
    actor_row = None

    engine = _create_multi_query_engine([stats_row, actor_row])
    repo = MssqlDiagnosticRepository(engine)

    rec = await repo.get_ticket_diagnostic_record(TicketDiagnosticCriteriaDTO(ticket_id=9999))
    assert rec is not None
    assert rec.ticket_id == 9999
    assert rec.has_db_activity is False
    assert rec.last_activity_time is None
    assert "No database activity records found" in rec.diagnostic_summary


@pytest.mark.asyncio
async def test_backup_status_full_backup_exists() -> None:
    """Scenario A: Full backup exists and is correctly identified with server recorded time."""
    full_time = datetime(2026, 9, 10, 10, 0, 0)
    engine = _create_multi_query_engine(
        [
            (12,),  # active connections
            [("D", full_time)],  # backupset
        ]
    )
    repo = MssqlDiagnosticRepository(engine, database_name="SuperOffice")

    health = await repo.get_database_health()
    assert health.is_healthy is True
    assert health.status_summary == "ONLINE"
    assert health.backup_status is not None
    assert health.backup_status.backup_found is True
    assert health.backup_status.status == "AVAILABLE"
    assert health.backup_status.latest_backup_at == full_time
    assert health.backup_status.latest_backup_at.tzinfo is None
    assert health.backup_status.latest_backup_type == "FULL"
    assert health.backup_status.latest_full_backup_at == full_time
    assert health.backup_status.latest_full_backup_at.tzinfo is None
    assert health.backup_status.latest_differential_backup_at is None
    assert health.backup_status.latest_log_backup_at is None
    assert health.backup_status.error_message is None


@pytest.mark.asyncio
async def test_backup_status_full_diff_log_history() -> None:
    """Scenario B: Full + diff + log backup history with correct latest resolution."""
    full_time = datetime(2026, 9, 8, 2, 0, 0)
    diff_time = datetime(2026, 9, 9, 6, 0, 0)
    log_time = datetime(2026, 9, 10, 11, 45, 0)
    engine = _create_multi_query_engine(
        [
            (8,),
            [("L", log_time), ("I", diff_time), ("D", full_time)],
        ]
    )
    repo = MssqlDiagnosticRepository(engine, database_name="SuperOffice")

    health = await repo.get_database_health()
    assert health.backup_status is not None
    assert health.backup_status.backup_found is True
    assert health.backup_status.status == "AVAILABLE"
    assert health.backup_status.latest_backup_at == log_time
    assert health.backup_status.latest_backup_at.tzinfo is None
    assert health.backup_status.latest_backup_type == "LOG"
    assert health.backup_status.latest_full_backup_at == full_time
    assert health.backup_status.latest_differential_backup_at == diff_time
    assert health.backup_status.latest_log_backup_at == log_time


@pytest.mark.asyncio
async def test_backup_status_no_backup_history() -> None:
    """Scenario C: No backup history exists; backup_found is false, timestamps null."""
    engine = _create_multi_query_engine(
        [
            (5,),
            [],  # 0 backup rows
        ]
    )
    repo = MssqlDiagnosticRepository(engine, database_name="SuperOffice")

    health = await repo.get_database_health()
    assert health.is_healthy is True
    assert health.backup_status is not None
    assert health.backup_status.backup_found is False
    assert health.backup_status.status == "AVAILABLE"
    assert health.backup_status.latest_backup_at is None
    assert health.backup_status.latest_backup_type is None
    assert health.backup_status.latest_full_backup_at is None
    assert health.backup_status.latest_differential_backup_at is None
    assert health.backup_status.latest_log_backup_at is None
    assert health.backup_status.error_message is None


@pytest.mark.asyncio
async def test_backup_status_query_error_returns_unavailable() -> None:
    """Scenario D: SQL error does not fabricate 'no backup' but reports UNAVAILABLE."""
    # 1. Permission denied error
    orig_perm = Exception(
        "('42000', '[42000] [Microsoft][ODBC Driver 18]SELECT permission was denied')"
    )
    orig_perm.args = ("42000", "SELECT permission was denied")
    dbapi_perm = DBAPIError("SELECT ...", {}, orig_perm)

    engine_perm = _create_multi_query_engine([(10,), dbapi_perm])
    repo_perm = MssqlDiagnosticRepository(engine_perm, database_name="SuperOffice")

    health_perm = await repo_perm.get_database_health()
    assert health_perm.is_healthy is True
    assert health_perm.status_summary == "ONLINE"
    assert health_perm.backup_status is not None
    assert health_perm.backup_status.backup_found is None  # Safe: not false!
    assert health_perm.backup_status.status == "UNAVAILABLE"
    assert health_perm.backup_status.error_message is not None
    assert "permission denied" in health_perm.backup_status.error_message.lower()

    # 2. Query timeout during backup query
    engine_timeout = _create_multi_query_engine([(10,), TimeoutError()])
    repo_timeout = MssqlDiagnosticRepository(engine_timeout, database_name="SuperOffice")

    health_timeout = await repo_timeout.get_database_health()
    assert health_timeout.is_healthy is True
    assert health_timeout.backup_status is not None
    assert health_timeout.backup_status.backup_found is None
    assert health_timeout.backup_status.status == "UNAVAILABLE"
    assert health_timeout.backup_status.error_message is not None
    assert "timed out" in health_timeout.backup_status.error_message.lower()


@pytest.mark.asyncio
async def test_backup_type_mapping_and_order() -> None:
    """Scenario E: Correct backup type mapping and timestamp resolution with differential newest."""
    full_time = datetime(2026, 9, 9, 2, 0, 0)
    diff_time = datetime(2026, 9, 10, 8, 0, 0)
    file_time = datetime(2026, 9, 7, 1, 0, 0)

    engine = _create_multi_query_engine(
        [
            (6,),
            [("I", diff_time), ("D", full_time), ("F", file_time)],
        ]
    )
    repo = MssqlDiagnosticRepository(engine, database_name="SuperOffice")

    health = await repo.get_database_health()
    assert health.backup_status is not None
    assert health.backup_status.backup_found is True
    # Differential is newer than full
    assert health.backup_status.latest_backup_at == diff_time
    assert health.backup_status.latest_backup_at.tzinfo is None
    assert health.backup_status.latest_backup_type == "DIFFERENTIAL"
    assert health.backup_status.latest_full_backup_at == full_time
    assert health.backup_status.latest_full_backup_at.tzinfo is None
    assert health.backup_status.latest_differential_backup_at == diff_time

    # Verify that if a driver or mock supplies a tz-aware datetime, tzinfo is safely stripped
    tz_aware_time = datetime(2026, 9, 10, 8, 0, 0, tzinfo=UTC)
    engine_tz = _create_multi_query_engine(
        [
            (6,),
            [("D", tz_aware_time)],
        ]
    )
    repo_tz = MssqlDiagnosticRepository(engine_tz, database_name="SuperOffice")
    health_tz = await repo_tz.get_database_health()
    assert health_tz.backup_status is not None
    assert health_tz.backup_status.latest_backup_at is not None
    assert health_tz.backup_status.latest_backup_at.tzinfo is None
    assert health_tz.backup_status.latest_backup_at == datetime(2026, 9, 10, 8, 0, 0)


def test_static_sql_safety_invariants() -> None:
    """Verify that no prohibited SQL patterns exist in MssqlDiagnosticRepository methods."""
    source = inspect.getsource(mssql_repository)

    # Invariant 1: No SELECT *
    assert "SELECT *" not in source.upper()

    # Invariant 2: No table-level NOLOCK
    assert "NOLOCK" not in source.upper()

    # Invariant 3: No READ UNCOMMITTED
    assert "READ UNCOMMITTED" not in source.upper()

    # Invariant 4: No ALTER DATABASE
    assert "ALTER DATABASE" not in source.upper()


# ============================================================================
# Focused MSSQL Connectivity Diagnosis Tests
# ============================================================================


@pytest.mark.asyncio
async def test_connectivity_connected() -> None:
    """1. CONNECTED: Healthy database connection and required health query succeeded."""
    engine = _create_mock_engine(mock_cursor_result=(7,))
    repo = MssqlDiagnosticRepository(engine, host="127.0.0.1", port=1433)

    with (
        patch("asyncio.open_connection", AsyncMock()) as mock_tcp,
        patch("socket.getaddrinfo") as mock_dns,
    ):
        health = await repo.get_database_health()
        mock_tcp.assert_not_called()
        mock_dns.assert_not_called()

    assert health.is_healthy is True
    assert health.status_summary == "ONLINE"
    assert health.active_connections == 7
    assert health.connectivity is not None
    assert health.connectivity.state == "CONNECTED"
    assert health.connectivity.observed_failure is None


@pytest.mark.asyncio
async def test_connectivity_dns_resolution_failure() -> None:
    """Hostname resolution failure maps to DNS_RESOLUTION_FAILURE without raw leak."""
    engine = MagicMock()
    engine.connect = MagicMock(
        side_effect=OperationalError("conn failed", {}, Exception("Connect error"))
    )
    repo = MssqlDiagnosticRepository(engine, host="sql.unresolvable.invalid", port=1433)

    with patch("asyncio.get_running_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = AsyncMock(
            side_effect=socket.gaierror(-2, "Name or service not known")
        )
        health = await repo.get_database_health()

    assert health.is_healthy is False
    assert health.status_summary == "UNAVAILABLE"
    assert health.active_connections == 0
    assert health.backup_status is not None
    assert health.backup_status.status == "UNAVAILABLE"
    assert health.backup_status.backup_found is None
    assert health.connectivity is not None
    assert health.connectivity.state == "DNS_RESOLUTION_FAILURE"
    assert health.connectivity.observed_failure == "Failed to resolve configured database hostname."
    assert "gaierror" not in str(health.connectivity.observed_failure)
    assert "Name or service" not in str(health.connectivity.observed_failure)


@pytest.mark.asyncio
async def test_connectivity_tcp_connectivity_failure() -> None:
    """TCP connection refusal maps to TCP_CONNECTIVITY_FAILURE."""
    engine = MagicMock()
    engine.connect = MagicMock(
        side_effect=OperationalError("conn failed", {}, Exception("Connect error"))
    )
    repo = MssqlDiagnosticRepository(engine, host="127.0.0.1", port=1433)

    with patch(
        "asyncio.open_connection",
        AsyncMock(side_effect=ConnectionRefusedError("Connection refused")),
    ):
        health = await repo.get_database_health()

    assert health.is_healthy is False
    assert health.status_summary == "UNAVAILABLE"
    assert health.connectivity is not None
    assert health.connectivity.state == "TCP_CONNECTIVITY_FAILURE"
    assert health.connectivity.observed_failure == (
        "Failed to establish TCP connection to configured database endpoint."
    )
    assert "refused" not in str(health.connectivity.observed_failure).lower()


@pytest.mark.asyncio
async def test_connectivity_tcp_connectivity_timeout() -> None:
    """TCP timeout maps to TCP_CONNECTIVITY_TIMEOUT."""
    engine = MagicMock()
    engine.connect = MagicMock(
        side_effect=OperationalError("conn failed", {}, Exception("Connect error"))
    )
    repo = MssqlDiagnosticRepository(engine, host="127.0.0.1", port=1433)

    with patch("asyncio.open_connection", AsyncMock(side_effect=TimeoutError("TCP timed out"))):
        health = await repo.get_database_health()

    assert health.is_healthy is False
    assert health.status_summary == "UNAVAILABLE"
    assert health.connectivity is not None
    assert health.connectivity.state == "TCP_CONNECTIVITY_TIMEOUT"
    assert health.connectivity.observed_failure == (
        "TCP connection attempt to configured database endpoint timed out."
    )


@pytest.mark.asyncio
async def test_connectivity_database_authentication_failure() -> None:
    """SQLSTATE 28000 login failure maps to DATABASE_AUTHENTICATION_FAILURE without leak."""
    orig = Exception("('28000', '[28000] Login failed for user admin_user with secret_pass')")
    orig.args = ("28000", "Login failed for user admin_user")
    dbapi_err = DBAPIError("CONNECT", {}, orig)

    engine = MagicMock()
    engine.connect = MagicMock(side_effect=dbapi_err)
    repo = MssqlDiagnosticRepository(engine, host="127.0.0.1", port=1433)

    with patch("asyncio.open_connection", AsyncMock()) as mock_tcp:
        health = await repo.get_database_health()
        mock_tcp.assert_not_called()

    assert health.is_healthy is False
    assert health.status_summary == "UNAVAILABLE"
    assert health.connectivity is not None
    assert health.connectivity.state == "DATABASE_AUTHENTICATION_FAILURE"
    assert health.connectivity.observed_failure == (
        "Database authentication failed for configured credentials."
    )
    assert "admin_user" not in str(health.connectivity.observed_failure)
    assert "secret_pass" not in str(health.connectivity.observed_failure)
    assert "28000" not in str(health.connectivity.observed_failure)


@pytest.mark.asyncio
async def test_connectivity_database_connection_failure() -> None:
    """TCP succeeds but handshake/protocol fails maps to DATABASE_CONNECTION_FAILURE."""
    engine = MagicMock()
    engine.connect = MagicMock(
        side_effect=OperationalError(
            "TLS negotiation failed with key_material_123", {}, Exception()
        )
    )
    repo = MssqlDiagnosticRepository(engine, host="127.0.0.1", port=1433)

    mock_writer = MagicMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()
    with patch("asyncio.open_connection", AsyncMock(return_value=(AsyncMock(), mock_writer))):
        health = await repo.get_database_health()

    mock_writer.close.assert_called_once()
    assert health.is_healthy is False
    assert health.status_summary == "UNAVAILABLE"
    assert health.connectivity is not None
    assert health.connectivity.state == "DATABASE_CONNECTION_FAILURE"
    assert health.connectivity.observed_failure == (
        "Database client failed to establish connection to database endpoint."
    )
    assert "key_material_123" not in str(health.connectivity.observed_failure)


@pytest.mark.asyncio
async def test_connectivity_database_connection_timeout() -> None:
    """TCP succeeds but DB connection attempt times out maps to DATABASE_CONNECTION_TIMEOUT."""
    engine = MagicMock()
    engine.connect = MagicMock(side_effect=SaTimeoutError("QueuePool timeout"))
    repo = MssqlDiagnosticRepository(engine, host="127.0.0.1", port=1433)

    mock_writer = MagicMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()
    with patch("asyncio.open_connection", AsyncMock(return_value=(AsyncMock(), mock_writer))):
        health = await repo.get_database_health()

    assert health.is_healthy is False
    assert health.status_summary == "UNAVAILABLE"
    assert health.connectivity is not None
    assert health.connectivity.state == "DATABASE_CONNECTION_TIMEOUT"
    assert health.connectivity.observed_failure == "Database connection attempt timed out."


@pytest.mark.asyncio
async def test_connectivity_database_query_failure() -> None:
    """Connection succeeds but health query execution fails maps to DATABASE_QUERY_FAILURE."""
    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(
        side_effect=DBAPIError("SELECT COUNT...", {}, Exception("DMV internal error"))
    )

    engine = MagicMock()
    engine.connect = MagicMock(return_value=mock_conn)
    repo = MssqlDiagnosticRepository(engine, host="127.0.0.1", port=1433)

    with patch("asyncio.open_connection", AsyncMock()) as mock_tcp:
        health = await repo.get_database_health()
        mock_tcp.assert_not_called()

    assert health.is_healthy is False
    assert health.status_summary == "DEGRADED"
    assert health.connectivity is not None
    assert health.connectivity.state == "DATABASE_QUERY_FAILURE"
    assert health.connectivity.observed_failure == "Database health diagnostic query failed."
    assert "DMV internal error" not in str(health.connectivity.observed_failure)


@pytest.mark.asyncio
async def test_connectivity_database_query_timeout() -> None:
    """Connection succeeds but health query execution times out maps to DATABASE_QUERY_TIMEOUT."""
    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=None)
    mock_conn.execute = AsyncMock(side_effect=TimeoutError("Statement timed out"))

    engine = MagicMock()
    engine.connect = MagicMock(return_value=mock_conn)
    repo = MssqlDiagnosticRepository(engine, host="127.0.0.1", port=1433)

    with patch("asyncio.open_connection", AsyncMock()) as mock_tcp:
        health = await repo.get_database_health()
        mock_tcp.assert_not_called()

    assert health.is_healthy is False
    assert health.status_summary == "DEGRADED"
    assert health.connectivity is not None
    assert health.connectivity.state == "DATABASE_QUERY_TIMEOUT"
    assert health.connectivity.observed_failure == "Database health diagnostic query timed out."


@pytest.mark.asyncio
async def test_connectivity_safe_unknown_fallback() -> None:
    """Direct test of repo._diagnose_connection_failure when unexpected error occurs."""
    engine = MagicMock()
    repo = MssqlDiagnosticRepository(engine, host="127.0.0.1", port=1433)

    with patch("ipaddress.ip_address", side_effect=TypeError("Unexpected type")):
        conn_dto = await repo._diagnose_connection_failure(Exception("connect err"))
        assert conn_dto.state == "UNKNOWN"
        assert conn_dto.observed_failure == (
            "An unclassified failure occurred during database connectivity diagnosis."
        )


@pytest.mark.asyncio
async def test_connectivity_probes_configured_host_port_only() -> None:
    """TCP probe strictly targets configured host and port, never arbitrary ports."""
    engine = MagicMock()
    engine.connect = MagicMock(side_effect=OperationalError("conn failed", {}, Exception()))
    repo = MssqlDiagnosticRepository(engine, host="10.10.10.10", port=14333)

    with patch(
        "asyncio.open_connection",
        AsyncMock(side_effect=ConnectionRefusedError()),
    ) as mock_tcp:
        await repo.get_database_health()
        mock_tcp.assert_called_once_with("10.10.10.10", 14333)


def test_no_caller_controlled_probe_destination() -> None:
    """Verify get_database_health signature accepts no caller-controlled network parameters."""
    engine = MagicMock()
    repo = MssqlDiagnosticRepository(engine)
    sig = inspect.signature(repo.get_database_health)
    assert len(sig.parameters) == 0


@pytest.mark.asyncio
async def test_healthy_call_does_not_execute_fallback_probes() -> None:
    """Healthy call does not execute DNS or TCP fallback probes."""
    engine = _create_mock_engine(mock_cursor_result=(5,))
    repo = MssqlDiagnosticRepository(engine, host="db.acme.no", port=1433)

    with (
        patch("asyncio.open_connection", AsyncMock()) as mock_tcp,
        patch("socket.getaddrinfo") as mock_dns,
    ):
        health = await repo.get_database_health()
        mock_tcp.assert_not_called()
        mock_dns.assert_not_called()

    assert health.is_healthy is True
    assert health.connectivity is not None
    assert health.connectivity.state == "CONNECTED"


@pytest.mark.asyncio
async def test_db_unavailable_does_not_fabricate_facts() -> None:
    """16. When DB is unavailable, active connections and backup status are not fabricated."""
    engine = MagicMock()
    engine.connect = MagicMock(side_effect=OperationalError("conn failed", {}, Exception()))
    repo = MssqlDiagnosticRepository(engine, host="127.0.0.1", port=1433)

    with patch("asyncio.open_connection", AsyncMock(side_effect=ConnectionRefusedError())):
        health = await repo.get_database_health()

    assert health.is_healthy is False
    assert health.active_connections == 0
    assert health.backup_status is not None
    assert health.backup_status.status == "UNAVAILABLE"
    assert health.backup_status.backup_found is None
    assert health.backup_status.latest_backup_at is None
    assert health.backup_status.latest_backup_type is None


@pytest.mark.asyncio
async def test_connectivity_raw_messages_not_exposed() -> None:
    """11. Raw ODBC/DBAPI messages and credentials are not exposed in observed_failure."""
    sensitive_server = "prod-sql-cluster.internal.corp"
    sensitive_user = "sa_superoffice"
    sensitive_pw = "SuperSecretP@ssw0rd!123"
    raw_odbc = (
        f"[Microsoft][ODBC Driver 18 for SQL Server][SQL Server]"
        f"Cannot open database 'SuperOffice' requested by the login for user '{sensitive_user}' "
        f"on server '{sensitive_server}' with pwd '{sensitive_pw}' (SQLSTATE 28000, error 18456)"
    )
    orig_exc = Exception(raw_odbc)
    orig_exc.args = ("28000", raw_odbc)
    dbapi_err = DBAPIError("CONNECT", {}, orig_exc)

    engine = MagicMock()
    engine.connect = MagicMock(side_effect=dbapi_err)
    repo = MssqlDiagnosticRepository(engine, host="127.0.0.1", port=1433)

    health = await repo.get_database_health()
    assert health.is_healthy is False
    assert health.connectivity is not None
    assert health.connectivity.observed_failure is not None
    obs = health.connectivity.observed_failure
    assert sensitive_server not in obs
    assert sensitive_user not in obs
    assert sensitive_pw not in obs
    assert "28000" not in obs
    assert "18456" not in obs
    assert "ODBC Driver" not in obs
    assert obs == "Database authentication failed for configured credentials."


@pytest.mark.asyncio
async def test_connectivity_ip_target_skips_dns_resolution() -> None:
    """If configured target is already an IP address, do not invent a DNS failure stage."""
    engine = MagicMock()
    engine.connect = MagicMock(side_effect=OperationalError("conn failed", {}, Exception()))
    repo = MssqlDiagnosticRepository(engine, host="192.168.1.50", port=1433)

    with (
        patch("socket.getaddrinfo") as mock_dns,
        patch("asyncio.open_connection", AsyncMock(side_effect=ConnectionRefusedError())),
    ):
        health = await repo.get_database_health()
        mock_dns.assert_not_called()

    assert health.connectivity is not None
    assert health.connectivity.state == "TCP_CONNECTIVITY_FAILURE"


@pytest.mark.asyncio
async def test_connectivity_backup_behavior_remains_unchanged_on_healthy_call() -> None:
    """15. Backup behavior remains unchanged on healthy calls: recorded times, types, status."""
    full_time = datetime(2026, 9, 9, 2, 0, 0)
    engine = _create_multi_query_engine(
        [
            (4,),
            [("D", full_time)],
        ]
    )
    repo = MssqlDiagnosticRepository(engine, database_name="SuperOffice")
    health = await repo.get_database_health()

    assert health.is_healthy is True
    assert health.connectivity is not None
    assert health.connectivity.state == "CONNECTED"
    assert health.backup_status is not None
    assert health.backup_status.status == "AVAILABLE"
    assert health.backup_status.backup_found is True
    assert health.backup_status.latest_backup_type == "FULL"
    assert health.backup_status.latest_full_backup_at == full_time
    assert health.backup_status.latest_full_backup_at.tzinfo is None
