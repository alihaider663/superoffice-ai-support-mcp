"""Unit tests for DiagnosticsEvidenceCollector with atomic source semantics."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    DatabaseHealthDomainDTO,
    DeadlockCriteriaDTO,
    DeadlockDomainDTO,
    SlowQueryCriteriaDTO,
    SlowQueryDomainDTO,
)
from platform_investigation.models import (
    EvidenceSourceType,
    SourceCollectionStatus,
)
from platform_investigation_service.collectors.diagnostics_collector import (
    DiagnosticsEvidenceCollector,
)
from platform_investigation_service.models import DiagnosticsSelectionDTO


class _FakeDiagnosticsPort:
    """Fake DiagnosticsServicePort for testing."""

    def __init__(
        self,
        health: DatabaseHealthDomainDTO | None = None,
        slow_queries: list[SlowQueryDomainDTO] | None = None,
        deadlocks: list[DeadlockDomainDTO] | None = None,
        *,
        health_error: bool = False,
        slow_query_error: bool = False,
        deadlock_error: bool = False,
    ) -> None:
        self._health = health or DatabaseHealthDomainDTO(
            is_healthy=True,
            status_summary="ONLINE",
            active_connections=42,
            latency_ms=2.5,
            collected_at=datetime.now(UTC),
        )
        self._slow_queries = slow_queries or []
        self._deadlocks = deadlocks or []
        self._health_error = health_error
        self._slow_query_error = slow_query_error
        self._deadlock_error = deadlock_error
        self.health_calls: int = 0
        self.slow_query_calls: list[SlowQueryCriteriaDTO] = []
        self.deadlock_calls: list[DeadlockCriteriaDTO] = []

    async def get_database_health(self) -> DatabaseHealthDomainDTO:
        self.health_calls += 1
        if self._health_error:
            raise RuntimeError("Health check failed on db-server-01.internal")
        return self._health

    async def find_slow_queries(
        self, criteria: SlowQueryCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[SlowQueryDomainDTO]:
        self.slow_query_calls.append(criteria)
        if self._slow_query_error:
            raise RuntimeError("Slow query search failed with SQL query text leak")
        return BoundedDiagnosticResultDTO[SlowQueryDomainDTO](
            items=tuple(self._slow_queries),
            returned_count=len(self._slow_queries),
            total_matched=len(self._slow_queries),
            is_truncated=False,
        )

    async def find_deadlocks(
        self, criteria: DeadlockCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[DeadlockDomainDTO]:
        self.deadlock_calls.append(criteria)
        if self._deadlock_error:
            raise RuntimeError("Deadlock search failed on deadlock-proc-55")
        return BoundedDiagnosticResultDTO[DeadlockDomainDTO](
            items=tuple(self._deadlocks),
            returned_count=len(self._deadlocks),
            total_matched=len(self._deadlocks),
            is_truncated=False,
        )


class TestDiagnosticsEvidenceCollector:
    """Tests for DiagnosticsEvidenceCollector."""

    def test_source_type_is_mssql_diagnostics(self) -> None:
        port = _FakeDiagnosticsPort()
        collector = DiagnosticsEvidenceCollector(port)
        assert collector.source_type == EvidenceSourceType.MSSQL_DIAGNOSTICS

    @pytest.mark.asyncio
    async def test_no_selections_makes_zero_calls(self) -> None:
        """selection=None -> 0 calls and SUCCESS with empty evidence."""
        port = _FakeDiagnosticsPort()
        collector = DiagnosticsEvidenceCollector(port, selection=None)

        result = await collector.collect("inv-001", "opaque-key")

        assert result.status == SourceCollectionStatus.SUCCESS
        assert len(result.evidence) == 0
        assert port.health_calls == 0
        assert len(port.slow_query_calls) == 0
        assert len(port.deadlock_calls) == 0

    @pytest.mark.asyncio
    async def test_default_diagnostics_selection_makes_zero_calls(self) -> None:
        port = _FakeDiagnosticsPort()
        collector = DiagnosticsEvidenceCollector(port, selection=DiagnosticsSelectionDTO())

        result = await collector.collect("inv-002", "opaque-key")

        assert result.status == SourceCollectionStatus.SUCCESS
        assert len(result.evidence) == 0
        assert port.health_calls == 0
        assert len(port.slow_query_calls) == 0
        assert len(port.deadlock_calls) == 0

    @pytest.mark.asyncio
    async def test_health_check_only_makes_exactly_one_call(self) -> None:
        port = _FakeDiagnosticsPort()
        selection = DiagnosticsSelectionDTO(include_database_health=True)
        collector = DiagnosticsEvidenceCollector(port, selection=selection)

        result = await collector.collect("inv-003", "opaque-key")

        assert result.status == SourceCollectionStatus.SUCCESS
        assert len(result.evidence) == 1
        assert port.health_calls == 1
        assert len(port.slow_query_calls) == 0
        assert len(port.deadlock_calls) == 0

        e = result.evidence[0]
        assert e.evidence_id == "diag:health:inv-003"
        assert e.title == "Database health observation"
        assert e.tags == ("diagnostics", "database", "health")
        assert e.data == {
            "is_healthy": True,
            "active_connections": 42,
            "latency_ms": 2.5,
        }

    @pytest.mark.asyncio
    async def test_deadlock_only_makes_exactly_one_call(self) -> None:
        now = datetime.now(UTC)
        deadlocks = [
            DeadlockDomainDTO(
                deadlock_id="dlk-uuid-001",
                occurred_at=now,
                victim_session_id=54,
                participating_session_count=2,
                resource_description="PAGE: 5:1:2345",
                summary="Secret raw deadlock details",
            )
        ]
        port = _FakeDiagnosticsPort(deadlocks=deadlocks)
        criteria = DeadlockCriteriaDTO(limit=10)
        selection = DiagnosticsSelectionDTO(deadlock_criteria=criteria)
        collector = DiagnosticsEvidenceCollector(port, selection=selection)

        result = await collector.collect("inv-004", "opaque-key")

        assert result.status == SourceCollectionStatus.SUCCESS
        assert len(result.evidence) == 1
        assert port.health_calls == 0
        assert len(port.deadlock_calls) == 1
        assert len(port.slow_query_calls) == 0

        e = result.evidence[0]
        assert e.evidence_id == "diag:deadlock:dlk-uuid-001"
        assert e.title == "Database deadlock observation"
        assert e.tags == ("diagnostics", "database", "deadlock")
        assert e.data == {
            "deadlock_id": "dlk-uuid-001",
            "victim_session_id": 54,
            "participating_session_count": 2,
        }
        # Verify no resource_description or summary leakage
        assert "resource_description" not in e.data
        assert "summary" not in e.data

        assert len(e.correlation_references) == 1
        assert e.correlation_references[0].namespace == "deadlock_id"
        assert e.correlation_references[0].value == "dlk-uuid-001"

    @pytest.mark.asyncio
    async def test_slow_query_only_makes_exactly_one_call(self) -> None:
        now = datetime.now(UTC)
        slow_queries = [
            SlowQueryDomainDTO(
                query_hash="0xABC123",
                duration_ms=4500,
                cpu_time_ms=3000,
                logical_reads=12000,
                execution_count=5,
                last_execution_time=now,
                summary="SELECT * FROM confidential_table WHERE secret=1",
            ),
            SlowQueryDomainDTO(
                query_hash="0xABC123",  # Duplicate query hash
                duration_ms=6000,
                cpu_time_ms=4000,
                logical_reads=15000,
                execution_count=3,
                last_execution_time=now,
                summary="SELECT * FROM another_confidential_table",
            ),
        ]
        port = _FakeDiagnosticsPort(slow_queries=slow_queries)
        criteria = SlowQueryCriteriaDTO(min_duration_ms=2000)
        selection = DiagnosticsSelectionDTO(slow_query_criteria=criteria)
        collector = DiagnosticsEvidenceCollector(port, selection=selection)

        result = await collector.collect("inv-005", "opaque-key")

        assert result.status == SourceCollectionStatus.SUCCESS
        assert len(result.evidence) == 2
        assert port.health_calls == 0
        assert len(port.deadlock_calls) == 0
        assert len(port.slow_query_calls) == 1

        # Stable result index assignment for collision safety
        assert result.evidence[0].evidence_id == "diag:slow_query:0xABC123:0"
        assert result.evidence[1].evidence_id == "diag:slow_query:0xABC123:1"

        e = result.evidence[0]
        assert e.title == "Slow query observation"
        assert e.tags == ("diagnostics", "database", "slow_query")
        assert e.data == {
            "query_hash": "0xABC123",
            "duration_ms": 4500,
            "cpu_time_ms": 3000,
            "logical_reads": 12000,
            "execution_count": 5,
        }
        # Verify no raw SQL or summary leakage
        assert "summary" not in e.data
        assert "sql" not in e.data

        assert len(e.correlation_references) == 1
        assert e.correlation_references[0].namespace == "query_hash"
        assert e.correlation_references[0].value == "0xABC123"

    @pytest.mark.asyncio
    async def test_all_three_selected_makes_exactly_three_calls(self) -> None:
        port = _FakeDiagnosticsPort(
            slow_queries=[
                SlowQueryDomainDTO(
                    query_hash="0x111",
                    duration_ms=1500,
                    last_execution_time=datetime.now(UTC),
                )
            ],
            deadlocks=[
                DeadlockDomainDTO(
                    deadlock_id="dlk-001",
                    occurred_at=datetime.now(UTC),
                    victim_session_id=1,
                    participating_session_count=2,
                )
            ],
        )
        selection = DiagnosticsSelectionDTO(
            include_database_health=True,
            deadlock_criteria=DeadlockCriteriaDTO(),
            slow_query_criteria=SlowQueryCriteriaDTO(),
        )
        collector = DiagnosticsEvidenceCollector(port, selection=selection)

        result = await collector.collect("inv-006", "opaque-key")

        assert result.status == SourceCollectionStatus.SUCCESS
        assert port.health_calls == 1
        assert len(port.deadlock_calls) == 1
        assert len(port.slow_query_calls) == 1
        # 1 health + 1 deadlock + 1 slow query = 3
        assert len(result.evidence) == 3

    @pytest.mark.asyncio
    async def test_health_succeeds_deadlock_fails_returns_failed_empty_evidence(self) -> None:
        """Atomic failure: health succeeds, deadlock fails -> FAILED with evidence == ()."""
        port = _FakeDiagnosticsPort(deadlock_error=True)
        selection = DiagnosticsSelectionDTO(
            include_database_health=True,
            deadlock_criteria=DeadlockCriteriaDTO(),
        )
        collector = DiagnosticsEvidenceCollector(port, selection=selection)

        result = await collector.collect("inv-fail-1", "opaque-key")

        assert result.status == SourceCollectionStatus.FAILED
        assert result.error_code == "DIAGNOSTICS_RETRIEVAL_FAILED"
        assert len(result.evidence) == 0
        assert "unexpected error" in (result.error_message or "").lower()
        # Verify no intermediate health evidence leaked
        assert result.evidence == ()

    @pytest.mark.asyncio
    async def test_deadlock_succeeds_slow_query_fails_returns_failed_empty_evidence(self) -> None:
        """Atomic failure: deadlock succeeds, slow query fails -> FAILED with evidence == ()."""
        port = _FakeDiagnosticsPort(
            deadlocks=[
                DeadlockDomainDTO(
                    deadlock_id="dlk-002",
                    occurred_at=datetime.now(UTC),
                    victim_session_id=2,
                    participating_session_count=2,
                )
            ],
            slow_query_error=True,
        )
        selection = DiagnosticsSelectionDTO(
            deadlock_criteria=DeadlockCriteriaDTO(),
            slow_query_criteria=SlowQueryCriteriaDTO(),
        )
        collector = DiagnosticsEvidenceCollector(port, selection=selection)

        result = await collector.collect("inv-fail-2", "opaque-key")

        assert result.status == SourceCollectionStatus.FAILED
        assert result.error_code == "DIAGNOSTICS_RETRIEVAL_FAILED"
        assert len(result.evidence) == 0
        # Verify no intermediate deadlock evidence leaked
        assert result.evidence == ()

    @pytest.mark.asyncio
    async def test_health_succeeds_deadlock_succeeds_slow_query_fails_returns_failed(self) -> None:
        """Atomic failure: health & deadlock succeed, slow query fails
        -> FAILED with evidence == ().
        """
        port = _FakeDiagnosticsPort(
            deadlocks=[
                DeadlockDomainDTO(
                    deadlock_id="dlk-003",
                    occurred_at=datetime.now(UTC),
                    victim_session_id=3,
                    participating_session_count=2,
                )
            ],
            slow_query_error=True,
        )
        selection = DiagnosticsSelectionDTO(
            include_database_health=True,
            deadlock_criteria=DeadlockCriteriaDTO(),
            slow_query_criteria=SlowQueryCriteriaDTO(),
        )
        collector = DiagnosticsEvidenceCollector(port, selection=selection)

        result = await collector.collect("inv-fail-3", "opaque-key")

        assert result.status == SourceCollectionStatus.FAILED
        assert result.error_code == "DIAGNOSTICS_RETRIEVAL_FAILED"
        assert len(result.evidence) == 0
        assert result.evidence == ()

    @pytest.mark.asyncio
    async def test_service_is_none_with_selections_returns_failed(self) -> None:
        selection = DiagnosticsSelectionDTO(include_database_health=True)
        collector = DiagnosticsEvidenceCollector(service=None, selection=selection)

        result = await collector.collect("inv-009", "opaque-key")

        assert result.status == SourceCollectionStatus.FAILED
        assert result.error_code == "DIAGNOSTICS_SERVICE_UNAVAILABLE"
        assert len(result.evidence) == 0

    @pytest.mark.asyncio
    async def test_mapping_failure_on_deadlock_propagates_validation_error(self) -> None:
        """Integrity failure during deadlock evidence construction propagates."""
        mock_deadlock = MagicMock()
        mock_deadlock.deadlock_id = ""  # Empty string violates CorrelationReference validation
        mock_deadlock.occurred_at = datetime.now(UTC)
        mock_deadlock.victim_session_id = 1
        mock_deadlock.participating_session_count = 2

        mock_port = MagicMock()
        mock_result = MagicMock()
        mock_result.items = (mock_deadlock,)
        mock_port.find_deadlocks = AsyncMock(return_value=mock_result)

        selection = DiagnosticsSelectionDTO(deadlock_criteria=DeadlockCriteriaDTO())
        collector = DiagnosticsEvidenceCollector(mock_port, selection=selection)

        with pytest.raises(ValidationError):
            await collector.collect("inv-map-fail", "opaque-key")

    @pytest.mark.asyncio
    async def test_mapping_failure_on_slow_query_propagates_validation_error(self) -> None:
        """Integrity failure during slow query evidence construction propagates."""
        mock_slow = MagicMock()
        mock_slow.query_hash = ""  # Empty string violates CorrelationReference validation
        mock_slow.duration_ms = 1000
        mock_slow.cpu_time_ms = 500
        mock_slow.logical_reads = 100
        mock_slow.execution_count = 1
        mock_slow.last_execution_time = datetime.now(UTC)

        mock_port = MagicMock()
        mock_result = MagicMock()
        mock_result.items = (mock_slow,)
        mock_port.find_slow_queries = AsyncMock(return_value=mock_result)

        selection = DiagnosticsSelectionDTO(slow_query_criteria=SlowQueryCriteriaDTO())
        collector = DiagnosticsEvidenceCollector(mock_port, selection=selection)

        with pytest.raises(ValidationError):
            await collector.collect("inv-map-fail", "opaque-key")

    @pytest.mark.asyncio
    async def test_error_logging_contains_no_sensitive_metadata_or_investigation_id(self) -> None:
        """Collector error logs must not contain investigation_id, deadlock_id, or raw exception."""
        port = _FakeDiagnosticsPort(deadlock_error=True)
        selection = DiagnosticsSelectionDTO(deadlock_criteria=DeadlockCriteriaDTO())
        collector = DiagnosticsEvidenceCollector(port, selection=selection)

        patch_target = "platform_investigation_service.collectors.diagnostics_collector.logger"
        with patch(patch_target) as mock_logger:
            result = await collector.collect("secret-inv-id-999", "secret-corr-key-111")

            assert result.status == SourceCollectionStatus.FAILED
            mock_logger.error.assert_called_once()
            call_args, call_kwargs = mock_logger.error.call_args

            assert "Deadlock search failed" in call_args[0]
            assert call_kwargs.get("error_code") == "DIAG_DEADLOCK_FAILED"
            assert "investigation_id" not in call_kwargs
            assert "secret-inv-id-999" not in str(call_kwargs)
            assert "deadlock-proc-55" not in str(call_kwargs)
