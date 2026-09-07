"""Composition tests verifying InvestigationApplicationService with MCP adapters."""

from unittest.mock import AsyncMock

import pytest

from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    DatabaseHealthDomainDTO,
    DeadlockCriteriaDTO,
    DeadlockDomainDTO,
    SlowQueryDomainDTO,
)
from investigation_mcp.adapters.diagnostics_mcp_adapter import DiagnosticsMcpClientAdapter
from investigation_mcp.adapters.superoffice_mcp_adapter import SuperOfficeMcpClientAdapter
from platform_investigation import IncidentCorrelationEngine, InvestigationOrchestratorEngine
from platform_investigation.models import SourceCollectionStatus
from platform_investigation.store import InMemoryInvestigationStore
from platform_investigation_service.models import DiagnosticsSelectionDTO, InvestigationRequest
from platform_investigation_service.service import InvestigationApplicationService
from so_mcp.contracts.dtos import MinimizedTicketDetailDTO


@pytest.mark.unit
async def test_full_investigation_flow_with_mcp_adapters():
    """Test investigation execution with real Layer-3 engines and MCP adapters."""
    # 1. Setup mock SuperOffice MCP response
    so_payload = {
        "ticket_id": 501,
        "title": "Database timeout incident",
        "status": "Open",
        "category": "Database",
        "priority": "Critical",
        "sanitized_description": "Deadlocks observed during checkout processing",
        "created_at": "2026-09-01T10:00:00Z",
    }
    mock_so_adapter = AsyncMock(spec=SuperOfficeMcpClientAdapter)
    mock_so_adapter.get_ticket = AsyncMock(
        return_value=MinimizedTicketDetailDTO.model_validate(so_payload)
    )

    # 2. Setup mock Diagnostics MCP response
    health_payload = {
        "is_healthy": True,
        "status_summary": "ONLINE",
        "active_connections": 15,
        "latency_ms": 2.0,
        "collected_at": "2026-09-01T10:00:00Z",
    }
    deadlock_payload = {
        "items": [
            {
                "deadlock_id": "dl-501",
                "occurred_at": "2026-09-01T10:00:00Z",
                "victim_session_id": 42,
                "participating_session_count": 2,
                "resource_description": "Page Lock",
                "summary": "Deadlock in ticket updates",
            }
        ],
        "returned_count": 1,
        "total_matched": 1,
        "is_truncated": False,
    }
    mock_diag_adapter = AsyncMock(spec=DiagnosticsMcpClientAdapter)
    mock_diag_adapter.get_database_health = AsyncMock(
        return_value=DatabaseHealthDomainDTO.model_validate(health_payload)
    )
    mock_diag_adapter.find_deadlocks = AsyncMock(
        return_value=BoundedDiagnosticResultDTO[DeadlockDomainDTO].model_validate(deadlock_payload)
    )
    mock_diag_adapter.find_slow_queries = AsyncMock(
        return_value=BoundedDiagnosticResultDTO[SlowQueryDomainDTO].model_validate(
            {"items": [], "returned_count": 0, "is_truncated": False}
        )
    )

    # 3. Instantiate real Layer-3 engines and Layer-4 service
    store = InMemoryInvestigationStore()
    orchestrator = InvestigationOrchestratorEngine(store=store)
    correlator = IncidentCorrelationEngine()

    service = InvestigationApplicationService(
        orchestrator=orchestrator,
        superoffice_service=mock_so_adapter,
        diagnostics_service=mock_diag_adapter,
        correlator=correlator,
    )

    # 4. Execute single-request investigation
    request = InvestigationRequest(
        correlation_key="inv-test-composite",
        initial_hypothesis="Deadlock causing ticket timeouts",
        ticket_id=501,
        diagnostics_selection=DiagnosticsSelectionDTO(
            include_database_health=True,
            deadlock_criteria=DeadlockCriteriaDTO(limit=5),
        ),
    )

    result = await service.investigate(request)

    # 5. Verify results
    assert result.investigation_id is not None
    assert result.plan.hypotheses[0].description == "Deadlock causing ticket timeouts"
    assert len(result.plan.steps) == 1
    assert result.plan.steps[0].step_number == 1
    assert result.aggregation is not None

    # Check SuperOffice outcome
    so_outcome = next(
        (o for o in result.aggregation.source_outcomes if o.source_type == "superoffice_crm"), None
    )
    assert so_outcome is not None
    assert so_outcome.status == SourceCollectionStatus.SUCCESS
    assert len(so_outcome.evidence) == 1

    # Check Diagnostics outcome
    diag_outcome = next(
        (o for o in result.aggregation.source_outcomes if o.source_type == "mssql_diagnostics"),
        None,
    )
    assert diag_outcome is not None
    assert diag_outcome.status == SourceCollectionStatus.SUCCESS
    assert len(diag_outcome.evidence) == 2  # Health + Deadlock

    # Verify timeline correlation
    assert result.timeline is not None
    assert len(result.timeline.events) >= 3
