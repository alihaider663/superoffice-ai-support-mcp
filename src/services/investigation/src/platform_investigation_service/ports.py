"""Port protocols for Layer-4 investigation service backend dependencies.

These protocols define the contract-only surface that the Layer-4 orchestration
service and concrete collectors depend on. They are satisfied by domain
Application Services from the server packages (so_mcp, diag_mcp, kb_mcp) and the Layer-3
investigation engine (InvestigationOrchestratorEngine) via structural subtyping.

Import policy: ONLY platform-investigation, platform-core, so_mcp.contracts.*,
diag_mcp.contracts.*, and kb_mcp.contracts.* DTO/criteria contracts are permitted.
NO server runtime, adapter, or infrastructure imports are allowed.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

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
from platform_investigation.models import (
    Hypothesis,
    InvestigationPlan,
)
from so_mcp.audit.contracts import TicketAuditTrailDTO
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
    """Narrow contract for SuperOffice CRM ticket and audit retrieval.

    Satisfied by SuperOfficeApplicationService and TicketAuditService from so_mcp.
    """

    async def get_ticket(
        self,
        ticket_id: int,
    ) -> MinimizedTicketDetailDTO:
        """Retrieve sanitized ticket detail with purpose-based field selection."""
        ...

    async def get_ticket_audit_trail(
        self,
        ticket_id: int,
        include_field_changes: bool = True,
        limit: int = 50,
    ) -> TicketAuditTrailDTO:
        """Retrieve chronological ticket audit trail and field mutation history."""
        ...


@runtime_checkable
class DiagnosticsServicePort(Protocol):
    """Narrow contract for MSSQL database diagnostics.

    Satisfied by DiagnosticsApplicationService from diag_mcp.
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

    async def get_ticket_diagnostic_record(
        self,
        ticket_id: int,
    ) -> TicketDiagnosticRecordDomainDTO | None:
        """Fetch database-level diagnostic record for a ticket."""
        ...

    async def find_blocking_sessions(
        self,
        criteria: BlockingSessionCriteriaDTO | None = None,
    ) -> BoundedDiagnosticResultDTO[BlockingSessionDomainDTO]:
        """Fetch active blocking session snapshot."""
        ...

    async def search_logs(
        self,
        query: str,
        limit: int = 20,
    ) -> BoundedDiagnosticResultDTO[SanitizedLogExcerptDTO]:
        """Search sanitized application and API logs."""
        ...


@runtime_checkable
class LogsServicePort(Protocol):
    """Narrow contract for application and API log retrieval."""

    async def search_logs(
        self,
        query: str,
        limit: int = 20,
    ) -> BoundedDiagnosticResultDTO[SanitizedLogExcerptDTO]:
        """Search sanitized application log entries."""
        ...


@runtime_checkable
class KnowledgeServicePort(Protocol):
    """Narrow contract for Knowledge Base search and runbook retrieval.

    Satisfied by KnowledgeApplicationService from kb_mcp.
    """

    async def search_knowledge(
        self,
        criteria: KnowledgeSearchCriteriaDTO,
    ) -> Sequence[KnowledgeSearchResultDomainDTO]:
        """Semantic search for knowledge articles and runbook excerpts."""
        ...

    async def find_known_issues(
        self,
        criteria: KnownIssueSearchCriteriaDTO,
    ) -> Sequence[KnownIssueDomainDTO]:
        """Find matching known issues and verified workarounds."""
        ...

    async def get_runbook(
        self,
        runbook_id: str,
    ) -> RunbookDetailDomainDTO | None:
        """Retrieve operational runbook details by ID."""
        ...
