"""Unit tests for MssqlDiagnosticRepository offline operation and error boundaries."""

import inspect
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import DBAPIError

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
        await repo.get_database_health()

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
        await repo.get_database_health()

    assert exc_info.value.error_code == "DATABASE_CONNECTION_FAILURE"


@pytest.mark.asyncio
async def test_get_database_health_success() -> None:
    """get_database_health returns healthy status and active connection count."""
    engine = _create_mock_engine(mock_cursor_result=(12,))
    repo = MssqlDiagnosticRepository(engine)

    health = await repo.get_database_health()
    assert health.is_healthy is True
    assert health.status_summary == "ONLINE"
    assert health.active_connections == 12
    assert health.latency_ms > 0.0


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
async def test_get_ticket_diagnostic_record_fails_closed_unconfigured() -> None:
    """get_ticket_diagnostic_record raises DIAGNOSTIC_SCHEMA_NOT_CONFIGURED."""
    engine = _create_mock_engine()
    repo = MssqlDiagnosticRepository(engine)

    with pytest.raises(DatabaseDiagnosticError) as exc_info:
        await repo.get_ticket_diagnostic_record(TicketDiagnosticCriteriaDTO(ticket_id=5005))

    assert exc_info.value.error_code == "DIAGNOSTIC_SCHEMA_NOT_CONFIGURED"
    assert exc_info.value.details["ticket_id"] == 5005


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
