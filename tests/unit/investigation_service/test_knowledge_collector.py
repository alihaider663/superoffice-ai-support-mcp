"""Unit tests for KnowledgeEvidenceCollector."""

import pytest

from platform_investigation.models import (
    EvidenceSourceType,
    SourceCollectionStatus,
)
from platform_investigation_service.collectors.knowledge_collector import (
    KnowledgeEvidenceCollector,
)


class TestKnowledgeEvidenceCollector:
    """Tests for KnowledgeEvidenceCollector (NOT_CONFIGURED source)."""

    def test_source_type_is_knowledge_base(self) -> None:
        collector = KnowledgeEvidenceCollector()
        assert collector.source_type == EvidenceSourceType.KNOWLEDGE_BASE

    @pytest.mark.asyncio
    async def test_returns_not_configured_status(self) -> None:
        collector = KnowledgeEvidenceCollector()

        result = await collector.collect("inv-001", "opaque-key")

        assert result.status == SourceCollectionStatus.NOT_CONFIGURED
        assert result.source_type == EvidenceSourceType.KNOWLEDGE_BASE

    @pytest.mark.asyncio
    async def test_produces_zero_evidence(self) -> None:
        collector = KnowledgeEvidenceCollector()

        result = await collector.collect("inv-002", "opaque-key")

        assert len(result.evidence) == 0

    @pytest.mark.asyncio
    async def test_error_code_and_message_are_safe_and_generic(self) -> None:
        collector = KnowledgeEvidenceCollector()

        result = await collector.collect("inv-003", "opaque-key")

        assert result.error_code == "KNOWLEDGE_BASE_NOT_CONFIGURED"
        assert result.error_message == "Knowledge store backend is not configured."
        # Verify no phase identifiers or internal details
        assert "phase" not in result.error_code.lower()
        assert "phase" not in (result.error_message or "").lower()
