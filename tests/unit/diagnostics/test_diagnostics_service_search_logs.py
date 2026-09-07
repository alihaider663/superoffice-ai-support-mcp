"""Unit and integration tests for DiagnosticsApplicationService.search_logs (Gate 7A.4C)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from diag_mcp.adapters.factory import create_composite_log_adapter
from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    LogRecordDomainDTO,
    LogSearchCriteriaDTO,
    SanitizedLogExcerptDTO,
)
from diag_mcp.contracts.errors import LogSearchError
from diag_mcp.contracts.interfaces import DiagnosticRepository, LogSearchClient
from diag_mcp.server import create_diagnostics_mcp_server
from diag_mcp.services.diagnostic_service import DiagnosticsApplicationService
from diag_mcp.settings import DiagnosticsServerSettings
from platform_gateway.registry import create_default_routing_table


class DummyRepository(DiagnosticRepository):
    """Dummy implementation of DiagnosticRepository for service testing."""

    async def get_database_health(self) -> Any:
        raise NotImplementedError

    async def find_slow_queries(self, criteria: Any) -> Any:
        raise NotImplementedError

    async def find_deadlocks(self, criteria: Any) -> Any:
        raise NotImplementedError

    async def find_blocking_sessions(self, criteria: Any) -> Any:
        raise NotImplementedError

    async def get_ticket_diagnostic_record(self, criteria: Any) -> Any:
        raise NotImplementedError


class MockLogSearchClient(LogSearchClient):
    """Controlled mock LogSearchClient for testing application service."""

    def __init__(self, records: list[LogRecordDomainDTO] | None = None) -> None:
        self.records = records or []
        self.captured_criteria: LogSearchCriteriaDTO | None = None

    async def search_logs(
        self, criteria: LogSearchCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[LogRecordDomainDTO]:
        self.captured_criteria = criteria
        return BoundedDiagnosticResultDTO[LogRecordDomainDTO](
            items=tuple(self.records),
            returned_count=len(self.records),
            total_matched=len(self.records),
            is_truncated=False,
        )


def _make_record(
    log_id: str,
    message: str,
    *,
    service_name: str = "superoffice_cs",
    severity: str = "WARN",
    raw_context: dict[str, str] | None = None,
    ticket_id: int | None = 12345,
) -> LogRecordDomainDTO:
    return LogRecordDomainDTO(
        log_id=log_id,
        timestamp=datetime(2026, 8, 25, 10, 0, 0, tzinfo=UTC),
        service_name=service_name,
        severity=severity,
        message=message,
        correlation_id="corr-xyz",
        ticket_id=ticket_id,
        raw_context=raw_context or {"numeric_id": "99", "secret_key": "raw_internal_value"},
    )


@pytest.mark.asyncio
async def test_search_logs_query_mapping_and_defaults() -> None:
    """Verify query maps to query_text, limit defaults to 20, no syntax parsed (Sec 10, 40)."""
    mock_client = MockLogSearchClient()
    svc = DiagnosticsApplicationService(
        repository=DummyRepository(),
        log_client=mock_client,
    )

    await svc.search_logs(query="  ticket:12345 severity:error  ")
    assert mock_client.captured_criteria is not None
    # Verifies literal text passed without extracting ticket_id or severity
    assert mock_client.captured_criteria.query_text == "ticket:12345 severity:error"
    assert mock_client.captured_criteria.limit == 20
    assert mock_client.captured_criteria.ticket_id is None
    assert mock_client.captured_criteria.severity is None


@pytest.mark.asyncio
async def test_search_logs_query_too_long_rejected() -> None:
    """Verify queries exceeding 256 chars are rejected with LOG_SEARCH_QUERY_TOO_LONG (Sec 12)."""
    svc = DiagnosticsApplicationService(
        repository=DummyRepository(),
        log_client=MockLogSearchClient(),
    )
    with pytest.raises(LogSearchError) as exc_info:
        await svc.search_logs(query="A" * 257)
    assert exc_info.value.error_code == "LOG_SEARCH_QUERY_TOO_LONG"


@pytest.mark.asyncio
async def test_search_logs_limit_bounds_and_rejection() -> None:
    """Verify limit bounds (max 50, ge 1) and over/under limit rejections (Sec 13, 40)."""
    mock_client = MockLogSearchClient()
    svc = DiagnosticsApplicationService(
        repository=DummyRepository(),
        log_client=mock_client,
    )

    # Valid limit: 50
    await svc.search_logs(query="test", limit=50)
    assert mock_client.captured_criteria is not None
    assert mock_client.captured_criteria.limit == 50

    # Over-limit: 51 -> rejected
    with pytest.raises(LogSearchError) as exc_over:
        await svc.search_logs(query="test", limit=51)
    assert exc_over.value.error_code == "LOG_SEARCH_LIMIT_EXCEEDED"

    # Under-limit: 0 -> rejected
    with pytest.raises(LogSearchError) as exc_under:
        await svc.search_logs(query="test", limit=0)
    assert exc_under.value.error_code == "LOG_SEARCH_LIMIT_INVALID"


@pytest.mark.asyncio
async def test_search_logs_sanitization_and_raw_field_minimization() -> None:
    """Verify PII/tokens sanitized, raw_context & ticket_id removed from AI output (Sec 20, 43)."""
    raw_message = (
        "User user@example.test with token Bearer secret-token-123 failed login "
        "from path C:\\Synthetic\\Private\\Path"
    )
    rec = _make_record(
        log_id="warn-101",
        message=raw_message,
        raw_context={"secret_internal": "super_secret", "numeric_id": "101"},
        ticket_id=999,
    )
    mock_client = MockLogSearchClient([rec])
    svc = DiagnosticsApplicationService(
        repository=DummyRepository(),
        log_client=mock_client,
    )

    res = await svc.search_logs(query="User")
    assert res.returned_count == 1
    item: SanitizedLogExcerptDTO = res.items[0]

    # Verify PII/token redaction
    assert "user@example.test" not in item.sanitized_message
    assert "secret-token-123" not in item.sanitized_message

    # Verify AI-facing DTO has NO raw_context or ticket_id
    assert not hasattr(item, "raw_context")
    assert not hasattr(item, "ticket_id")
    dump = item.model_dump()
    assert "raw_context" not in dump
    assert "ticket_id" not in dump
    assert "secret_internal" not in str(dump)


@pytest.mark.asyncio
async def test_search_logs_no_client_configured_fails_closed() -> None:
    """Verify service raises LOG_SEARCH_BACKEND_NOT_CONFIGURED when log_client is None (Sec 6)."""
    svc = DiagnosticsApplicationService(repository=DummyRepository(), log_client=None)
    with pytest.raises(LogSearchError) as exc_info:
        await svc.search_logs(query="test")
    assert exc_info.value.error_code == "LOG_SEARCH_BACKEND_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_mcp_tool_search_logs_execution() -> None:
    """Verify Diagnostics MCP server search_logs tool accepts request and calls service (Sec 48)."""
    rec = _make_record("warn-201", "Application health normal")
    mock_client = MockLogSearchClient([rec])
    svc = DiagnosticsApplicationService(
        repository=DummyRepository(),
        log_client=mock_client,
    )

    mcp_server = create_diagnostics_mcp_server(service=svc)
    tool_fn = mcp_server._tool_manager.get_tool("search_logs")
    assert tool_fn is not None

    result = await tool_fn.run({"query": "health", "limit": 10})
    assert isinstance(result, dict)
    assert result["returned_count"] == 1
    assert result["items"][0]["excerpt_id"] == "warn-201"
    assert "Application health normal" in result["items"][0]["sanitized_message"]


@pytest.mark.asyncio
async def test_mcp_tool_search_logs_unconfigured_fails_closed() -> None:
    """Verify Diagnostics MCP tool fails closed when no service is configured (Sec 48)."""
    mcp_server = create_diagnostics_mcp_server(service=None)
    tool_fn = mcp_server._tool_manager.get_tool("search_logs")
    assert tool_fn is not None

    with pytest.raises((LogSearchError, ToolError)) as exc_info:
        await tool_fn.run({"query": "health"})
    err_str = str(exc_info.value)
    assert "LOG_SEARCH_BACKEND_NOT_CONFIGURED" in err_str or "not configured" in err_str


def test_default_settings_factory_creates_unconfigured_adapter() -> None:
    """Verify default settings create adapter with no enabled sources (Sec 51, 52, 53)."""
    settings = DiagnosticsServerSettings()
    assert settings.iis_log_enabled is False
    assert settings.application_log_enabled is False

    adapter = create_composite_log_adapter(settings)
    assert adapter.has_enabled_sources is False


@pytest.mark.asyncio
async def test_investigation_subordinate_calls_do_not_include_search_logs() -> None:
    """Verify investigation_incident subordinate call set does NOT include search_logs (Sec 35)."""
    routing = create_default_routing_table()
    search_logs_route = routing.get_route("search_logs")
    assert search_logs_route is not None
    # search_logs routes to DIAGNOSTICS, NOT INVESTIGATION
    assert search_logs_route.target_server.value == "DIAGNOSTICS"
