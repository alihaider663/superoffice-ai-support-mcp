"""Layer-4 investigation service request/result contracts.

Import policy: ONLY platform-investigation, platform-core, and diag_mcp.contracts
are permitted. No server runtime or adapter imports.
"""

from pydantic import ConfigDict, Field, field_validator

from diag_mcp.contracts.dtos import DeadlockCriteriaDTO, SlowQueryCriteriaDTO
from platform_core.models import PlatformBaseModel
from platform_investigation.models import (
    EvidenceAggregationResult,
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


class InvestigationRequest(PlatformBaseModel):
    """Typed request for a single-request investigation cycle.

    Requires opaque correlation_key and caller-supplied initial_hypothesis.
    Optional ticket_id allows explicit SuperOffice evidence collection.
    Optional diagnostics_selection controls which MSSQL diagnostics to execute.
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
    diagnostics_selection: DiagnosticsSelectionDTO | None = Field(
        default=None,
        description="Explicit opt-in selection for diagnostic operations (default: False/None)",
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
    and chronological timeline.
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
