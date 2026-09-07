"""Unit tests for DiagnosticsMcpClientAdapter."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    DatabaseHealthDomainDTO,
    DeadlockCriteriaDTO,
    SlowQueryCriteriaDTO,
)
from diag_mcp.contracts.errors import DatabaseDiagnosticError
from investigation_mcp.adapters.diagnostics_mcp_adapter import (
    TOOL_NAME_DATABASE_HEALTH,
    TOOL_NAME_FIND_DEADLOCKS,
    TOOL_NAME_FIND_SLOW_QUERIES,
    DiagnosticsMcpClientAdapter,
)


@pytest.fixture
def mock_mcp_session():
    """Fixture providing a mock MCP ClientSession."""
    session = AsyncMock()
    session.initialize = AsyncMock()
    session.__aenter__.return_value = session
    return session


@pytest.mark.unit
async def test_get_database_health_success(mock_mcp_session):
    """Test successful database health retrieval and parsing."""
    valid_payload = {
        "is_healthy": True,
        "status_summary": "ONLINE",
        "active_connections": 12,
        "latency_ms": 1.8,
        "collected_at": "2026-09-01T10:00:00Z",
    }
    tool_result = CallToolResult(
        content=[TextContent(type="text", text="")],
        structuredContent=valid_payload,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = DiagnosticsMcpClientAdapter(base_url="http://localhost:8002")
        result = await adapter.get_database_health()

        assert isinstance(result, DatabaseHealthDomainDTO)
        assert result.is_healthy is True
        assert result.status_summary == "ONLINE"
        assert result.active_connections == 12

        mock_mcp_session.call_tool.assert_awaited_once_with(
            name=TOOL_NAME_DATABASE_HEALTH,
            arguments={},
        )


@pytest.mark.unit
async def test_find_deadlocks_success(mock_mcp_session):
    """Test successful deadlock event search and bounded envelope parsing."""
    valid_payload = {
        "items": [
            {
                "deadlock_id": "dl-101",
                "occurred_at": "2026-09-01T10:00:00Z",
                "victim_session_id": 55,
                "participating_session_count": 2,
                "resource_description": "Page Lock (table: ticket)",
                "summary": "Deadlock between session 55 and 56",
            }
        ],
        "returned_count": 1,
        "total_matched": 1,
        "is_truncated": False,
    }
    tool_result = CallToolResult(
        content=[TextContent(type="text", text="")],
        structuredContent=valid_payload,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = DiagnosticsMcpClientAdapter()
        criteria = DeadlockCriteriaDTO(limit=5)
        result = await adapter.find_deadlocks(criteria)

        assert isinstance(result, BoundedDiagnosticResultDTO)
        assert result.returned_count == 1
        assert len(result.items) == 1
        assert result.items[0].deadlock_id == "dl-101"

        mock_mcp_session.call_tool.assert_awaited_once_with(
            name=TOOL_NAME_FIND_DEADLOCKS,
            arguments={"limit": 5},
        )


@pytest.mark.unit
async def test_find_slow_queries_success(mock_mcp_session):
    """Test successful slow query search and bounded envelope parsing."""
    valid_payload = {
        "items": [
            {
                "query_hash": "q-hash-abc",
                "duration_ms": 3200,
                "cpu_time_ms": 1500,
                "logical_reads": 45000,
                "execution_count": 10,
                "last_execution_time": "2026-09-01T10:00:00Z",
                "summary": "SELECT * FROM ticket WHERE status = ?",
            }
        ],
        "returned_count": 1,
        "total_matched": 1,
        "is_truncated": False,
    }
    tool_result = CallToolResult(
        content=[TextContent(type="text", text="")],
        structuredContent=valid_payload,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = DiagnosticsMcpClientAdapter()
        criteria = SlowQueryCriteriaDTO(min_duration_ms=2000, limit=10)
        result = await adapter.find_slow_queries(criteria)

        assert isinstance(result, BoundedDiagnosticResultDTO)
        assert result.returned_count == 1
        assert result.items[0].query_hash == "q-hash-abc"

        mock_mcp_session.call_tool.assert_awaited_once_with(
            name=TOOL_NAME_FIND_SLOW_QUERIES,
            arguments={"min_duration_ms": 2000, "limit": 10},
        )


@pytest.mark.unit
async def test_diagnostics_downstream_tool_error(mock_mcp_session):
    """Test error handling when Diagnostics MCP tool returns an error."""
    tool_result = CallToolResult(
        content=[TextContent(type="text", text="MSSQL query execution failed")],
        isError=True,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = DiagnosticsMcpClientAdapter()
        with pytest.raises(DatabaseDiagnosticError) as exc_info:
            await adapter.get_database_health()

        assert "MSSQL query execution failed" in str(exc_info.value)


@pytest.mark.unit
async def test_diagnostics_timeout():
    """Test timeout handling during Diagnostics MCP call."""
    with patch(
        "investigation_mcp.adapters.diagnostics_mcp_adapter.streamable_http_client"
    ) as mock_client:
        mock_client.side_effect = httpx.TimeoutException("Timed out")

        adapter = DiagnosticsMcpClientAdapter()
        with pytest.raises(DatabaseDiagnosticError) as exc_info:
            await adapter.get_database_health()

        assert "timed out" in str(exc_info.value).lower()


@pytest.mark.unit
async def test_diagnostics_malformed_payload_fails_validation(mock_mcp_session):
    """Test that malformed diagnostic payload raises ValidationError (fail-closed)."""
    malformed_payload = {"is_healthy": "not_a_bool"}
    tool_result = CallToolResult(
        content=[TextContent(type="text", text="")],
        structuredContent=malformed_payload,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = DiagnosticsMcpClientAdapter()
        with pytest.raises(ValidationError):
            await adapter.get_database_health()


@pytest.mark.unit
async def test_diagnostics_with_external_http_client(mock_mcp_session):
    """Test Diagnostics adapter with externally provided httpx.AsyncClient."""
    valid_payload = {
        "is_healthy": True,
        "status_summary": "ONLINE",
        "active_connections": 10,
        "latency_ms": 1.0,
        "collected_at": "2026-09-01T10:00:00Z",
    }
    tool_result = CallToolResult(
        content=[],
        structuredContent=valid_payload,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        async with httpx.AsyncClient() as external_client:
            adapter = DiagnosticsMcpClientAdapter(http_client=external_client)
            result = await adapter.get_database_health()
            assert result.is_healthy is True


@pytest.mark.unit
async def test_diagnostics_raw_text_and_empty_payload_fallbacks(mock_mcp_session):
    """Test diagnostics payload fallback on raw non-JSON text and empty content."""
    # 1. Non-JSON raw text
    tool_result_raw = CallToolResult(
        content=[TextContent(type="text", text="raw string")],
        structuredContent=None,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result_raw)

    with (
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = DiagnosticsMcpClientAdapter()
        with pytest.raises(ValidationError):
            await adapter.get_database_health()

    # 2. Empty content
    tool_result_empty = CallToolResult(
        content=[],
        structuredContent=None,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result_empty)

    with (
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        with pytest.raises(ValidationError):
            await adapter.get_database_health()


@pytest.mark.unit
async def test_diagnostics_default_error_message(mock_mcp_session):
    """Test diagnostics tool error when error text is blank."""
    tool_result = CallToolResult(
        content=[TextContent(type="text", text="   ")],
        isError=True,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.diagnostics_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = DiagnosticsMcpClientAdapter()
        with pytest.raises(DatabaseDiagnosticError) as exc_info:
            await adapter.get_database_health()
        assert "Diagnostics MCP tool 'get_database_health' returned an error" in str(exc_info.value)


@pytest.mark.unit
async def test_diagnostics_http_status_error():
    """Test diagnostics HTTP error status handling."""
    req = httpx.Request("POST", "http://localhost:8002/mcp")
    resp = httpx.Response(502, request=req)

    with patch(
        "investigation_mcp.adapters.diagnostics_mcp_adapter.streamable_http_client"
    ) as mock_client:
        mock_client.side_effect = httpx.HTTPStatusError("Bad Gateway", request=req, response=resp)

        adapter = DiagnosticsMcpClientAdapter()
        with pytest.raises(DatabaseDiagnosticError) as exc_info:
            await adapter.get_database_health()
        assert "502" in str(exc_info.value)


@pytest.mark.unit
async def test_diagnostics_generic_communication_error():
    """Test diagnostics generic network failure."""
    with patch(
        "investigation_mcp.adapters.diagnostics_mcp_adapter.streamable_http_client"
    ) as mock_client:
        mock_client.side_effect = RuntimeError("Broken pipe")

        adapter = DiagnosticsMcpClientAdapter()
        with pytest.raises(DatabaseDiagnosticError) as exc_info:
            await adapter.get_database_health()
        assert "Broken pipe" in str(exc_info.value)
