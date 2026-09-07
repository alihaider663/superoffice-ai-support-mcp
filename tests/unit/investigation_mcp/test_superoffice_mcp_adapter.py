"""Unit tests for SuperOfficeMcpClientAdapter."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from investigation_mcp.adapters.superoffice_mcp_adapter import (
    TOOL_NAME_GET_TICKET,
    SuperOfficeMcpClientAdapter,
)
from so_mcp.contracts.dtos import MinimizedTicketDetailDTO
from so_mcp.contracts.errors import SuperOfficeIntegrationError


@pytest.fixture
def mock_mcp_session():
    """Fixture providing a mock MCP ClientSession."""
    session = AsyncMock()
    session.initialize = AsyncMock()
    session.__aenter__.return_value = session
    return session


@pytest.mark.unit
async def test_get_ticket_success(mock_mcp_session):
    """Test successful get_ticket tool invocation and DTO parsing."""
    valid_payload = {
        "ticket_id": 101,
        "title": "Database connection failure",
        "status": "Open",
        "category": "Database",
        "priority": "High",
        "sanitized_description": "Connection pool timeout observed on checkout",
        "created_at": "2026-09-01T10:00:00Z",
    }
    tool_result = CallToolResult(
        content=[TextContent(type="text", text="")],
        structuredContent=valid_payload,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = SuperOfficeMcpClientAdapter(base_url="http://localhost:8001")
        result = await adapter.get_ticket(101)

        assert isinstance(result, MinimizedTicketDetailDTO)
        assert result.ticket_id == 101
        assert result.title == "Database connection failure"
        assert result.status == "Open"
        assert result.sanitized_description == "Connection pool timeout observed on checkout"

        mock_mcp_session.call_tool.assert_awaited_once_with(
            name=TOOL_NAME_GET_TICKET,
            arguments={"ticket_id": 101},
        )


@pytest.mark.unit
async def test_get_ticket_json_text_success(mock_mcp_session):
    """Test successful get_ticket parsing when payload is returned as text JSON."""
    json_text = (
        '{"ticket_id": 102, "title": "Slow login", "status": "In Progress", '
        '"category": "Auth", "priority": "Medium", "sanitized_description": "Login latency high", '
        '"created_at": "2026-09-01T11:00:00Z"}'
    )
    tool_result = CallToolResult(
        content=[TextContent(type="text", text=json_text)],
        structuredContent=None,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = SuperOfficeMcpClientAdapter()
        result = await adapter.get_ticket(102)

        assert result.ticket_id == 102
        assert result.title == "Slow login"
        assert result.category == "Auth"


@pytest.mark.unit
async def test_get_ticket_downstream_tool_error(mock_mcp_session):
    """Test handling of downstream MCP tool errors."""
    tool_result = CallToolResult(
        content=[TextContent(type="text", text="Ticket #999 not found")],
        isError=True,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = SuperOfficeMcpClientAdapter()
        with pytest.raises(SuperOfficeIntegrationError) as exc_info:
            await adapter.get_ticket(999)

        assert "Ticket #999 not found" in str(exc_info.value)


@pytest.mark.unit
async def test_get_ticket_timeout():
    """Test timeout during downstream SuperOffice MCP call."""
    with patch(
        "investigation_mcp.adapters.superoffice_mcp_adapter.streamable_http_client"
    ) as mock_client:
        mock_client.side_effect = httpx.TimeoutException("Connection timed out")

        adapter = SuperOfficeMcpClientAdapter()
        with pytest.raises(SuperOfficeIntegrationError) as exc_info:
            await adapter.get_ticket(101)

        assert "timed out" in str(exc_info.value).lower()


@pytest.mark.unit
async def test_get_ticket_http_error():
    """Test HTTP 503 from downstream SuperOffice MCP server."""
    req = httpx.Request("POST", "http://localhost:8001/mcp")
    resp = httpx.Response(503, request=req)

    with patch(
        "investigation_mcp.adapters.superoffice_mcp_adapter.streamable_http_client"
    ) as mock_client:
        mock_client.side_effect = httpx.HTTPStatusError(
            "Service Unavailable", request=req, response=resp
        )

        adapter = SuperOfficeMcpClientAdapter()
        with pytest.raises(SuperOfficeIntegrationError) as exc_info:
            await adapter.get_ticket(101)

        assert "503" in str(exc_info.value)


@pytest.mark.unit
async def test_get_ticket_malformed_payload_fails_validation(mock_mcp_session):
    """Test that malformed/invalid payload propagates ValidationError (fail-closed)."""
    malformed_payload = {"ticket_id": "not_an_int"}
    tool_result = CallToolResult(
        content=[TextContent(type="text", text="")],
        structuredContent=malformed_payload,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = SuperOfficeMcpClientAdapter()
        with pytest.raises(ValidationError):
            await adapter.get_ticket(101)


@pytest.mark.unit
async def test_get_ticket_with_external_http_client(mock_mcp_session):
    """Test get_ticket with externally injected httpx.AsyncClient."""
    valid_payload = {
        "ticket_id": 101,
        "title": "Database connection failure",
        "status": "Open",
        "category": "Database",
        "priority": "High",
        "sanitized_description": "Connection pool timeout observed on checkout",
        "created_at": "2026-09-01T10:00:00Z",
    }
    tool_result = CallToolResult(
        content=[],
        structuredContent=valid_payload,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        async with httpx.AsyncClient() as external_client:
            adapter = SuperOfficeMcpClientAdapter(http_client=external_client)
            result = await adapter.get_ticket(101)
            assert result.ticket_id == 101


@pytest.mark.unit
async def test_get_ticket_raw_text_payload_fallback(mock_mcp_session):
    """Test get_ticket payload extraction when raw non-JSON text is returned."""
    tool_result = CallToolResult(
        content=[TextContent(type="text", text="plain text response")],
        structuredContent=None,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = SuperOfficeMcpClientAdapter()
        with pytest.raises(ValidationError):
            await adapter.get_ticket(101)


@pytest.mark.unit
async def test_get_ticket_empty_content_fallback(mock_mcp_session):
    """Test get_ticket payload extraction with empty content and None structuredContent."""
    tool_result = CallToolResult(
        content=[],
        structuredContent=None,
        isError=False,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = SuperOfficeMcpClientAdapter()
        with pytest.raises(ValidationError):
            await adapter.get_ticket(101)


@pytest.mark.unit
async def test_get_ticket_default_error_message(mock_mcp_session):
    """Test get_ticket tool error when error content has empty text."""
    tool_result = CallToolResult(
        content=[TextContent(type="text", text="   ")],
        isError=True,
    )
    mock_mcp_session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.streamable_http_client"
        ) as mock_client,
        patch(
            "investigation_mcp.adapters.superoffice_mcp_adapter.ClientSession",
            return_value=mock_mcp_session,
        ),
    ):
        mock_client.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock(), None)

        adapter = SuperOfficeMcpClientAdapter()
        with pytest.raises(SuperOfficeIntegrationError) as exc_info:
            await adapter.get_ticket(101)
        assert "SuperOffice MCP get_ticket returned an error" in str(exc_info.value)


@pytest.mark.unit
async def test_get_ticket_generic_communication_error():
    """Test get_ticket when an unexpected network or stream exception occurs."""
    with patch(
        "investigation_mcp.adapters.superoffice_mcp_adapter.streamable_http_client"
    ) as mock_client:
        mock_client.side_effect = RuntimeError("Socket abruptly closed")

        adapter = SuperOfficeMcpClientAdapter()
        with pytest.raises(SuperOfficeIntegrationError) as exc_info:
            await adapter.get_ticket(101)
        assert "Socket abruptly closed" in str(exc_info.value)
