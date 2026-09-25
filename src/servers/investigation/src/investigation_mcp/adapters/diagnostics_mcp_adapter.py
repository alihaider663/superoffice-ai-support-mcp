"""Diagnostics MCP client adapter satisfying Layer-4 DiagnosticsServicePort."""

import json
from typing import Any

import httpx
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

from diag_mcp.contracts.dtos import (
    BlockingSessionCriteriaDTO,
    BlockingSessionDomainDTO,
    BoundedDiagnosticResultDTO,
    DatabaseHealthDomainDTO,
    DeadlockCriteriaDTO,
    DeadlockDomainDTO,
    SanitizedLogExcerptDTO,
    SlowQueryCriteriaDTO,
    SlowQueryDomainDTO,
    TicketDiagnosticRecordDomainDTO,
)
from diag_mcp.contracts.errors import DatabaseDiagnosticError, LogSearchError
from platform_investigation_service.ports import DiagnosticsServicePort, LogsServicePort
from platform_observability.logging import get_logger

logger = get_logger(__name__)

# Fixed internal tool names for Diagnostics capabilities
TOOL_NAME_DATABASE_HEALTH = "get_database_health"
TOOL_NAME_FIND_DEADLOCKS = "find_deadlocks"
TOOL_NAME_FIND_SLOW_QUERIES = "find_slow_queries"
TOOL_NAME_GET_TICKET_DIAGNOSTIC_RECORD = "get_ticket_diagnostic_record"
TOOL_NAME_FIND_BLOCKING_SESSIONS = "find_blocking_sessions"
TOOL_NAME_SEARCH_LOGS = "search_logs"


class DiagnosticsMcpClientAdapter(DiagnosticsServicePort, LogsServicePort):
    """Downstream MCP client adapter for MSSQL database diagnostics and logs.

    Implements DiagnosticsServicePort and LogsServicePort using official MCP streamable_http_client.
    Invokes strictly the bounded diagnostic capabilities:
    - get_database_health
    - find_deadlocks
    - find_slow_queries
    - get_ticket_diagnostic_record
    - find_blocking_sessions
    - search_logs
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8002",
        endpoint_path: str = "/mcp",
        http_client: httpx.AsyncClient | None = None,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._endpoint_path = endpoint_path
        self._http_client = http_client
        self._timeout_seconds = timeout_seconds

    def _build_headers(self) -> dict[str, str]:
        """Construct minimal second-hop transport headers."""
        return {}

    def _extract_payload(self, tool_result: CallToolResult) -> Any:
        """Extract structured or text JSON payload from CallToolResult."""
        if tool_result.structuredContent is not None:
            return tool_result.structuredContent

        texts: list[str] = [
            item.text for item in tool_result.content if isinstance(item, TextContent)
        ]
        joined_text = "\n".join(texts).strip()
        if not joined_text:
            return {}

        try:
            return json.loads(joined_text)
        except json.JSONDecodeError:
            return {"raw_text": joined_text}

    def _extract_error_message(self, tool_result: CallToolResult, tool_name: str) -> str:
        """Extract human-readable error text from failed CallToolResult."""
        for item in tool_result.content:
            if isinstance(item, TextContent) and item.text.strip():
                return item.text.strip()
        return f"Diagnostics MCP tool '{tool_name}' returned an error."

    async def _execute_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Execute downstream tool invocation over Streamable HTTP."""
        endpoint_url = f"{self._base_url}{self._endpoint_path}"
        headers = self._build_headers()
        timeout = httpx.Timeout(self._timeout_seconds)

        client_to_use = self._http_client
        owns_client = False

        if client_to_use is None:
            client_to_use = httpx.AsyncClient(
                headers=headers,
                timeout=timeout,
                follow_redirects=False,
            )
            owns_client = True
        else:
            client_to_use.headers.update(headers)

        try:
            async with (
                streamable_http_client(
                    endpoint_url,
                    http_client=client_to_use,
                ) as (read_stream, write_stream, _),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                tool_result: CallToolResult = await session.call_tool(
                    name=tool_name,
                    arguments=arguments,
                )

                if tool_result.isError:
                    error_msg = self._extract_error_message(tool_result, tool_name)
                    if tool_name == TOOL_NAME_SEARCH_LOGS and (
                        "not configured" in error_msg.lower() or "blocked" in error_msg.lower()
                    ):
                        raise LogSearchError(
                            error_msg, error_code="LOG_SEARCH_BACKEND_NOT_CONFIGURED"
                        )
                    raise DatabaseDiagnosticError(
                        f"Downstream {tool_name} failed: {error_msg}",
                        error_code="DOWNSTREAM_DIAGNOSTICS_ERROR",
                    )

                return self._extract_payload(tool_result)

        except (httpx.TimeoutException, TimeoutError) as exc:
            logger.warning(
                "Diagnostics MCP tool call timed out",
                tool=tool_name,
                endpoint=endpoint_url,
                error=str(exc),
            )
            raise DatabaseDiagnosticError(
                f"Diagnostics MCP server timed out during {tool_name}.",
                error_code="DOWNSTREAM_TIMEOUT",
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Diagnostics MCP server returned HTTP error status",
                status_code=exc.response.status_code,
                endpoint=endpoint_url,
            )
            raise DatabaseDiagnosticError(
                f"Diagnostics MCP server returned HTTP status {exc.response.status_code}.",
                error_code="DOWNSTREAM_UNAVAILABLE",
            ) from exc
        except (DatabaseDiagnosticError, LogSearchError):
            raise
        except Exception as exc:
            logger.error(
                "Diagnostics MCP communication failed",
                tool=tool_name,
                endpoint=endpoint_url,
                error=str(exc),
            )
            raise DatabaseDiagnosticError(
                f"Failed to communicate with Diagnostics MCP server: {exc}",
                error_code="DOWNSTREAM_UNAVAILABLE",
            ) from exc
        finally:
            if owns_client:
                await client_to_use.aclose()

    async def get_database_health(self) -> DatabaseHealthDomainDTO:
        """Fetch sanitized database health status via downstream Diagnostics MCP server."""
        raw_payload = await self._execute_tool_call(TOOL_NAME_DATABASE_HEALTH, {})
        return DatabaseHealthDomainDTO.model_validate(raw_payload)

    async def find_deadlocks(
        self,
        criteria: DeadlockCriteriaDTO,
    ) -> BoundedDiagnosticResultDTO[DeadlockDomainDTO]:
        """Find recent deadlock events via downstream Diagnostics MCP server."""
        args: dict[str, Any] = criteria.model_dump(mode="json", exclude_none=True)
        raw_payload = await self._execute_tool_call(TOOL_NAME_FIND_DEADLOCKS, args)
        return BoundedDiagnosticResultDTO[DeadlockDomainDTO].model_validate(raw_payload)

    async def find_slow_queries(
        self,
        criteria: SlowQueryCriteriaDTO,
    ) -> BoundedDiagnosticResultDTO[SlowQueryDomainDTO]:
        """Find slow queries via downstream Diagnostics MCP server."""
        args: dict[str, Any] = criteria.model_dump(mode="json", exclude_none=True)
        raw_payload = await self._execute_tool_call(TOOL_NAME_FIND_SLOW_QUERIES, args)
        return BoundedDiagnosticResultDTO[SlowQueryDomainDTO].model_validate(raw_payload)

    async def get_ticket_diagnostic_record(
        self,
        ticket_id: int,
    ) -> TicketDiagnosticRecordDomainDTO | None:
        """Fetch ticket database diagnostic record via downstream Diagnostics MCP server."""
        raw_payload = await self._execute_tool_call(
            TOOL_NAME_GET_TICKET_DIAGNOSTIC_RECORD, {"ticket_id": ticket_id}
        )
        if isinstance(raw_payload, dict) and raw_payload:
            return TicketDiagnosticRecordDomainDTO.model_validate(raw_payload)
        return None

    async def find_blocking_sessions(
        self,
        criteria: BlockingSessionCriteriaDTO | None = None,
    ) -> BoundedDiagnosticResultDTO[BlockingSessionDomainDTO]:
        """Fetch active blocking session snapshot via downstream Diagnostics MCP server."""
        _ = criteria
        raw_payload = await self._execute_tool_call(TOOL_NAME_FIND_BLOCKING_SESSIONS, {})
        return BoundedDiagnosticResultDTO[BlockingSessionDomainDTO].model_validate(raw_payload)

    async def search_logs(
        self,
        query: str,
        limit: int = 20,
    ) -> BoundedDiagnosticResultDTO[SanitizedLogExcerptDTO]:
        """Search application logs via downstream Diagnostics MCP server."""
        raw_payload = await self._execute_tool_call(
            TOOL_NAME_SEARCH_LOGS, {"query": query, "limit": limit}
        )
        return BoundedDiagnosticResultDTO[SanitizedLogExcerptDTO].model_validate(raw_payload)
