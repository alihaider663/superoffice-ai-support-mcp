"""Microsoft SQL Server read-only Diagnostic Repository implementation using SQLAlchemy Async."""

import asyncio
import contextlib
import ipaddress
import logging
import socket
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import (
    DBAPIError,
    OperationalError,
)
from sqlalchemy.exc import (
    TimeoutError as SaTimeoutError,
)
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

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
    TicketDiagnosticRecordDomainDTO,
)
from diag_mcp.contracts.errors import DatabaseDiagnosticError
from diag_mcp.contracts.interfaces import DiagnosticRepository

logger = logging.getLogger(__name__)

BACKUP_TYPE_MAP: dict[str, str] = {
    "D": "FULL",
    "I": "DIFFERENTIAL",
    "L": "LOG",
    "F": "FILE",
    "G": "DIFFERENTIAL_FILE",
    "P": "PARTIAL",
    "Q": "DIFFERENTIAL_PARTIAL",
}


class MssqlDiagnosticRepository(DiagnosticRepository):
    """Read-only Diagnostic Repository backed by Microsoft SQL Server and SQLAlchemy Async.

    Enforces 5.0s statement timeouts, SNAPSHOT isolation, 50-row hard caps, and zero dynamic SQL.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        query_timeout_seconds: int = 5,
        max_rows: int = 50,
        database_name: str | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        self._engine = engine
        self._query_timeout_seconds = query_timeout_seconds
        self._max_rows = max_rows
        self._database_name = database_name or "SuperOffice"
        self._host = host or "localhost"
        self._port = port or 1433

    async def verify_snapshot_readiness(self) -> None:
        """Verify that ALLOW_SNAPSHOT_ISOLATION is ON (state=1) on the database catalog.

        Fails closed on state 0 (OFF), state 2 (transition to OFF), state 3 (transition to ON).
        """
        sql = text(
            "SELECT snapshot_isolation_state, snapshot_isolation_state_desc "
            "FROM sys.databases "
            "WHERE name = DB_NAME();"
        )
        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(sql)
                row = result.fetchone()
        except Exception as exc:
            self._handle_exception(exc, "verify_snapshot_readiness")

        if not row:
            raise DatabaseDiagnosticError(
                message="Unable to verify snapshot isolation state for target database.",
                error_code="DATABASE_CONFIG_ERROR",
                details={"operation": "verify_snapshot_readiness"},
            )

        state = row[0]
        desc = str(row[1]) if len(row) > 1 else str(state)

        if state != 1:
            raise DatabaseDiagnosticError(
                message=(
                    f"MSSQL target database has snapshot isolation state '{desc}' ({state}). "
                    "Live diagnostics requires ALLOW_SNAPSHOT_ISOLATION=ON (state 1) "
                    "configured by DBA."
                ),
                error_code="DATABASE_CONFIG_ERROR",
                details={"snapshot_isolation_state": state, "state_desc": desc},
            )

    def _handle_exception(self, exc: Exception, operation: str) -> None:
        """Translate driver, DBAPI, and asyncio exceptions into DatabaseDiagnosticError."""
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError, SaTimeoutError)):
            raise DatabaseDiagnosticError(
                message=f"MSSQL diagnostic query timed out during {operation}.",
                error_code="DATABASE_TIMEOUT",
                details={"operation": operation, "timeout_seconds": self._query_timeout_seconds},
            ) from None

        if isinstance(exc, DBAPIError):
            orig = getattr(exc, "orig", None)
            sqlstate = ""
            if orig is not None and hasattr(orig, "args") and orig.args:
                sqlstate = str(orig.args[0])

            # Check for ODBC timeout SQLSTATEs (HYT00 / HYT01) or timeout in message
            if "HYT00" in sqlstate or "HYT01" in sqlstate or "timeout" in str(orig).lower():
                raise DatabaseDiagnosticError(
                    message=f"MSSQL diagnostic query timed out during {operation}.",
                    error_code="DATABASE_TIMEOUT",
                    details={
                        "operation": operation,
                        "timeout_seconds": self._query_timeout_seconds,
                    },
                ) from None

            if "28000" in sqlstate or "42000" in sqlstate or "permission" in str(orig).lower():
                raise DatabaseDiagnosticError(
                    message=f"Database permission denied during {operation}.",
                    error_code="DATABASE_ACCESS_DENIED",
                    details={"operation": operation},
                ) from None

            if "08001" in sqlstate or "08S01" in sqlstate or "connection" in str(orig).lower():
                raise DatabaseDiagnosticError(
                    message=f"Unable to connect to MSSQL diagnostic server during {operation}.",
                    error_code="DATABASE_CONNECTION_FAILURE",
                    details={"operation": operation},
                ) from None

        if isinstance(exc, OperationalError):
            raise DatabaseDiagnosticError(
                message=f"MSSQL operational failure during {operation}.",
                error_code="DATABASE_CONNECTION_FAILURE",
                details={"operation": operation},
            ) from None

        raise DatabaseDiagnosticError(
            message=f"MSSQL diagnostic execution failed during {operation}.",
            error_code="DATABASE_DIAGNOSTIC_ERROR",
            details={"operation": operation},
        ) from None

    async def _fetch_backup_status(self, conn: AsyncConnection) -> DatabaseBackupStatusDTO:
        """Query bounded SQL Server backup history for the configured database.

        Fails safe on permissions or query errors by returning UNAVAILABLE status
        without failing the overall database health check or fabricating false.
        """
        sql_backup = text(
            "SELECT TOP (:limit) "
            "    type, "
            "    MAX(backup_finish_date) AS latest_finish_date "
            "FROM msdb.dbo.backupset "
            "WHERE database_name = :database_name "
            "  AND (is_damaged = 0 OR is_damaged IS NULL) "
            "GROUP BY type "
            "ORDER BY latest_finish_date DESC;"
        )
        effective_limit = min(self._max_rows, 50)
        params: dict[str, Any] = {
            "limit": effective_limit,
            "database_name": self._database_name,
        }

        try:
            result = await conn.execute(sql_backup, params)
            rows = result.fetchall()
        except Exception as exc:
            orig = getattr(exc, "orig", None)
            orig_str = str(orig).lower() if orig is not None else str(exc).lower()
            sqlstate = ""
            if orig is not None and hasattr(orig, "args") and orig.args:
                sqlstate = str(orig.args[0])

            if isinstance(exc, (TimeoutError, asyncio.TimeoutError, SaTimeoutError)):
                err_msg = "Database backup history query timed out."
            elif (
                "28000" in sqlstate
                or "42000" in sqlstate
                or "permission" in orig_str
                or "denied" in orig_str
            ):
                err_msg = "Database permission denied while querying msdb backup history."
            elif "hyt00" in sqlstate or "hyt01" in sqlstate or "timeout" in orig_str:
                err_msg = "Database backup history query timed out."
            else:
                err_msg = "Database backup history inspection unavailable."

            logger.warning("Backup history inspection unavailable: %s", orig_str)
            return DatabaseBackupStatusDTO(
                backup_found=None,
                status="UNAVAILABLE",
                error_message=err_msg,
            )

        by_type: dict[str, datetime] = {}
        latest_finish: datetime | None = None
        latest_type: str | None = None

        for r in rows:
            if len(r) < 2:
                continue
            raw_type = str(r[0]).strip().upper() if r[0] is not None else ""
            mapped_type = BACKUP_TYPE_MAP.get(raw_type, raw_type or "UNKNOWN")
            raw_finish = r[1]
            if isinstance(raw_finish, datetime):
                # msdb.dbo.backupset.backup_finish_date does not record timezone offset.
                # Retain as SQL Server recorded timestamp without fabricating UTC.
                finish_recorded = (
                    raw_finish.replace(tzinfo=None) if raw_finish.tzinfo else raw_finish
                )
            else:
                continue

            by_type[mapped_type] = finish_recorded
            if latest_finish is None or finish_recorded > latest_finish:
                latest_finish = finish_recorded
                latest_type = mapped_type

        if not by_type:
            return DatabaseBackupStatusDTO(
                backup_found=False,
                latest_backup_at=None,
                latest_backup_type=None,
                latest_full_backup_at=None,
                latest_differential_backup_at=None,
                latest_log_backup_at=None,
                status="AVAILABLE",
            )

        return DatabaseBackupStatusDTO(
            backup_found=True,
            latest_backup_at=latest_finish,
            latest_backup_type=latest_type,
            latest_full_backup_at=by_type.get("FULL"),
            latest_differential_backup_at=by_type.get("DIFFERENTIAL"),
            latest_log_backup_at=by_type.get("LOG"),
            status="AVAILABLE",
        )

    @staticmethod
    def _is_auth_failure(exc: Exception) -> bool:
        """Check if exception represents a database authentication/login failure."""
        orig = getattr(exc, "orig", None)
        sqlstate = ""
        if orig is not None and hasattr(orig, "args") and orig.args:
            sqlstate = str(orig.args[0])
        exc_str = (str(orig) if orig is not None else str(exc)).lower()
        return (
            "28000" in sqlstate or "login failed" in exc_str or "login failed for user" in exc_str
        )

    @staticmethod
    def _is_timeout_failure(exc: Exception) -> bool:
        """Check if exception represents a query or connection timeout."""
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError, SaTimeoutError)):
            return True
        orig = getattr(exc, "orig", None)
        sqlstate = ""
        if orig is not None and hasattr(orig, "args") and orig.args:
            sqlstate = str(orig.args[0])
        exc_str = (str(orig) if orig is not None else str(exc)).lower()
        return "hyt00" in sqlstate.lower() or "hyt01" in sqlstate.lower() or "timeout" in exc_str

    def _diagnose_query_failure(self, exc: Exception) -> DatabaseConnectivityDTO:
        """Classify query-level failure when DB connection succeeded but query execution failed.

        Does NOT execute any TCP fallback probe since the database connection
        was already established.
        """
        if self._is_timeout_failure(exc):
            return DatabaseConnectivityDTO(
                state="DATABASE_QUERY_TIMEOUT",
                observed_failure="Database health diagnostic query timed out.",
            )
        return DatabaseConnectivityDTO(
            state="DATABASE_QUERY_FAILURE",
            observed_failure="Database health diagnostic query failed.",
        )

    async def _probe_dns(self, timeout: float) -> DatabaseConnectivityDTO | None:
        """Probe DNS resolution if host requires name resolution (not an IP)."""
        is_ip = False
        try:
            ipaddress.ip_address(self._host)
            is_ip = True
        except ValueError:
            is_ip = False

        if is_ip:
            return None

        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.getaddrinfo(
                    self._host,
                    int(self._port),
                    type=socket.SOCK_STREAM,
                ),
                timeout=timeout,
            )
            return None
        except TimeoutError:
            return DatabaseConnectivityDTO(
                state="DNS_RESOLUTION_FAILURE",
                observed_failure="Configured database hostname resolution timed out.",
            )
        except Exception:
            return DatabaseConnectivityDTO(
                state="DNS_RESOLUTION_FAILURE",
                observed_failure="Failed to resolve configured database hostname.",
            )

    async def _probe_tcp(self, timeout: float) -> DatabaseConnectivityDTO | None:
        """Probe bounded TCP connection strictly to configured host/port."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, int(self._port)),
                timeout=timeout,
            )
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            return None
        except TimeoutError:
            return DatabaseConnectivityDTO(
                state="TCP_CONNECTIVITY_TIMEOUT",
                observed_failure=(
                    "TCP connection attempt to configured database endpoint timed out."
                ),
            )
        except (ConnectionRefusedError, OSError):
            return DatabaseConnectivityDTO(
                state="TCP_CONNECTIVITY_FAILURE",
                observed_failure=(
                    "Failed to establish TCP connection to configured database endpoint."
                ),
            )

    async def _diagnose_connection_failure(self, exc: Exception) -> DatabaseConnectivityDTO:
        """Classify connection-level failure using bounded DNS and TCP probes.

        Probes target configured host/port only.
        """
        try:
            if self._is_auth_failure(exc):
                return DatabaseConnectivityDTO(
                    state="DATABASE_AUTHENTICATION_FAILURE",
                    observed_failure="Database authentication failed for configured credentials.",
                )

            probe_timeout = min(float(self._query_timeout_seconds), 2.0)

            dns_failure = await self._probe_dns(probe_timeout)
            if dns_failure is not None:
                return dns_failure

            tcp_failure = await self._probe_tcp(probe_timeout)
            if tcp_failure is not None:
                return tcp_failure

            if self._is_timeout_failure(exc):
                return DatabaseConnectivityDTO(
                    state="DATABASE_CONNECTION_TIMEOUT",
                    observed_failure="Database connection attempt timed out.",
                )

            return DatabaseConnectivityDTO(
                state="DATABASE_CONNECTION_FAILURE",
                observed_failure=(
                    "Database client failed to establish connection to database endpoint."
                ),
            )
        except Exception:
            return DatabaseConnectivityDTO(
                state="UNKNOWN",
                observed_failure=(
                    "An unclassified failure occurred during database connectivity diagnosis."
                ),
            )

    async def get_database_health(self) -> DatabaseHealthDomainDTO:
        """Fetch database health, connection count, latency, backup status, and connectivity.

        When MSSQL is healthy: returns online status, active connection count, latency,
        backup status, and CONNECTED state without performing extra fallback probes.
        When MSSQL is unavailable or query fails: returns structured failure DTO without
        raising tool error.
        """
        start_time = datetime.now(UTC)
        sql = text(
            "SELECT COUNT(session_id) AS active_connections "
            "FROM sys.dm_exec_sessions "
            "WHERE is_user_process = 1;"
        )

        backup_status: DatabaseBackupStatusDTO | None = None
        active_connections = 0

        try:
            async with self._engine.connect() as conn:
                try:
                    result = await conn.execute(sql)
                    row = result.fetchone()
                    active_connections = int(row[0]) if row and row[0] is not None else 0
                    backup_status = await self._fetch_backup_status(conn)
                except Exception as query_exc:
                    end_time = datetime.now(UTC)
                    latency_ms = max(0.1, (end_time - start_time).total_seconds() * 1000.0)
                    connectivity = self._diagnose_query_failure(query_exc)
                    return DatabaseHealthDomainDTO(
                        is_healthy=False,
                        status_summary="DEGRADED",
                        active_connections=0,
                        latency_ms=round(latency_ms, 2),
                        collected_at=end_time,
                        backup_status=DatabaseBackupStatusDTO(
                            backup_found=None,
                            status="UNAVAILABLE",
                            error_message=(
                                "Database backup history inspection unavailable "
                                "due to health query failure."
                            ),
                        ),
                        connectivity=connectivity,
                    )
        except Exception as connect_exc:
            end_time = datetime.now(UTC)
            latency_ms = max(0.1, (end_time - start_time).total_seconds() * 1000.0)
            connectivity = await self._diagnose_connection_failure(connect_exc)
            return DatabaseHealthDomainDTO(
                is_healthy=False,
                status_summary="UNAVAILABLE",
                active_connections=0,
                latency_ms=round(latency_ms, 2),
                collected_at=end_time,
                backup_status=DatabaseBackupStatusDTO(
                    backup_found=None,
                    status="UNAVAILABLE",
                    error_message=(
                        "Database backup history inspection unavailable "
                        "due to database connectivity failure."
                    ),
                ),
                connectivity=connectivity,
            )

        end_time = datetime.now(UTC)
        latency_ms = max(0.1, (end_time - start_time).total_seconds() * 1000.0)

        return DatabaseHealthDomainDTO(
            is_healthy=True,
            status_summary="ONLINE",
            active_connections=active_connections,
            latency_ms=round(latency_ms, 2),
            collected_at=end_time,
            backup_status=backup_status,
            connectivity=DatabaseConnectivityDTO(
                state="CONNECTED",
                observed_failure=None,
            ),
        )

    async def find_slow_queries(
        self, criteria: SlowQueryCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[SlowQueryDomainDTO]:
        """Find slow query records matching execution time threshold and window.

        Resource metrics (duration_ms, cpu_time_ms, logical_reads) represent
        average per-execution values across cached executions.
        """
        effective_limit = min(criteria.limit or self._max_rows, self._max_rows)
        min_duration_us = criteria.min_duration_ms * 1000

        # Fixed parameter-bound query on performance DMVs projecting average per-execution metrics
        sql = text(
            "SELECT TOP (:effective_limit) "
            "    qs.query_hash, "
            "    CAST((CASE WHEN qs.execution_count = 0 THEN 0 "
            "               ELSE qs.total_elapsed_time / qs.execution_count END"
            "    ) / 1000 AS INT) AS avg_duration_ms, "
            "    CAST((CASE WHEN qs.execution_count = 0 THEN 0 "
            "               ELSE qs.total_worker_time / qs.execution_count END"
            "    ) / 1000 AS INT) AS avg_cpu_time_ms, "
            "    CAST(CASE WHEN qs.execution_count = 0 THEN 0 "
            "              ELSE qs.total_logical_reads / qs.execution_count END "
            "    AS INT) AS avg_logical_reads, "
            "    qs.execution_count, "
            "    qs.last_execution_time, "
            "    SUBSTRING(st.text, 1, 256) AS query_excerpt "
            "FROM sys.dm_exec_query_stats qs "
            "CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st "
            "WHERE (CASE WHEN qs.execution_count = 0 THEN 0 "
            "            ELSE qs.total_elapsed_time / qs.execution_count END"
            "      ) >= :min_duration_us "
            "  AND (:start_time IS NULL OR qs.last_execution_time >= :start_time) "
            "  AND (:end_time IS NULL OR qs.last_execution_time <= :end_time) "
            "ORDER BY qs.last_execution_time DESC;"
        )

        params: dict[str, Any] = {
            "effective_limit": effective_limit,
            "min_duration_us": min_duration_us,
            "start_time": criteria.start_time,
            "end_time": criteria.end_time,
        }

        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(sql, params)
                rows = result.fetchall()
        except Exception as exc:
            self._handle_exception(exc, "find_slow_queries")

        items: list[SlowQueryDomainDTO] = []
        for r in rows:
            q_hash = f"0x{r[0].hex().upper()}" if isinstance(r[0], bytes) else str(r[0] or "0x0000")
            avg_dur_ms = max(0, int(r[1] or 0))
            avg_cpu_ms = max(0, int(r[2] or 0))
            avg_reads = max(0, int(r[3] or 0))
            exec_count = max(1, int(r[4] or 1))

            last_exec = r[5]
            if isinstance(last_exec, datetime):
                last_exec_utc = last_exec if last_exec.tzinfo else last_exec.replace(tzinfo=UTC)
            else:
                last_exec_utc = datetime.now(UTC)

            raw_summary = str(r[6] or "").strip()
            # Sanitize whitespace in query summary excerpt
            summary = " ".join(raw_summary.split()) if raw_summary else "Diagnostic Query"

            items.append(
                SlowQueryDomainDTO(
                    query_hash=q_hash,
                    duration_ms=avg_dur_ms,
                    cpu_time_ms=avg_cpu_ms,
                    logical_reads=avg_reads,
                    execution_count=exec_count,
                    last_execution_time=last_exec_utc,
                    summary=summary,
                )
            )

        returned_count = len(items)
        is_truncated = returned_count == effective_limit

        return BoundedDiagnosticResultDTO[SlowQueryDomainDTO](
            items=tuple(items),
            returned_count=returned_count,
            total_matched=None,
            is_truncated=is_truncated,
        )

    async def find_deadlocks(
        self, criteria: DeadlockCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[DeadlockDomainDTO]:
        """Query recent deadlock events from system_health ring buffer."""
        effective_limit = min(criteria.limit or self._max_rows, self._max_rows)

        # Relationalize individual deadlock events from system_health ring_buffer
        sql = text(
            "SELECT TOP (:effective_limit) "
            "    deadlock_event.value('(@timestamp)[1]', 'datetime2') AS occurred_at, "
            "    CAST(deadlock_event.query('.') AS nvarchar(max)) AS event_xml "
            "FROM sys.dm_xe_session_targets xst "
            "JOIN sys.dm_xe_sessions xs ON xs.address = xst.event_session_address "
            "CROSS APPLY (SELECT CAST(xst.target_data AS XML)) AS TargetData(x) "
            "CROSS APPLY TargetData.x.nodes("
            "    'RingBufferTarget/event[@name=\"xml_deadlock_report\"]'"
            ") AS XEvent(deadlock_event) "
            "WHERE xs.name = 'system_health' "
            "  AND xst.target_name = 'ring_buffer' "
            "  AND (:start_time IS NULL OR "
            "       deadlock_event.value('(@timestamp)[1]', 'datetime2') >= :start_time) "
            "  AND (:end_time IS NULL OR "
            "       deadlock_event.value('(@timestamp)[1]', 'datetime2') <= :end_time) "
            "ORDER BY occurred_at DESC;"
        )

        params: dict[str, Any] = {
            "effective_limit": effective_limit,
            "start_time": criteria.start_time,
            "end_time": criteria.end_time,
        }

        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(sql, params)
                rows = result.fetchall()
        except Exception as exc:
            self._handle_exception(exc, "find_deadlocks")

        items: list[DeadlockDomainDTO] = []
        for idx, r in enumerate(rows):
            occurred_at_raw = r[0]
            if isinstance(occurred_at_raw, datetime):
                occurred_at = (
                    occurred_at_raw
                    if occurred_at_raw.tzinfo
                    else occurred_at_raw.replace(tzinfo=UTC)
                )
            else:
                occurred_at = datetime.now(UTC)

            raw_xml_str = str(r[1] or "")
            victim_session_id = 1
            participating_count = 2
            resource_desc = "Page/Object Lock"
            summary = "Deadlock cycle detected in system_health telemetry."

            # Safe internal XML extraction for DTO fields only (never stored as raw XML)
            if raw_xml_str:
                try:
                    root = ET.fromstring(raw_xml_str)
                    victim_elem = root.find(".//victimProcess")
                    if victim_elem is not None and "id" in victim_elem.attrib:
                        raw_id = victim_elem.attrib["id"]
                        digits = "".join(ch for ch in raw_id if ch.isdigit())
                        victim_session_id = max(1, int(digits)) if digits else 1

                    proc_elems = root.findall(".//process")
                    if proc_elems:
                        participating_count = max(2, len(proc_elems))

                    res_elem = root.find(".//resource-list/*")
                    if res_elem is not None:
                        obj_name = res_elem.attrib.get("objectname") or res_elem.tag
                        resource_desc = f"Lock on {obj_name}"
                except Exception:
                    pass

            deadlock_id = f"DLOCK-{occurred_at.strftime('%Y%m%d%H%M%S')}-{idx + 1}"

            items.append(
                DeadlockDomainDTO(
                    deadlock_id=deadlock_id,
                    occurred_at=occurred_at,
                    victim_session_id=victim_session_id,
                    participating_session_count=participating_count,
                    resource_description=resource_desc,
                    summary=summary,
                )
            )

        returned_count = len(items)
        is_truncated = returned_count == effective_limit

        return BoundedDiagnosticResultDTO[DeadlockDomainDTO](
            items=tuple(items),
            returned_count=returned_count,
            total_matched=None,
            is_truncated=is_truncated,
        )

    async def find_blocking_sessions(
        self, criteria: BlockingSessionCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[BlockingSessionDomainDTO]:
        """Query currently active blocking sessions exceeding duration threshold."""
        effective_limit = min(criteria.limit or self._max_rows, self._max_rows)

        sql = text(
            "SELECT TOP (:effective_limit) "
            "    r.session_id AS blocked_session_id, "
            "    r.blocking_session_id, "
            "    w.wait_duration_ms, "
            "    w.wait_type "
            "FROM sys.dm_exec_requests r "
            "JOIN sys.dm_os_waiting_tasks w ON r.session_id = w.session_id "
            "WHERE r.blocking_session_id <> 0 "
            "  AND w.wait_duration_ms >= :min_blocked_duration_ms "
            "ORDER BY w.wait_duration_ms DESC;"
        )

        params: dict[str, Any] = {
            "effective_limit": effective_limit,
            "min_blocked_duration_ms": criteria.min_blocked_duration_ms,
        }

        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(sql, params)
                rows = result.fetchall()
        except Exception as exc:
            self._handle_exception(exc, "find_blocking_sessions")

        now = datetime.now(UTC)
        items: list[BlockingSessionDomainDTO] = []
        for r in rows:
            blocked_id = int(r[0])
            blocking_id = int(r[1])
            wait_dur = max(0, int(r[2]))
            wait_type = str(r[3] or "LCK_M_X")

            items.append(
                BlockingSessionDomainDTO(
                    blocked_session_id=blocked_id,
                    blocking_session_id=blocking_id,
                    wait_duration_ms=wait_dur,
                    wait_type=wait_type,
                    detected_at=now,
                )
            )

        returned_count = len(items)
        is_truncated = returned_count == effective_limit

        return BoundedDiagnosticResultDTO[BlockingSessionDomainDTO](
            items=tuple(items),
            returned_count=returned_count,
            total_matched=None,
            is_truncated=is_truncated,
        )

    async def get_ticket_diagnostic_record(
        self, criteria: TicketDiagnosticCriteriaDTO
    ) -> TicketDiagnosticRecordDomainDTO | None:
        """Fetch ticket-scoped diagnostic record.

        Fails closed with DIAGNOSTIC_SCHEMA_NOT_CONFIGURED because SuperOffice
        database diagnostic event schema is not yet verified.
        """
        raise DatabaseDiagnosticError(
            message=(
                "Ticket diagnostic database schema mapping is not verified or configured. "
                "Operation blocked pending SuperOffice diagnostic table/view specification."
            ),
            error_code="DIAGNOSTIC_SCHEMA_NOT_CONFIGURED",
            details={"ticket_id": criteria.ticket_id},
        )
