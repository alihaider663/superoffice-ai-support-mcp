"""Unit tests for InvestigationApplicationService."""

from datetime import UTC, datetime

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
from platform_core.errors import DomainValidationError
from platform_investigation.models import (
    EvidenceSourceType,
    InvestigationStatus,
    SourceCollectionStatus,
)
from platform_investigation.orchestrator import InvestigationOrchestratorEngine
from platform_investigation.timeline import IncidentCorrelationEngine
from platform_investigation_service.models import (
    DiagnosticsSelectionDTO,
    InvestigationRequest,
    InvestigationResult,
)
from platform_investigation_service.service import InvestigationApplicationService
from so_mcp.contracts.dtos import MinimizedTicketDetailDTO


class _FakeSuperOfficeService:
    """Fake SuperOffice service for pipeline testing."""

    def __init__(self, *, raise_error: bool = False) -> None:
        self.get_ticket_calls: list[int] = []
        self._raise_error = raise_error

    async def get_ticket(self, ticket_id: int) -> MinimizedTicketDetailDTO:
        self.get_ticket_calls.append(ticket_id)
        if self._raise_error:
            raise RuntimeError("SO failure")
        return MinimizedTicketDetailDTO(
            ticket_id=ticket_id,
            title="Ticket Title",
            status="Open",
            category="Technical",
            priority="High",
            sanitized_description="Description",
            created_at=datetime.now(UTC),
        )


class _FakeDiagnosticsService:
    """Fake Diagnostics service for pipeline testing."""

    def __init__(
        self,
        *,
        health_error: bool = False,
        slow_query_error: bool = False,
        deadlock_error: bool = False,
    ) -> None:
        self.health_calls: int = 0
        self.slow_query_calls: int = 0
        self.deadlock_calls: int = 0
        self._health_error = health_error
        self._slow_query_error = slow_query_error
        self._deadlock_error = deadlock_error

    async def get_database_health(self) -> DatabaseHealthDomainDTO:
        self.health_calls += 1
        if self._health_error:
            raise RuntimeError("Health check failed")
        return DatabaseHealthDomainDTO(
            is_healthy=True,
            status_summary="ONLINE",
            active_connections=15,
            latency_ms=1.2,
            collected_at=datetime.now(UTC),
        )

    async def find_slow_queries(
        self, criteria: SlowQueryCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[SlowQueryDomainDTO]:
        _ = criteria
        self.slow_query_calls += 1
        if self._slow_query_error:
            raise RuntimeError("Slow query failed")
        return BoundedDiagnosticResultDTO[SlowQueryDomainDTO](
            items=(
                SlowQueryDomainDTO(
                    query_hash="0xQUERY1",
                    duration_ms=4000,
                    cpu_time_ms=2500,
                    logical_reads=8000,
                    execution_count=2,
                    last_execution_time=datetime.now(UTC),
                ),
            ),
            returned_count=1,
            total_matched=1,
            is_truncated=False,
        )

    async def find_deadlocks(
        self, criteria: DeadlockCriteriaDTO
    ) -> BoundedDiagnosticResultDTO[DeadlockDomainDTO]:
        _ = criteria
        self.deadlock_calls += 1
        if self._deadlock_error:
            raise RuntimeError("Deadlock failed")
        return BoundedDiagnosticResultDTO[DeadlockDomainDTO](
            items=(
                DeadlockDomainDTO(
                    deadlock_id="dlk-test-01",
                    occurred_at=datetime.now(UTC),
                    victim_session_id=12,
                    participating_session_count=2,
                ),
            ),
            returned_count=1,
            total_matched=1,
            is_truncated=False,
        )


def _build_service(
    *,
    so_service: _FakeSuperOfficeService | None = None,
    diag_service: _FakeDiagnosticsService | None = None,
) -> InvestigationApplicationService:
    orchestrator = InvestigationOrchestratorEngine()
    correlator = IncidentCorrelationEngine()
    return InvestigationApplicationService(
        orchestrator=orchestrator,
        superoffice_service=so_service or _FakeSuperOfficeService(),
        diagnostics_service=diag_service or _FakeDiagnosticsService(),
        correlator=correlator,
    )


class TestInvestigationApplicationService:
    """Tests for InvestigationApplicationService."""

    @pytest.mark.asyncio
    async def test_full_investigation_cycle(self) -> None:
        so_service = _FakeSuperOfficeService()
        diag_service = _FakeDiagnosticsService()
        service = _build_service(so_service=so_service, diag_service=diag_service)

        selection = DiagnosticsSelectionDTO(
            include_database_health=True,
            slow_query_criteria=SlowQueryCriteriaDTO(),
        )
        request = InvestigationRequest(
            correlation_key="ticket:10209",
            initial_hypothesis="Database connection pool exhaustion causing slow ticket responses",
            ticket_id=10209,
            diagnostics_selection=selection,
        )

        result = await service.investigate(request)

        assert isinstance(result, InvestigationResult)
        assert result.investigation_id == result.plan.investigation_id

        # Plan status remains IN_PROGRESS
        assert result.plan.status == InvestigationStatus.IN_PROGRESS
        assert result.plan.concluded_root_cause is None

        # Exactly 1 step recorded
        assert result.plan.current_step_count == 1
        assert len(result.plan.steps) == 1
        step = result.plan.steps[0]
        assert step.step_number == 1
        assert step.action_taken == "Multi-source diagnostic evidence collection and correlation"
        assert "Collected" in step.summary
        assert step.severity == "INFO"
        assert step.correlation_keys == ("ticket:10209",)

        # 4 registered sources in authoritative order
        assert result.aggregation.total_sources == 4
        source_order = [o.source_type for o in result.aggregation.source_outcomes]
        assert source_order == [
            EvidenceSourceType.SUPEROFFICE_CRM,
            EvidenceSourceType.MSSQL_DIAGNOSTICS,
            EvidenceSourceType.APPLICATION_LOGS,
            EvidenceSourceType.KNOWLEDGE_BASE,
        ]

        # 1 SO + 2 Diag = 3 evidence items
        assert len(result.aggregation.evidence) == 3
        assert result.aggregation.successful_sources_count == 2
        assert result.timeline.total_events == 3

    @pytest.mark.asyncio
    async def test_structural_call_budget_max_four_calls(self) -> None:
        """Physical backend calls are bounded to 4 maximum (1 SO + 3 Diag)."""
        so_service = _FakeSuperOfficeService()
        diag_service = _FakeDiagnosticsService()
        service = _build_service(so_service=so_service, diag_service=diag_service)

        selection = DiagnosticsSelectionDTO(
            include_database_health=True,
            deadlock_criteria=DeadlockCriteriaDTO(),
            slow_query_criteria=SlowQueryCriteriaDTO(),
        )
        request = InvestigationRequest(
            correlation_key="app-incident-42",
            initial_hypothesis="Complex deadlock issue",
            ticket_id=10209,
            diagnostics_selection=selection,
        )

        await service.investigate(request)

        total_backend_calls = (
            len(so_service.get_ticket_calls)
            + diag_service.health_calls
            + diag_service.slow_query_calls
            + diag_service.deadlock_calls
        )
        assert total_backend_calls == 4
        assert len(so_service.get_ticket_calls) == 1
        assert diag_service.health_calls == 1
        assert diag_service.slow_query_calls == 1
        assert diag_service.deadlock_calls == 1

    @pytest.mark.asyncio
    async def test_zero_selections_makes_zero_backend_calls(self) -> None:
        """ticket_id=None and diagnostics_selection=None -> 0 physical backend calls."""
        so_service = _FakeSuperOfficeService()
        diag_service = _FakeDiagnosticsService()
        service = _build_service(so_service=so_service, diag_service=diag_service)

        request = InvestigationRequest(
            correlation_key="generic-key",
            initial_hypothesis="Initial hypothesis without backend criteria",
            ticket_id=None,
            diagnostics_selection=None,
        )

        result = await service.investigate(request)

        total_backend_calls = (
            len(so_service.get_ticket_calls)
            + diag_service.health_calls
            + diag_service.slow_query_calls
            + diag_service.deadlock_calls
        )
        assert total_backend_calls == 0
        assert len(result.aggregation.evidence) == 0
        assert result.plan.status == InvestigationStatus.IN_PROGRESS
        assert result.plan.current_step_count == 1

    @pytest.mark.asyncio
    async def test_all_sources_non_success_produces_warn_step(self) -> None:
        """When all queried sources are non-success, step severity is WARN."""
        so_service = _FakeSuperOfficeService(raise_error=True)
        diag_service = _FakeDiagnosticsService(health_error=True)
        service = _build_service(so_service=so_service, diag_service=diag_service)

        request = InvestigationRequest(
            correlation_key="fail-key",
            initial_hypothesis="Failing investigation",
            ticket_id=10209,
            diagnostics_selection=DiagnosticsSelectionDTO(include_database_health=True),
        )

        result = await service.investigate(request)

        assert len(result.aggregation.evidence) == 0
        assert result.aggregation.all_sources_failed is True
        assert result.plan.current_step_count == 1
        step = result.plan.steps[0]
        assert step.severity == "WARN"
        assert result.timeline.total_events == 0

    @pytest.mark.asyncio
    async def test_service_level_partial_source_availability(self) -> None:
        """Diagnostics FAILED + SO SUCCESS -> valid result with SO evidence."""
        so_service = _FakeSuperOfficeService()
        diag_service = _FakeDiagnosticsService(health_error=True)
        service = _build_service(so_service=so_service, diag_service=diag_service)

        request = InvestigationRequest(
            correlation_key="partial-key",
            initial_hypothesis="Service level partial source availability",
            ticket_id=10209,
            diagnostics_selection=DiagnosticsSelectionDTO(include_database_health=True),
        )

        result = await service.investigate(request)

        # SO evidence is preserved, Diagnostics evidence is absent
        assert len(result.aggregation.evidence) == 1
        assert result.aggregation.evidence[0].source_type == EvidenceSourceType.SUPEROFFICE_CRM

        outcomes = {o.source_type: o.status for o in result.aggregation.source_outcomes}
        assert outcomes[EvidenceSourceType.SUPEROFFICE_CRM] == SourceCollectionStatus.SUCCESS
        assert outcomes[EvidenceSourceType.MSSQL_DIAGNOSTICS] == SourceCollectionStatus.FAILED
        assert outcomes[EvidenceSourceType.APPLICATION_LOGS] == SourceCollectionStatus.BLOCKED
        assert outcomes[EvidenceSourceType.KNOWLEDGE_BASE] == SourceCollectionStatus.NOT_CONFIGURED

        assert result.plan.steps[0].severity == "INFO"

    @pytest.mark.asyncio
    async def test_max_steps_propagated_to_plan(self) -> None:
        service = _build_service()
        request = InvestigationRequest(
            correlation_key="key",
            initial_hypothesis="Hypothesis",
            max_steps=7,
        )

        result = await service.investigate(request)

        assert result.plan.max_steps == 7

    @pytest.mark.asyncio
    async def test_hypothesis_evaluation_in_phase_6(self) -> None:
        """InvestigationResult contains hypothesis evaluation in Phase 6."""
        service = _build_service()
        request = InvestigationRequest(
            correlation_key="key",
            initial_hypothesis="Hypothesis",
        )

        result = await service.investigate(request)

        assert hasattr(result, "hypothesis_evaluation")

    def test_request_validation_rejects_leading_trailing_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            InvestigationRequest(
                correlation_key="  padded-key  ",
                initial_hypothesis="Valid hypothesis",
            )

        with pytest.raises(ValidationError):
            InvestigationRequest(
                correlation_key="valid-key",
                initial_hypothesis="  padded-hypothesis  ",
            )

    def test_request_validation_rejects_empty_fields(self) -> None:
        with pytest.raises(ValidationError):
            InvestigationRequest(
                correlation_key="",
                initial_hypothesis="Valid hypothesis",
            )

        with pytest.raises(ValidationError):
            InvestigationRequest(
                correlation_key="valid-key",
                initial_hypothesis="",
            )

    def test_request_validation_rejects_out_of_bounds_max_steps(self) -> None:
        with pytest.raises(ValidationError):
            InvestigationRequest(
                correlation_key="key",
                initial_hypothesis="Hypothesis",
                max_steps=0,
            )

        with pytest.raises(ValidationError):
            InvestigationRequest(
                correlation_key="key",
                initial_hypothesis="Hypothesis",
                max_steps=26,
            )

    def test_service_manual_request_validation_checks(self) -> None:
        service = _build_service()

        # Test internal _validate_request method directly
        # with mock objects having invalid attributes
        class _InvalidReq:
            correlation_key = ""
            initial_hypothesis = "hyp"

        with pytest.raises(DomainValidationError):
            service._validate_request(_InvalidReq())  # type: ignore[arg-type]

        class _InvalidReq2:
            correlation_key = "key"
            initial_hypothesis = ""

        with pytest.raises(DomainValidationError):
            service._validate_request(_InvalidReq2())  # type: ignore[arg-type]
