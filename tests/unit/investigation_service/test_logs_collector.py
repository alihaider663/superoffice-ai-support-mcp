"""Unit tests for DiagnosticLogsEvidenceCollector."""

import pytest

from platform_investigation.models import (
    EvidenceSourceType,
    SourceCollectionStatus,
)
from platform_investigation_service.collectors.logs_collector import (
    DiagnosticLogsEvidenceCollector,
    LogsEvidenceCollector,
)


class TestDiagnosticLogsEvidenceCollector:
    """Tests for DiagnosticLogsEvidenceCollector (BLOCKED source)."""

    def test_source_type_is_application_logs(self) -> None:
        collector = DiagnosticLogsEvidenceCollector()
        assert collector.source_type == EvidenceSourceType.APPLICATION_LOGS

    def test_alias_is_identical_class(self) -> None:
        assert LogsEvidenceCollector is DiagnosticLogsEvidenceCollector

    @pytest.mark.asyncio
    async def test_returns_blocked_status(self) -> None:
        collector = DiagnosticLogsEvidenceCollector()

        result = await collector.collect("inv-001", "opaque-key")

        assert result.status == SourceCollectionStatus.BLOCKED
        assert result.source_type == EvidenceSourceType.APPLICATION_LOGS

    @pytest.mark.asyncio
    async def test_produces_zero_evidence(self) -> None:
        collector = DiagnosticLogsEvidenceCollector()

        result = await collector.collect("inv-002", "opaque-key")

        assert len(result.evidence) == 0

    @pytest.mark.asyncio
    async def test_error_code_and_message_are_safe_and_generic(self) -> None:
        collector = DiagnosticLogsEvidenceCollector()

        result = await collector.collect("inv-003", "opaque-key")

        assert result.error_code == "DIAGNOSTIC_LOGS_BLOCKED"
        assert result.error_message == "Application logging backend is blocked or not configured."
        # Verify no phase identifiers or internal details
        assert "phase" not in result.error_code.lower()
        assert "phase" not in (result.error_message or "").lower()
