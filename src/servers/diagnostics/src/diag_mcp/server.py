"""Diagnostics MCP Server FastMCP runtime application exposing /mcp tools."""

from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from diag_mcp.adapters.factory import create_composite_log_adapter, create_diagnostic_repository
from diag_mcp.contracts.dtos import (
    BlockingSessionCriteriaDTO,
    DeadlockCriteriaDTO,
    SlowQueryCriteriaDTO,
    TicketDiagnosticCriteriaDTO,
)
from diag_mcp.contracts.errors import DatabaseDiagnosticError, LogSearchError
from diag_mcp.contracts.interfaces import DiagnosticRepository, LogSearchClient
from diag_mcp.services.diagnostic_service import DiagnosticsApplicationService
from diag_mcp.settings import DiagnosticsServerSettings

ALLOWED_BACKEND_HOSTS = [
    "localhost",
    "localhost:*",
    "127.0.0.1",
    "127.0.0.1:*",
    "testserver",
    "testserver:*",
    "diag-backend",
    "diag-backend:*",
    "diag-server",
    "diag-server:*",
    "diag-internal",
    "diag-internal:*",
]


def create_diagnostics_mcp_server(
    service: DiagnosticsApplicationService | None = None,
    repository: DiagnosticRepository | None = None,
) -> FastMCP:
    """Instantiate and configure the official FastMCP Diagnostics server."""
    mcp_server = FastMCP(
        name="diagnostics-mcp-server",
        streamable_http_path="/mcp",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=ALLOWED_BACKEND_HOSTS,
        ),
    )

    app_service = service or (
        DiagnosticsApplicationService(repository=repository) if repository else None
    )

    @mcp_server.tool(
        name="get_database_health",
        description=(
            "Current point-in-time observation of database cluster health, active connections, "
            "backup history, and connectivity boundary. A CONNECTED state proves database "
            "reachability at collection time only; it does NOT invalidate or disprove previously "
            "observed failures. Historical root cause remains UNKNOWN unless separate historical "
            "evidence proves it. latency_ms is an observational diagnostic measurement for this "
            "specific query and does NOT by itself prove client timeout, SQL saturation, "
            "VPN/firewall failure, connection pool exhaustion, or outage cause. Do not recommend "
            "changing connection timeouts, firewall, VPN, or database network configurations "
            "without concrete supporting evidence."
        ),
    )
    async def get_database_health() -> dict[str, Any]:
        if app_service is None:
            raise DatabaseDiagnosticError(
                "Diagnostics database service is not configured or unavailable.",
                error_code="DIAGNOSTICS_SERVICE_UNCONFIGURED",
            )
        res = await app_service.get_database_health()
        return res.model_dump(mode="json")

    @mcp_server.tool(
        name="find_slow_queries",
        description=(
            "Inspect slow query execution records from the SQL Server plan cache "
            "(sys.dm_exec_query_stats). Metrics represent cached and aggregated historical "
            "averages per execution, not proof of query execution at the exact current moment."
        ),
    )
    async def find_slow_queries(min_duration_ms: float = 1000.0, limit: int = 10) -> dict[str, Any]:
        if app_service is None:
            raise DatabaseDiagnosticError(
                "Diagnostics database service is not configured or unavailable.",
                error_code="DIAGNOSTICS_SERVICE_UNCONFIGURED",
            )
        criteria = SlowQueryCriteriaDTO(min_duration_ms=int(min_duration_ms), limit=limit)
        res = await app_service.find_slow_queries(criteria)
        return res.model_dump(mode="json")

    @mcp_server.tool(
        name="get_ticket_diagnostic_record",
        description=(
            "Inspect database-level diagnostic activity and update telemetry for a ticket, "
            "verifying database recording state, activity counts, and recent mutations."
        ),
    )
    async def get_ticket_diagnostic_record(ticket_id: int) -> dict[str, Any]:
        if app_service is None:
            raise DatabaseDiagnosticError(
                "Diagnostics database service is not configured or unavailable.",
                error_code="DIAGNOSTICS_SERVICE_UNCONFIGURED",
            )
        criteria = TicketDiagnosticCriteriaDTO(ticket_id=ticket_id)
        res = await app_service.get_ticket_diagnostic_record(criteria)
        if res is not None:
            return res.model_dump(mode="json")
        return {
            "ticket_id": ticket_id,
            "has_db_activity": False,
            "recent_error_count": 0,
            "last_activity_time": None,
            "diagnostic_summary": f"No database diagnostic records found for ticket #{ticket_id}.",
        }

    @mcp_server.tool(
        name="search_logs",
        description=(
            "Search application and API log entries (BLOCKED: Log backend is unconfigured "
            "in this environment. Do not call or retry calling this tool)."
        ),
    )
    async def search_logs(query: str, limit: int = 20) -> dict[str, Any]:
        if app_service is None:
            raise LogSearchError(
                "Diagnostics log search service is not configured or unavailable.",
                error_code="LOG_SEARCH_BACKEND_NOT_CONFIGURED",
            )
        res = await app_service.search_logs(query=query, limit=limit)
        return res.model_dump(mode="json")

    @mcp_server.tool(
        name="find_deadlocks",
        description=(
            "Query deadlock events captured in the SQL Server system_health ring buffer within "
            "the queried time window (hours_back, default 24). Zero returned deadlocks means only "
            "that none were captured within that specific window; it does NOT prove historical "
            "absence outside that window or absence of other contention."
        ),
    )
    async def find_deadlocks(
        hours_back: int = 24,
        limit: int = 10,
    ) -> dict[str, Any]:
        if app_service is None:
            raise DatabaseDiagnosticError(
                "Diagnostics database service is not configured or unavailable.",
                error_code="DIAGNOSTICS_SERVICE_UNCONFIGURED",
            )
        start_time = datetime.now(UTC) - timedelta(hours=hours_back) if hours_back > 0 else None
        criteria = DeadlockCriteriaDTO(limit=limit, start_time=start_time)
        res = await app_service.find_deadlocks(criteria)
        return res.model_dump(mode="json")

    @mcp_server.tool(
        name="find_blocking_sessions",
        description=(
            "Real-time snapshot of active SQL Server blocking transactions. Zero current "
            "blocking sessions means no blocking sessions were observed at the exact moment "
            "of this snapshot; it does NOT prove absence of blocking prior to the snapshot."
        ),
    )
    async def find_blocking_sessions() -> dict[str, Any]:
        if app_service is None:
            raise DatabaseDiagnosticError(
                "Diagnostics database service is not configured or unavailable.",
                error_code="DIAGNOSTICS_SERVICE_UNCONFIGURED",
            )
        criteria = BlockingSessionCriteriaDTO()
        res = await app_service.find_blocking_sessions(criteria)
        return res.model_dump(mode="json")

    return mcp_server


def create_app(
    settings: DiagnosticsServerSettings | None = None,
    service: DiagnosticsApplicationService | None = None,
    repository: DiagnosticRepository | None = None,
    log_client: LogSearchClient | None = None,
) -> Starlette:
    """Create the Starlette ASGI application for Diagnostics MCP Server."""
    active_service = service
    if active_service is None:
        active_settings = settings or DiagnosticsServerSettings()
        active_repo = repository or create_diagnostic_repository(active_settings)
        active_log_client = log_client or create_composite_log_adapter(active_settings)
        active_service = DiagnosticsApplicationService(
            repository=active_repo,
            log_client=active_log_client,
        )

    server = create_diagnostics_mcp_server(service=active_service)
    return server.streamable_http_app()
