"""Internal cross-package integration tests for Phase 3.5 Investigation Service.

Verifies end-to-end composition of:
- Layer-4 InvestigationApplicationService
- Layer-4 concrete evidence collectors (SuperOffice, Diagnostics, Knowledge, Logs)
- Layer-3 InvestigationOrchestratorEngine
- Layer-3 EvidenceAggregatorEngine
- Layer-3 IncidentCorrelationEngine
- Real InMemoryInvestigationStore
- Injected fake domain service ports
"""

from datetime import UTC, datetime

import pytest

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
    InvestigationStatus,
    SourceCollectionStatus,
)
from platform_investigation.orchestrator import InvestigationOrchestratorEngine
from platform_investigation.store import InMemoryInvestigationStore
from platform_investigation.timeline import IncidentCorrelationEngine
from platform_investigation_service.models import (
    DiagnosticsSelectionDTO,
    InvestigationRequest,
    InvestigationResult,
)
from platform_investigation_service.service import InvestigationApplicationService
from so_mcp.contracts.dtos import MinimizedTicketDetailDTO


class _IntegrationSuperOfficeService:
    """Fake SuperOffice service with deterministic test data."""

    def __init__(self) -> None:
        self.call_history: list[int] = []

    async def get_ticket(self, ticket_id: int) -> MinimizedTicketDetailDTO:
        self.call_history.append(ticket_id)
        return MinimizedTicketDetailDTO(
            ticket_id=ticket_id,
            title="Customer Portal 504 Gateway Timeout",
            status="Open",
            category="Infrastructure",
            priority="Critical",
            sanitized_description="Users experiencing 504 Gateway Timeout on login page.",
            sanitized_customer_reference="CUST-ACME-CORP",
            assigned_agent_id="AGENT-L2-01",
            created_at=datetime.now(UTC),
        )


class _IntegrationDiagnosticsService:
    """Fake Diagnostics service with deterministic test data."""

    def __init__(self) -> None:
        self.health_calls = 0
        self.deadlock_calls = 0
        self.slow_query_calls = 0

    async def get_database_health(self) -> DatabaseHealthDomainDTO:
        self.health_calls += 1
        return DatabaseHealthDomainDTO(
            is_healthy=True,
            status_summary="ONLINE",
            active_connections=85,
            latency_ms=4.8,
            collected_at=datetime.now(UTC),
        )

    async def find_deadlocks(
        self, criteria: DeadlockCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[DeadlockDomainDTO]:
        _ = criteria
        self.deadlock_calls += 1
        return BoundedDiagnosticResultDTO[DeadlockDomainDTO](
            items=(
                DeadlockDomainDTO(
                    deadlock_id="dlk-e2e-888",
                    occurred_at=datetime.now(UTC),
                    victim_session_id=72,
                    participating_session_count=2,
                    resource_description="KEY: 6:72057594041794560",
                    summary="Deadlock between spid 72 and spid 85 on tbl_ticket",
                ),
            ),
            returned_count=1,
            total_matched=1,
            is_truncated=False,
        )

    async def find_slow_queries(
        self, criteria: SlowQueryCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[SlowQueryDomainDTO]:
        _ = criteria
        self.slow_query_calls += 1
        return BoundedDiagnosticResultDTO[SlowQueryDomainDTO](
            items=(
                SlowQueryDomainDTO(
                    query_hash="0xDEADBEEF01",
                    duration_ms=12500,
                    cpu_time_ms=9000,
                    logical_reads=450000,
                    execution_count=14,
                    last_execution_time=datetime.now(UTC),
                    summary="SELECT * FROM ticket_messages WHERE body LIKE '%error%'",
                ),
            ),
            returned_count=1,
            total_matched=1,
            is_truncated=False,
        )


@pytest.mark.asyncio
async def test_end_to_end_internal_investigation_integration() -> None:
    """End-to-end integration test verifying full composition with real engines."""
    # 1. Setup real Layer-3 store and engines
    store = InMemoryInvestigationStore()
    orchestrator = InvestigationOrchestratorEngine(store=store, default_max_steps=15)
    correlator = IncidentCorrelationEngine()

    # 2. Setup domain service fakes
    so_service = _IntegrationSuperOfficeService()
    diag_service = _IntegrationDiagnosticsService()

    # 3. Setup Layer-4 service
    service = InvestigationApplicationService(
        orchestrator=orchestrator,
        superoffice_service=so_service,
        diagnostics_service=diag_service,
        correlator=correlator,
    )

    # 4. Construct typed investigation request
    selection = DiagnosticsSelectionDTO(
        include_database_health=True,
        deadlock_criteria=DeadlockCriteriaDTO(limit=5),
        slow_query_criteria=SlowQueryCriteriaDTO(min_duration_ms=5000),
    )
    request = InvestigationRequest(
        correlation_key="inc-2026-09-01-portal-outage",
        initial_hypothesis="Deadlock on tbl_ticket during peak message ingestion",
        ticket_id=50412,
        diagnostics_selection=selection,
        max_steps=12,
    )

    # 5. Execute investigation
    result = await service.investigate(request)

    # 6. Verify result integrity
    assert isinstance(result, InvestigationResult)
    inv_id = result.investigation_id
    assert inv_id is not None

    # Verify plan in store
    saved_plan = await store.get_plan(inv_id)
    assert saved_plan is not None
    assert saved_plan.max_steps == 12
    assert saved_plan.status == InvestigationStatus.IN_PROGRESS
    assert saved_plan.current_step_count == 1
    assert saved_plan.concluded_root_cause is None
    assert len(saved_plan.hypotheses) == 1
    expected_desc = "Deadlock on tbl_ticket during peak message ingestion"
    assert saved_plan.hypotheses[0].description == expected_desc

    # Verify step
    step = saved_plan.steps[0]
    assert step.step_number == 1
    assert step.action_taken == "Multi-source diagnostic evidence collection and correlation"
    assert "Collected 4 evidence items" in step.summary
    assert step.severity == "INFO"
    assert step.correlation_keys == ("inc-2026-09-01-portal-outage",)
    assert len(step.collected_evidence_ids) == 4

    # Verify evidence aggregation
    assert result.aggregation.total_sources == 4
    assert result.aggregation.successful_sources_count == 2
    assert result.aggregation.has_failures is True  # Logs BLOCKED, KB NOT_CONFIGURED

    # Check individual sources
    outcomes = {o.source_type: o for o in result.aggregation.source_outcomes}
    assert outcomes[EvidenceSourceType.SUPEROFFICE_CRM].status == SourceCollectionStatus.SUCCESS
    assert outcomes[EvidenceSourceType.MSSQL_DIAGNOSTICS].status == SourceCollectionStatus.SUCCESS
    assert outcomes[EvidenceSourceType.APPLICATION_LOGS].status == SourceCollectionStatus.BLOCKED
    kb_outcome = outcomes[EvidenceSourceType.KNOWLEDGE_BASE]
    assert kb_outcome.status == SourceCollectionStatus.NOT_CONFIGURED

    # Verify timeline (4 events: 1 SO + 3 Diag)
    assert result.timeline.total_events == 4
    event_titles = [ev.title for ev in result.timeline.events]
    assert "SuperOffice ticket observation" in event_titles
    assert "Database health observation" in event_titles
    assert "Database deadlock observation" in event_titles
    assert "Slow query observation" in event_titles

    # Verify call counts
    assert so_service.call_history == [50412]
    assert diag_service.health_calls == 1
    assert diag_service.deadlock_calls == 1
    assert diag_service.slow_query_calls == 1
