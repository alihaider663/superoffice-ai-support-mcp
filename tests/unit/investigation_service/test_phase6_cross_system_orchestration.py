# ruff: noqa: ARG002, E501
"""Unit tests for Phase 6 Full Cross-System Incident Investigation Orchestration.

Verifies:
1. KnowledgeEvidenceCollector live retrieval and unconfigured fallback
2. DiagnosticLogsEvidenceCollector live retrieval and blocked fallback
3. SuperOfficeEvidenceCollector ticket audit trail integration
4. DiagnosticsEvidenceCollector ticket diagnostics and blocking sessions integration
5. HypothesisEvaluatorEngine activation and deterministic evaluation
6. End-to-end 4-source orchestration cycle
"""

from datetime import UTC, datetime

import pytest

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
from kb_mcp.contracts.dtos import (
    KnowledgeSearchCriteriaDTO,
    KnowledgeSearchResultDomainDTO,
    KnownIssueDomainDTO,
    KnownIssueSearchCriteriaDTO,
    RunbookDetailDomainDTO,
)
from kb_mcp.contracts.errors import KnowledgeBackendNotConfiguredError
from platform_investigation.evaluator import HypothesisEvaluatorEngine
from platform_investigation.models import (
    EvidenceSourceType,
    HypothesisEvaluationOutcome,
    InvestigationStatus,
    SourceCollectionStatus,
)
from platform_investigation.orchestrator import InvestigationOrchestratorEngine
from platform_investigation.timeline import IncidentCorrelationEngine
from platform_investigation_service.collectors.knowledge_collector import (
    KnowledgeEvidenceCollector,
)
from platform_investigation_service.collectors.logs_collector import (
    DiagnosticLogsEvidenceCollector,
)
from platform_investigation_service.models import (
    DiagnosticsSelectionDTO,
    InvestigationRequest,
    InvestigationResult,
    KnowledgeSelectionDTO,
    LogsSelectionDTO,
    SuperOfficeSelectionDTO,
)
from platform_investigation_service.ports import (
    DiagnosticsServicePort,
    KnowledgeServicePort,
    LogsServicePort,
    SuperOfficeServicePort,
)
from platform_investigation_service.service import InvestigationApplicationService
from so_mcp.audit.contracts import TicketActionItemDTO, TicketAuditTrailDTO, TicketFieldChangeDTO
from so_mcp.contracts.dtos import MinimizedTicketDetailDTO


class FakeSuperOfficeService(SuperOfficeServicePort):
    """Fake SuperOffice service providing tickets and audit trails."""

    def __init__(self) -> None:
        self.get_ticket_calls: list[int] = []
        self.get_audit_calls: list[int] = []

    async def get_ticket(self, ticket_id: int) -> MinimizedTicketDetailDTO:
        self.get_ticket_calls.append(ticket_id)
        return MinimizedTicketDetailDTO(
            ticket_id=ticket_id,
            title="Database contention during order submission",
            status="Open",
            category="Ordering",
            priority="Critical",
            sanitized_description="Users report timeouts when completing checkout.",
            created_at=datetime(2026, 9, 25, 8, 30, tzinfo=UTC),
        )

    async def get_ticket_audit_trail(
        self,
        ticket_id: int,
        include_field_changes: bool = True,
        limit: int = 50,
    ) -> TicketAuditTrailDTO:
        self.get_audit_calls.append(ticket_id)
        return TicketAuditTrailDTO(
            ticket_id=ticket_id,
            actions=(
                TicketActionItemDTO(
                    action_id=501,
                    occurred_at=datetime(2026, 9, 25, 8, 31, tzinfo=UTC),
                    actor="system_auto_triage",
                    user_id=1,
                    customer_id=-1,
                    action_code=13,
                    action_name="Priority escalated",
                    description="Priority escalated from High to Critical",
                    changes=(
                        TicketFieldChangeDTO(
                            id=1001,
                            action_id=501,
                            field_name="priority_id",
                            display_name="Priority",
                            from_value="High",
                            to_value="Critical",
                        ),
                    ),
                ),
            ),
            total_actions=1,
            total_changes=1,
        )


class FakeDiagnosticsService(DiagnosticsServicePort, LogsServicePort):
    """Fake Diagnostics and Logs service."""

    def __init__(self) -> None:
        self.health_calls = 0
        self.deadlock_calls = 0
        self.slow_query_calls = 0
        self.ticket_diag_calls = 0
        self.blocking_calls = 0
        self.log_calls = 0

    async def get_database_health(self) -> DatabaseHealthDomainDTO:
        self.health_calls += 1
        return DatabaseHealthDomainDTO(
            is_healthy=True,
            status_summary="ONLINE",
            active_connections=42,
            latency_ms=2.1,
            collected_at=datetime(2026, 9, 25, 8, 35, tzinfo=UTC),
        )

    async def find_deadlocks(
        self, criteria: DeadlockCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[DeadlockDomainDTO]:
        self.deadlock_calls += 1
        return BoundedDiagnosticResultDTO[DeadlockDomainDTO](
            items=(
                DeadlockDomainDTO(
                    deadlock_id="dlk-phase6-001",
                    occurred_at=datetime(2026, 9, 25, 8, 32, tzinfo=UTC),
                    victim_session_id=105,
                    participating_session_count=2,
                ),
            ),
            returned_count=1,
            total_matched=1,
            is_truncated=False,
        )

    async def find_slow_queries(
        self, criteria: SlowQueryCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[SlowQueryDomainDTO]:
        self.slow_query_calls += 1
        return BoundedDiagnosticResultDTO[SlowQueryDomainDTO](
            items=(
                SlowQueryDomainDTO(
                    query_hash="0xDEADBEEF1234",
                    duration_ms=5400,
                    cpu_time_ms=3200,
                    logical_reads=120000,
                    execution_count=8,
                    last_execution_time=datetime(2026, 9, 25, 8, 33, tzinfo=UTC),
                ),
            ),
            returned_count=1,
            total_matched=1,
            is_truncated=False,
        )

    async def get_ticket_diagnostic_record(
        self, ticket_id: int
    ) -> TicketDiagnosticRecordDomainDTO | None:
        self.ticket_diag_calls += 1
        return TicketDiagnosticRecordDomainDTO(
            ticket_id=ticket_id,
            has_db_activity=True,
            recent_error_count=3,
            last_activity_time=datetime(2026, 9, 25, 8, 34, tzinfo=UTC),
            diagnostic_summary=f"3 database timeout errors recorded for ticket #{ticket_id}.",
        )

    async def find_blocking_sessions(
        self, criteria: BlockingSessionCriteriaDTO | None = None
    ) -> BoundedDiagnosticResultDTO[BlockingSessionDomainDTO]:
        self.blocking_calls += 1
        return BoundedDiagnosticResultDTO[BlockingSessionDomainDTO](
            items=(
                BlockingSessionDomainDTO(
                    blocking_session_id=98,
                    blocked_session_id=105,
                    wait_duration_ms=45000,
                    wait_type="LCK_M_X",
                    detected_at=datetime(2026, 9, 25, 8, 35, tzinfo=UTC),
                ),
            ),
            returned_count=1,
            total_matched=1,
            is_truncated=False,
        )

    async def search_logs(
        self, query: str, limit: int = 20
    ) -> BoundedDiagnosticResultDTO[SanitizedLogExcerptDTO]:
        self.log_calls += 1
        return BoundedDiagnosticResultDTO[SanitizedLogExcerptDTO](
            items=(
                SanitizedLogExcerptDTO(
                    excerpt_id="log-phase6-901",
                    timestamp=datetime(2026, 9, 25, 8, 32, 30, tzinfo=UTC),
                    service_name="OrderService",
                    severity="ERROR",
                    sanitized_message="Transaction deadlock encountered during checkout commit.",
                    correlation_id="corr-checkout-889",
                ),
            ),
            returned_count=1,
            total_matched=1,
            is_truncated=False,
        )


class FakeKnowledgeService(KnowledgeServicePort):
    """Fake Knowledge Base service."""

    def __init__(self, *, not_configured: bool = False) -> None:
        self.not_configured = not_configured
        self.find_issues_calls = 0
        self.search_knowledge_calls = 0

    async def find_known_issues(
        self, criteria: KnownIssueSearchCriteriaDTO
    ) -> list[KnownIssueDomainDTO]:
        if self.not_configured:
            raise KnowledgeBackendNotConfiguredError("Knowledge backend unconfigured")
        self.find_issues_calls += 1
        return [
            KnownIssueDomainDTO(
                issue_id="KI-CHECKOUT-004",
                title="Concurrent checkout order deadlock under high concurrency",
                symptom_summary="Users encounter transaction deadlocks when submitting orders simultaneously.",
                root_cause_summary="Lock escalation on order lines table when updating inventory balances.",
                workaround="Apply rowlock hint in checkout transaction or enable read committed snapshot isolation.",
                permanent_fix_reference="HOTFIX-2026-09",
                affected_products=("SuperOffice Service", "OrderModule"),
                category="database",
                source_reference="KB-REF-100",
            )
        ]

    async def search_knowledge(
        self, criteria: KnowledgeSearchCriteriaDTO
    ) -> list[KnowledgeSearchResultDomainDTO]:
        if self.not_configured:
            raise KnowledgeBackendNotConfiguredError("Knowledge backend unconfigured")
        self.search_knowledge_calls += 1
        return [
            KnowledgeSearchResultDomainDTO(
                document_id="doc-rb-deadlock-101",
                title="Troubleshooting MSSQL Deadlocks and Concurrency",
                content_excerpt="When investigating deadlocks, inspect lock resources and participating sessions.",
                category="troubleshooting",
                relevance_score=0.92,
                source_reference="RB-MSSQL-002",
            )
        ]

    async def get_runbook(self, runbook_id: str) -> RunbookDetailDomainDTO | None:
        return None


# ============================================================================
# Test Cases
# ============================================================================


@pytest.mark.asyncio
async def test_knowledge_collector_success() -> None:
    """KnowledgeEvidenceCollector returns SUCCESS with verified known issues."""
    kb_svc = FakeKnowledgeService()
    collector = KnowledgeEvidenceCollector(
        service=kb_svc,
        selection=KnowledgeSelectionDTO(limit=5),
        query_context="checkout deadlock",
    )

    result = await collector.collect("inv-test", "corr-test")

    assert result.status == SourceCollectionStatus.SUCCESS
    assert len(result.evidence) == 2  # 1 known issue + 1 doc
    assert result.source_type == EvidenceSourceType.KNOWLEDGE_BASE

    issue_ev = next(e for e in result.evidence if "known_issue" in e.tags)
    assert issue_ev.data["issue_id"] == "KI-CHECKOUT-004"
    assert "workaround" in issue_ev.data


@pytest.mark.asyncio
async def test_knowledge_collector_unconfigured_fallback() -> None:
    """KnowledgeEvidenceCollector gracefully returns NOT_CONFIGURED when service is None."""
    collector = KnowledgeEvidenceCollector(service=None)
    result = await collector.collect("inv-test", "corr-test")

    assert result.status == SourceCollectionStatus.NOT_CONFIGURED
    assert result.error_code == "KNOWLEDGE_BASE_NOT_CONFIGURED"
    assert len(result.evidence) == 0


@pytest.mark.asyncio
async def test_logs_collector_success() -> None:
    """DiagnosticLogsEvidenceCollector returns SUCCESS with sanitized excerpts."""
    diag_svc = FakeDiagnosticsService()
    collector = DiagnosticLogsEvidenceCollector(
        service=diag_svc,
        selection=LogsSelectionDTO(include_logs=True, query="deadlock", limit=10),
    )

    result = await collector.collect("inv-test", "corr-test")

    assert result.status == SourceCollectionStatus.SUCCESS
    assert len(result.evidence) == 1
    assert result.source_type == EvidenceSourceType.APPLICATION_LOGS
    log_ev = result.evidence[0]
    assert log_ev.data["severity"] == "ERROR"
    assert "deadlock" in log_ev.data["sanitized_message"]


@pytest.mark.asyncio
async def test_logs_collector_not_requested_blocked_fallback() -> None:
    """DiagnosticLogsEvidenceCollector returns BLOCKED when include_logs is False."""
    collector = DiagnosticLogsEvidenceCollector(
        service=FakeDiagnosticsService(),
        selection=LogsSelectionDTO(include_logs=False),
    )

    result = await collector.collect("inv-test", "corr-test")

    assert result.status == SourceCollectionStatus.BLOCKED
    assert result.error_code == "DIAGNOSTIC_LOGS_BLOCKED"
    assert len(result.evidence) == 0


@pytest.mark.asyncio
async def test_full_cross_system_investigation_orchestration() -> None:
    """Execute complete 4-source cross-system investigation cycle in Phase 6."""
    so_svc = FakeSuperOfficeService()
    diag_svc = FakeDiagnosticsService()
    kb_svc = FakeKnowledgeService()

    orchestrator = InvestigationOrchestratorEngine()
    correlator = IncidentCorrelationEngine()
    evaluator = HypothesisEvaluatorEngine()

    service = InvestigationApplicationService(
        orchestrator=orchestrator,
        superoffice_service=so_svc,
        diagnostics_service=diag_svc,
        knowledge_service=kb_svc,
        logs_service=diag_svc,
        correlator=correlator,
        evaluator=evaluator,
    )

    request = InvestigationRequest(
        correlation_key="ticket:10209",
        initial_hypothesis="Deadlock contention during checkout order submission",
        ticket_id=10209,
        so_selection=SuperOfficeSelectionDTO(include_audit_trail=True),
        diagnostics_selection=DiagnosticsSelectionDTO(
            include_database_health=True,
            deadlock_criteria=DeadlockCriteriaDTO(),
            slow_query_criteria=SlowQueryCriteriaDTO(),
            include_ticket_diagnostic=True,
            include_blocking_sessions=True,
        ),
        logs_selection=LogsSelectionDTO(include_logs=True, query="checkout"),
        knowledge_selection=KnowledgeSelectionDTO(include_knowledge_search=True),
    )

    result = await service.investigate(request)

    assert isinstance(result, InvestigationResult)
    assert result.plan.status == InvestigationStatus.IN_PROGRESS
    assert result.plan.current_step_count == 1

    # Authoritative 4-source registration order
    assert result.aggregation.total_sources == 4
    source_order = [o.source_type for o in result.aggregation.source_outcomes]
    assert source_order == [
        EvidenceSourceType.SUPEROFFICE_CRM,
        EvidenceSourceType.MSSQL_DIAGNOSTICS,
        EvidenceSourceType.APPLICATION_LOGS,
        EvidenceSourceType.KNOWLEDGE_BASE,
    ]

    # All 4 sources successful
    assert result.aggregation.successful_sources_count == 4
    for outcome in result.aggregation.source_outcomes:
        assert outcome.status == SourceCollectionStatus.SUCCESS

    # Verify multi-source evidence inventory:
    # SO: 1 ticket + 1 audit action = 2
    # Diag: 1 health + 1 deadlock + 1 slow query + 1 ticket diag + 1 blocking = 5
    # Logs: 1 log excerpt = 1
    # KB: 1 known issue + 1 article = 2
    # Total = 10 evidence items
    assert len(result.aggregation.evidence) == 10

    # Verify chronological timeline built
    assert result.timeline.total_events == 10

    # Verify Hypothesis Evaluator derived SUPPORTED (deadlocks, error logs, and known issues support hypothesis)
    assert result.hypothesis_evaluation is not None
    assert result.hypothesis_evaluation.outcome == HypothesisEvaluationOutcome.SUPPORTED
