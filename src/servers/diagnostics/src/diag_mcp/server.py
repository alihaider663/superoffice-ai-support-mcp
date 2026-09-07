"""Diagnostics MCP Server FastMCP runtime application exposing /mcp tools."""

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
        description="Basic database cluster health diagnostics",
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
        description="Inspect slow query execution records",
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
        description="Get diagnostic database records for a ticket (BLOCKED: awaiting schema)",
    )
    async def get_ticket_diagnostic_record(ticket_id: int) -> dict[str, Any]:
        if app_service is not None:
            criteria = TicketDiagnosticCriteriaDTO(ticket_id=ticket_id)
            res = await app_service.get_ticket_diagnostic_record(criteria)
            if res is not None:
                return res.model_dump(mode="json")
        raise DatabaseDiagnosticError(
            "Ticket diagnostic record querying is blocked pending DB schema verification.",
            error_code="DIAGNOSTIC_SCHEMA_NOT_CONFIGURED",
        )

    @mcp_server.tool(
        name="search_logs",
        description="Search application and API log entries",
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
        description="Analyze SQL Server deadlock graphs and events",
    )
    async def find_deadlocks(
        hours_back: int = 24,  # noqa: ARG001
        limit: int = 10,
    ) -> dict[str, Any]:
        if app_service is None:
            raise DatabaseDiagnosticError(
                "Diagnostics database service is not configured or unavailable.",
                error_code="DIAGNOSTICS_SERVICE_UNCONFIGURED",
            )
        criteria = DeadlockCriteriaDTO(limit=limit)
        res = await app_service.find_deadlocks(criteria)
        return res.model_dump(mode="json")

    @mcp_server.tool(
        name="find_blocking_sessions",
        description="Analyze SQL Server blocking transactions",
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
