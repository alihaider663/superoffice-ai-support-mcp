"""Security tests verifying Phase 4.1 header relaying and boundary rules."""

import pytest

from investigation_mcp.adapters.diagnostics_mcp_adapter import DiagnosticsMcpClientAdapter
from investigation_mcp.adapters.superoffice_mcp_adapter import SuperOfficeMcpClientAdapter
from platform_observability.correlation import CorrelationContext


@pytest.mark.unit
def test_superoffice_adapter_headers_empty():
    """Verify SuperOfficeMcpClientAdapter sends EMPTY second-hop header set."""
    adapter = SuperOfficeMcpClientAdapter()
    headers = adapter._build_headers()

    assert headers == {}
    assert "x-correlation-id" not in headers
    assert "x-user-id" not in headers
    assert "x-user-role" not in headers
    assert "x-production-write" not in headers
    assert "x-attachment-access" not in headers
    assert "authorization" not in headers


@pytest.mark.unit
def test_superoffice_adapter_does_not_relay_correlation_id():
    """Verify SuperOfficeMcpClientAdapter does NOT relay X-Correlation-ID in Phase 4.1."""
    with CorrelationContext("corr-abc-123"):
        adapter = SuperOfficeMcpClientAdapter()
        headers = adapter._build_headers()
        assert headers == {}
        assert "x-correlation-id" not in headers


@pytest.mark.unit
def test_diagnostics_adapter_headers_empty():
    """Verify DiagnosticsMcpClientAdapter sends EMPTY second-hop header set."""
    adapter = DiagnosticsMcpClientAdapter()
    headers = adapter._build_headers()

    assert headers == {}
    assert "x-correlation-id" not in headers
    assert "x-user-id" not in headers
    assert "x-user-role" not in headers
    assert "x-production-write" not in headers
    assert "x-attachment-access" not in headers
    assert "authorization" not in headers


@pytest.mark.unit
def test_diagnostics_adapter_does_not_relay_correlation_id():
    """Verify DiagnosticsMcpClientAdapter does NOT relay X-Correlation-ID in Phase 4.1."""
    with CorrelationContext("corr-diag-456"):
        adapter = DiagnosticsMcpClientAdapter()
        headers = adapter._build_headers()
        assert headers == {}
        assert "x-correlation-id" not in headers
