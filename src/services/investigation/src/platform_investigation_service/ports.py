"""Port protocols for Layer-4 investigation service backend dependencies.

These protocols define the contract-only surface that the Layer-4 orchestration
service and concrete collectors depend on. They are satisfied by domain
Application Services from the server packages (so_mcp, diag_mcp) and the Layer-3
investigation engine (InvestigationOrchestratorEngine) via structural subtyping.

Import policy: ONLY platform-investigation, platform-core, so_mcp.contracts.*,
and diag_mcp.contracts.* DTO/criteria contracts are permitted.
NO server runtime, adapter, or infrastructure imports are allowed.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from diag_mcp.contracts.dtos import (
    BoundedDiagnosticResultDTO,
    DatabaseHealthDomainDTO,
    DeadlockCriteriaDTO,
    DeadlockDomainDTO,
    SlowQueryCriteriaDTO,
    SlowQueryDomainDTO,
)
from platform_investigation.models import (
    Hypothesis,
    InvestigationPlan,
)
from so_mcp.contracts.dtos import MinimizedTicketDetailDTO


@runtime_checkable
class InvestigationOrchestratorPort(Protocol):
    """Contract for managing bounded investigation state machines.

    Satisfied by InvestigationOrchestratorEngine from platform-investigation.
    """

    async def create_plan(
        self,
        initial_hypothesis: str,
        max_steps: int | None = None,
    ) -> InvestigationPlan:
        """Create and initialize a new step-bounded diagnostic investigation plan."""
        ...

    async def advance_step(
        self,
        plan_id: str,
        hypothesis: Hypothesis | None = None,
        *,
        action_taken: str = "Diagnostic step executed",
        summary: str = "Investigation step advanced",
        severity: str = "INFO",
        correlation_keys: Sequence[str] = (),
        collected_evidence_ids: Sequence[str] = (),
    ) -> InvestigationPlan:
        """Advance the diagnostic state machine, appending a step and validating bounds."""
        ...


@runtime_checkable
class SuperOfficeServicePort(Protocol):
    """Narrow contract for SuperOffice CRM ticket retrieval.

    Satisfied by SuperOfficeApplicationService from so_mcp.
    Only the get_ticket operation is consumed during investigation collection.
    """

    async def get_ticket(
        self,
        ticket_id: int,
    ) -> MinimizedTicketDetailDTO:
        """Retrieve sanitized ticket detail with purpose-based field selection."""
        ...


@runtime_checkable
class DiagnosticsServicePort(Protocol):
    """Narrow contract for MSSQL database diagnostics.

    Satisfied by DiagnosticsApplicationService from diag_mcp.
    Only baseline selected read-only operations are included.
    """

    async def get_database_health(self) -> DatabaseHealthDomainDTO:
        """Fetch sanitized database health status."""
        ...

    async def find_deadlocks(
        self,
        criteria: DeadlockCriteriaDTO,
    ) -> BoundedDiagnosticResultDTO[DeadlockDomainDTO]:
        """Find recent deadlock events with sanitized summaries."""
        ...

    async def find_slow_queries(
        self,
        criteria: SlowQueryCriteriaDTO,
    ) -> BoundedDiagnosticResultDTO[SlowQueryDomainDTO]:
        """Find slow queries with bounded results and sanitized summary text."""
        ...
