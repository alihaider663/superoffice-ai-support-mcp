"""Unit tests for Phase 4 performance optimizations, concurrency, and connection pooling."""

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from pydantic import HttpUrl

from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    DatabaseHealthDomainDTO,
    DeadlockCriteriaDTO,
    DeadlockDomainDTO,
    SlowQueryCriteriaDTO,
    SlowQueryDomainDTO,
)
from platform_config.gateway import GatewaySettings
from platform_gateway.adapters.http_dispatcher import HttpToolDispatcher, PooledTransport
from platform_gateway.registry import GatewayBackendRegistry
from platform_gateway.server.app import create_gateway_app
from platform_gateway.services.gateway_service import GatewayApplicationService
from platform_investigation.aggregator import EvidenceAggregatorEngine
from platform_investigation.interfaces import OutcomeAwareEvidenceCollector
from platform_investigation.models import (
    DiagnosticEvidence,
    EvidenceSourceType,
    SourceCollectionResult,
    SourceCollectionStatus,
)
from platform_investigation_service.collectors.diagnostics_collector import (
    DiagnosticsEvidenceCollector,
)
from platform_investigation_service.models import DiagnosticsSelectionDTO


class DelayedMockCollector(OutcomeAwareEvidenceCollector):
    """Mock collector simulating downstream I/O latency."""

    def __init__(
        self,
        source_type: EvidenceSourceType,
        delay_seconds: float,
        should_fail: bool = False,
    ) -> None:
        self._source_type = source_type
        self._delay = delay_seconds
        self._should_fail = should_fail

    @property
    def source_type(self) -> EvidenceSourceType:
        return self._source_type

    async def collect(
        self,
        investigation_id: str,  # noqa: ARG002
        correlation_key: str,  # noqa: ARG002
    ) -> SourceCollectionResult:
        await asyncio.sleep(self._delay)
        if self._should_fail:
            raise RuntimeError(f"Simulated collector failure for {self._source_type.value}")
        return SourceCollectionResult(
            source_type=self._source_type,
            status=SourceCollectionStatus.SUCCESS,
            evidence=(
                DiagnosticEvidence(
                    evidence_id=f"ev-{self._source_type.value}-001",
                    source_type=self._source_type,
                    title=f"Mock evidence for {self._source_type.value}",
                    data={"collected": True},
                ),
            ),
        )


class DelayedFakeDiagnosticsPort:
    """Fake DiagnosticsServicePort with simulated call latency."""

    def __init__(self, delay_seconds: float = 0.05) -> None:
        self.delay = delay_seconds

    async def get_database_health(self) -> DatabaseHealthDomainDTO:
        await asyncio.sleep(self.delay)
        return DatabaseHealthDomainDTO(
            is_healthy=True,
            status_summary="HEALTHY_ONLINE",
            active_connections=25,
            latency_ms=1.8,
            collected_at=datetime.now(UTC),
        )

    async def find_deadlocks(
        self,
        criteria: DeadlockCriteriaDTO,  # noqa: ARG002
    ) -> BoundedDiagnosticResultDTO[DeadlockDomainDTO]:
        await asyncio.sleep(self.delay)
        return BoundedDiagnosticResultDTO[DeadlockDomainDTO](
            items=(),
            returned_count=0,
            is_truncated=False,
        )

    async def find_slow_queries(
        self,
        criteria: SlowQueryCriteriaDTO,  # noqa: ARG002
    ) -> BoundedDiagnosticResultDTO[SlowQueryDomainDTO]:
        await asyncio.sleep(self.delay)
        return BoundedDiagnosticResultDTO[SlowQueryDomainDTO](
            items=(),
            returned_count=0,
            is_truncated=False,
        )


@pytest.mark.asyncio
async def test_evidence_aggregator_runs_collectors_concurrently() -> None:
    """EvidenceAggregatorEngine executes outcome-aware collectors concurrently."""
    delay = 0.06
    c1 = DelayedMockCollector(EvidenceSourceType.SUPEROFFICE_CRM, delay)
    c2 = DelayedMockCollector(EvidenceSourceType.MSSQL_DIAGNOSTICS, delay)
    c3 = DelayedMockCollector(EvidenceSourceType.APPLICATION_LOGS, delay)

    engine = EvidenceAggregatorEngine(collectors=[c1, c2, c3])

    start_time = time.monotonic()
    result = await engine.aggregate("inv-perf-01", "corr-perf-01")
    elapsed = time.monotonic() - start_time

    assert result.has_failures is False
    assert len(result.source_outcomes) == 3
    # Sequential would take >= 3 * 0.06 = 0.18s; concurrent should take < 0.14s
    assert elapsed < (delay * 2.3)
    # Ensure registration order is strictly preserved
    assert [r.source_type for r in result.source_outcomes] == [
        EvidenceSourceType.SUPEROFFICE_CRM,
        EvidenceSourceType.MSSQL_DIAGNOSTICS,
        EvidenceSourceType.APPLICATION_LOGS,
    ]


@pytest.mark.asyncio
async def test_evidence_aggregator_resilience_under_concurrency() -> None:
    """Failing collector during concurrent execution does not abort sibling collectors."""
    c1 = DelayedMockCollector(EvidenceSourceType.SUPEROFFICE_CRM, 0.02)
    c2 = DelayedMockCollector(EvidenceSourceType.MSSQL_DIAGNOSTICS, 0.02, should_fail=True)
    c3 = DelayedMockCollector(EvidenceSourceType.APPLICATION_LOGS, 0.02)

    engine = EvidenceAggregatorEngine(collectors=[c1, c2, c3])
    result = await engine.aggregate("inv-perf-02", "corr-perf-02")

    assert result.has_failures is True
    assert len(result.source_outcomes) == 3
    assert result.source_outcomes[0].status == SourceCollectionStatus.SUCCESS
    assert result.source_outcomes[1].status == SourceCollectionStatus.FAILED
    assert result.source_outcomes[1].error_code == "SOURCE_EXECUTION_FAILED"
    assert result.source_outcomes[2].status == SourceCollectionStatus.SUCCESS


@pytest.mark.asyncio
async def test_diagnostics_collector_runs_queries_concurrently() -> None:
    """DiagnosticsEvidenceCollector gathers health, deadlocks, and slow queries concurrently."""
    delay = 0.05
    port = DelayedFakeDiagnosticsPort(delay_seconds=delay)
    collector = DiagnosticsEvidenceCollector(
        service=port,
        selection=DiagnosticsSelectionDTO(
            include_database_health=True,
            deadlock_criteria=DeadlockCriteriaDTO(),
            slow_query_criteria=SlowQueryCriteriaDTO(),
        ),
    )

    start_time = time.monotonic()
    res = await collector.collect("inv-diag-01", "corr-diag-01")
    elapsed = time.monotonic() - start_time

    assert res.status == SourceCollectionStatus.SUCCESS
    assert len(res.evidence) == 1
    # Sequential would take >= 3 * 0.05 = 0.15s; concurrent takes < 0.12s
    assert elapsed < (delay * 2.4)




@pytest.mark.asyncio
async def test_http_dispatcher_connection_pool_and_lifecycle() -> None:
    """HttpToolDispatcher maintains persistent transport pool and cleans up on aclose."""
    settings = GatewaySettings(
        superoffice_mcp_url=HttpUrl("http://so-server:8001"),
        diagnostics_mcp_url=HttpUrl("http://diag-server:8002"),
        knowledge_mcp_url=HttpUrl("http://kb-server:8003"),
        infrastructure_mcp_url=HttpUrl("http://infra-server:8004"),
    )
    registry = GatewayBackendRegistry(settings)
    dispatcher = HttpToolDispatcher(backend_registry=registry)

    # Validate transport initialization
    assert dispatcher._transport is not None
    assert isinstance(dispatcher._transport, httpx.AsyncHTTPTransport)

    # Test PooledTransport does not close underlying transport on client close
    pooled = PooledTransport(dispatcher._transport)
    await pooled.aclose()  # Should be a no-op

    # Test dispatcher aclose closes the transport
    with patch.object(dispatcher._transport, "aclose", new_callable=AsyncMock) as mock_aclose:
        await dispatcher.aclose()
        mock_aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_service_aclose_lifecycle() -> None:
    """GatewayApplicationService delegates aclose to its underlying dispatcher."""
    mock_dispatcher = AsyncMock()
    mock_dispatcher.aclose = AsyncMock()

    service = GatewayApplicationService(
        routing_table=AsyncMock(),
        dispatcher=mock_dispatcher,
        authenticator=AsyncMock(),
        authorizer=AsyncMock(),
    )

    assert service.dispatcher is mock_dispatcher
    await service.aclose()
    mock_dispatcher.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_app_lifespan_calls_aclose() -> None:
    """Starlette Gateway app lifespan cleans up active_service connection pools on shutdown."""
    mock_service = AsyncMock(spec=GatewayApplicationService)
    mock_service.aclose = AsyncMock()

    app = create_gateway_app(service=mock_service)
    async with app.router.lifespan_context(app):
        pass

    mock_service.aclose.assert_awaited_once()


