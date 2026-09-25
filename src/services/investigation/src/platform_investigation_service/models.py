"""Layer-4 investigation service request/result contracts.

Import policy: ONLY platform-investigation, platform-core, diag_mcp.contracts,
and kb_mcp.contracts are permitted. No server runtime or adapter imports.
"""

from pydantic import ConfigDict, Field, field_validator

from diag_mcp.contracts.dtos import DeadlockCriteriaDTO, SlowQueryCriteriaDTO
from platform_core.models import PlatformBaseModel
from platform_investigation.models import (
    EvidenceAggregationResult,
    HypothesisEvaluationResult,
    InvestigationPlan,
    InvestigationTimeline,
)


class DiagnosticsSelectionDTO(PlatformBaseModel):
    """Explicit opt-in selection for which diagnostic operations to execute.

    Mandatory semantics:
    - diagnostics_selection=None or DiagnosticsSelectionDTO() -> 0 diagnostics calls
    - include_database_health=True -> exactly 1 get_database_health call
    - deadlock_criteria supplied -> exactly 1 find_deadlocks call
    - slow_query_criteria supplied -> exactly 1 find_slow_queries call
    - include_ticket_diagnostic=True -> exactly 1 get_ticket_diagnostic_record call
    - include_blocking_sessions=True -> exactly 1 find_blocking_sessions call
    """

    include_database_health: bool = Field(
        default=False,
        description="Explicit opt-in to execute database health check",
    )
    deadlock_criteria: DeadlockCriteriaDTO | None = Field(
        default=None,
        description="Explicit criteria to execute deadlock search",
    )
    slow_query_criteria: SlowQueryCriteriaDTO | None = Field(
        default=None,
        description="Explicit criteria to execute slow query search",
    )
    include_ticket_diagnostic: bool = Field(
        default=False,
        description="Explicit opt-in to inspect ticket database diagnostic record (y_logticket)",
    )
    include_blocking_sessions: bool = Field(
        default=False,
        description="Explicit opt-in to inspect active blocking sessions snapshot",
    )


class SuperOfficeSelectionDTO(PlatformBaseModel):
    """Explicit options for SuperOffice CRM evidence collection."""

    include_audit_trail: bool = Field(
        default=False,
        description="Explicit opt-in to retrieve ticket change history and audit trail",
    )
    audit_trail_limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum audit trail events to retrieve",
    )


class KnowledgeSelectionDTO(PlatformBaseModel):
    """Explicit options for Knowledge Base evidence collection."""

    include_knowledge_search: bool = Field(
        default=True,
        description="Whether to search knowledge base for matching known issues and runbooks",
    )
    query_override: str | None = Field(
        default=None,
        max_length=256,
        description="Optional custom query for knowledge search (defaults to hypothesis/ticket)",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum knowledge items to retrieve",
    )


class LogsSelectionDTO(PlatformBaseModel):
    """Explicit options for Application Logs evidence collection."""

    include_logs: bool = Field(
        default=False,
        description="Explicit opt-in to search application logs",
    )
    query: str | None = Field(
        default=None,
        max_length=256,
        description="Query text for log search (defaults to ticket ID or correlation key)",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Maximum log excerpts to retrieve",
    )


class InvestigationRequest(PlatformBaseModel):
    """Typed request for a single-request investigation cycle.

    Requires opaque correlation_key and caller-supplied initial_hypothesis.
    Optional ticket_id allows explicit SuperOffice evidence collection.
    Optional selections control cross-domain diagnostic operations.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        str_strip_whitespace=False,
    )

    correlation_key: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Primary opaque correlation key for evidence aggregation",
    )
    initial_hypothesis: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Caller-supplied initial hypothesis description (REQUIRED)",
    )
    ticket_id: int | None = Field(
        default=None,
        ge=1,
        description="Optional explicit ticket ID for SuperOffice evidence collection",
    )
    so_selection: SuperOfficeSelectionDTO | None = Field(
        default=None,
        description="Explicit options for SuperOffice CRM collection",
    )
    diagnostics_selection: DiagnosticsSelectionDTO | None = Field(
        default=None,
        description="Explicit opt-in selection for diagnostic operations (default: False/None)",
    )
    knowledge_selection: KnowledgeSelectionDTO | None = Field(
        default=None,
        description="Explicit options for Knowledge Base collection",
    )
    logs_selection: LogsSelectionDTO | None = Field(
        default=None,
        description="Explicit options for Application Logs collection",
    )
    max_steps: int | None = Field(
        default=None,
        ge=1,
        le=25,
        description="Optional step budget for the investigation plan (1..25)",
    )

    @field_validator("correlation_key", "initial_hypothesis", mode="after")
    @classmethod
    def _validate_no_surrounding_whitespace(cls, v: str) -> str:
        if v != v.strip():
            msg = "Field cannot contain leading or trailing whitespace."
            raise ValueError(msg)
        return v


class InvestigationResult(PlatformBaseModel):
    """Immutable composite result from a single-request investigation cycle.

    Contains the unique investigation_id, authoritative plan, aggregated evidence,
    chronological timeline, and optional hypothesis evaluation.
    """

    investigation_id: str = Field(
        ...,
        description="Unique identifier of the investigation cycle",
    )
    plan: InvestigationPlan = Field(
        ...,
        description="Authoritative investigation plan with lifecycle state",
    )
    aggregation: EvidenceAggregationResult = Field(
        ...,
        description="Authoritative aggregated multi-source evidence collection result",
    )
    timeline: InvestigationTimeline = Field(
        ...,
        description="Deterministic chronological timeline and correlation groups",
    )
    hypothesis_evaluation: HypothesisEvaluationResult | None = Field(
        default=None,
        description="Deterministic hypothesis evaluation outcome against collected evidence",
    )
