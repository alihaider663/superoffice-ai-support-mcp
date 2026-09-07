"""Domain models for investigation state machine, evidence, and hypotheses."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import ConfigDict, Field, field_validator, model_validator

from platform_core.models import PlatformBaseModel, UtcTimestamp


class EvidenceSourceType(StrEnum):
    """Origin of a collected evidence artifact."""

    MSSQL_DIAGNOSTICS = "mssql_diagnostics"
    APPLICATION_LOGS = "application_logs"
    SUPEROFFICE_CRM = "superoffice_crm"
    KNOWLEDGE_BASE = "knowledge_base"
    INFRASTRUCTURE_PROBE = "infrastructure_probe"


class InvestigationStatus(StrEnum):
    """Lifecycle status of a diagnostic investigation."""

    INITIALIZED = "initialized"
    IN_PROGRESS = "in_progress"
    CONCLUDED = "concluded"
    ABORTED = "aborted"
    STEP_LIMIT_EXCEEDED = "step_limit_exceeded"


class HypothesisStatus(StrEnum):
    """Validation state of an investigation hypothesis."""

    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    DISPROVEN = "disproven"
    INCONCLUSIVE = "inconclusive"


class HypothesisEvaluationOutcome(StrEnum):
    """Deterministic outcome of evaluating a hypothesis against explicit evidence."""

    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    UNEVALUATED = "unevaluated"


class SourceCollectionStatus(StrEnum):
    """Execution status of an individual evidence source collector."""

    SUCCESS = "success"
    BLOCKED = "blocked"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class CorrelationReference(PlatformBaseModel):
    """Explicit, typed correlation identifier attached to evidence or diagnostic artifacts."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        str_strip_whitespace=False,
    )

    namespace: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Correlation domain namespace (e.g. ticket, trace, spid, session)",
    )
    value: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Explicit correlation identifier value",
    )

    @field_validator("namespace", "value", mode="after")
    @classmethod
    def _validate_no_whitespace(cls, v: str) -> str:
        if v != v.strip():
            msg = "CorrelationReference fields cannot contain leading or trailing whitespace."
            raise ValueError(msg)
        return v


class DiagnosticEvidence(PlatformBaseModel):
    """Atomic diagnostic evidence artifact collected during an investigation."""

    evidence_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique evidence identifier",
    )
    source_type: EvidenceSourceType = Field(..., description="System origin of evidence")
    title: str = Field(..., description="Short summary description")
    timestamp: UtcTimestamp = Field(default_factory=lambda: datetime.now(UTC))
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence rating (0.0 to 1.0)",
    )
    data: dict[str, Any] = Field(default_factory=dict, description="Structured evidence payload")
    tags: tuple[str, ...] = Field(default=(), description="Diagnostic classification tags")
    correlation_references: tuple[CorrelationReference, ...] = Field(
        default=(),
        description="Explicit typed correlation identifiers attached to this observation",
    )

    @field_validator("correlation_references", mode="after")
    @classmethod
    def _validate_unique_correlation_references(
        cls,
        refs: tuple[CorrelationReference, ...],
    ) -> tuple[CorrelationReference, ...]:
        seen: set[tuple[str, str]] = set()
        for ref in refs:
            key = (ref.namespace, ref.value)
            if key in seen:
                msg = "DiagnosticEvidence contains a duplicate correlation reference."
                raise ValueError(msg)
            seen.add(key)
        return refs


class Hypothesis(PlatformBaseModel):
    """Working hypothesis regarding root cause."""

    hypothesis_id: str = Field(default_factory=lambda: str(uuid4()))
    description: str
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    supporting_evidence_ids: tuple[str, ...] = Field(default=())
    refuting_evidence_ids: tuple[str, ...] = Field(default=())
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class HypothesisEvaluationResult(PlatformBaseModel):
    """Immutable deterministic evaluation result for a hypothesis."""

    hypothesis_id: str = Field(..., min_length=1, description="Target hypothesis identifier")
    outcome: HypothesisEvaluationOutcome = Field(
        ...,
        description="Evaluated support/refutation outcome",
    )


class InvestigationStep(PlatformBaseModel):
    """Single diagnostic execution step in an investigation."""

    step_number: int = Field(..., ge=1)
    action_taken: str
    summary: str
    severity: str = "INFO"
    correlation_keys: tuple[str, ...] = Field(
        default=(),
        description="Linked keys (e.g. ticket:10209, req:xyz)",
    )
    collected_evidence_ids: tuple[str, ...] = Field(default=())
    timestamp: UtcTimestamp = Field(default_factory=lambda: datetime.now(UTC))


class InvestigationPlan(PlatformBaseModel):
    """Structured container tracking the lifecycle of an investigation."""

    investigation_id: str = Field(default_factory=lambda: str(uuid4()))
    status: InvestigationStatus = InvestigationStatus.INITIALIZED
    max_steps: int = Field(default=10, ge=1, le=25)
    current_step_count: int = Field(default=0, ge=0)
    steps: tuple[InvestigationStep, ...] = Field(default=())
    hypotheses: tuple[Hypothesis, ...] = Field(default=())
    concluded_root_cause: str | None = None
    created_at: UtcTimestamp = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: UtcTimestamp = Field(default_factory=lambda: datetime.now(UTC))


class LogInvestigationResult(PlatformBaseModel):
    """Summary of log analysis across a time window or incident."""

    total_matched_entries: int = Field(default=0, ge=0)
    error_summary: list[str] = Field(default_factory=list)
    top_exception_types: dict[str, int] = Field(default_factory=dict)
    sample_evidence: tuple[DiagnosticEvidence, ...] = Field(default=())


class SourceCollectionResult(PlatformBaseModel):
    """Typed outcome of evidence collection from a single source."""

    source_type: EvidenceSourceType = Field(..., description="Target source system")
    status: SourceCollectionStatus = Field(..., description="Collection execution status")
    evidence: tuple[DiagnosticEvidence, ...] = Field(
        default=(),
        description="Actual sourced observations (empty on failure/block)",
    )
    error_code: str | None = Field(default=None, description="Normalized safe error code")
    error_message: str | None = Field(default=None, description="Sanitized safe error summary")
    collected_at: UtcTimestamp = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _validate_invariants(self) -> "SourceCollectionResult":
        if self.status == SourceCollectionStatus.SUCCESS:
            if self.error_code is not None:
                msg = "SourceCollectionResult with status 'success' cannot contain an error_code."
                raise ValueError(msg)
            if self.error_message is not None:
                msg = (
                    "SourceCollectionResult with status 'success' cannot contain an error_message."
                )
                raise ValueError(msg)
        else:
            # Non-SUCCESS statuses: BLOCKED, NOT_CONFIGURED, UNAVAILABLE, FAILED
            if len(self.evidence) > 0:
                msg = (
                    f"SourceCollectionResult with status '{self.status.value}' "
                    "cannot contain evidence items."
                )
                raise ValueError(msg)
            if not self.error_code or not self.error_code.strip():
                msg = (
                    f"SourceCollectionResult with status '{self.status.value}' "
                    "must contain a normalized error_code."
                )
                raise ValueError(msg)

        for item in self.evidence:
            if item.source_type != self.source_type:
                msg = (
                    f"Evidence item '{item.evidence_id}' has source_type "
                    f"'{item.source_type.value}' which does not match result "
                    f"source_type '{self.source_type.value}'."
                )
                raise ValueError(msg)
        return self


class EvidenceAggregationResult(PlatformBaseModel):
    """Aggregate result from multi-source evidence collection."""

    investigation_id: str = Field(..., description="Target investigation identifier")
    correlation_key: str = Field(..., description="Correlation key used for collection")
    source_outcomes: tuple[SourceCollectionResult, ...] = Field(
        default=(),
        description="Per-source execution breakdown",
    )
    collected_at: UtcTimestamp = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_sources(self) -> int:
        """Total number of sources queried in this aggregation pass."""
        return len(self.source_outcomes)

    @property
    def successful_sources_count(self) -> int:
        """Number of sources that executed with status SUCCESS."""
        return sum(1 for s in self.source_outcomes if s.status == SourceCollectionStatus.SUCCESS)

    @property
    def has_failures(self) -> bool:
        """True if at least one queried source executed with a non-SUCCESS status."""
        return any(s.status != SourceCollectionStatus.SUCCESS for s in self.source_outcomes)

    @property
    def has_partial_failures(self) -> bool:
        """True if partial availability: at least one SUCCESS and at least one non-SUCCESS."""
        has_succ = any(s.status == SourceCollectionStatus.SUCCESS for s in self.source_outcomes)
        has_fail = any(s.status != SourceCollectionStatus.SUCCESS for s in self.source_outcomes)
        return has_succ and has_fail

    @property
    def all_sources_failed(self) -> bool:
        """True if there is at least one source queried and zero sources succeeded."""
        return len(self.source_outcomes) > 0 and self.successful_sources_count == 0

    @property
    def evidence(self) -> tuple[DiagnosticEvidence, ...]:
        """Authoritative flattened view of all evidence items in deterministic order."""
        return tuple(item for outcome in self.source_outcomes for item in outcome.evidence)


class TimelineEvent(PlatformBaseModel):
    """Chronological event projection over a collected diagnostic observation."""

    evidence_id: str = Field(
        ...,
        description="Traceable link and identity of original DiagnosticEvidence",
    )
    source_type: EvidenceSourceType = Field(..., description="System origin of evidence")
    timestamp: UtcTimestamp = Field(..., description="UTC observation timestamp")
    title: str = Field(..., description="Summary title of the observation")
    correlation_references: tuple[CorrelationReference, ...] = Field(
        default=(),
        description="Explicit correlation references attached to the observation",
    )
    tags: tuple[str, ...] = Field(default=(), description="Classification tags")


class CorrelationGroup(PlatformBaseModel):
    """Explicit grouping of evidence items sharing an identical correlation reference."""

    correlation_reference: CorrelationReference = Field(
        ...,
        description="Target correlation reference",
    )
    evidence_ids: tuple[str, ...] = Field(
        ...,
        min_length=2,
        description="Evidence identifiers sharing this reference in order (size >= 2)",
    )

    @field_validator("evidence_ids", mode="after")
    @classmethod
    def _validate_distinct_evidence_ids(cls, ids: tuple[str, ...]) -> tuple[str, ...]:
        if len(ids) != len(set(ids)):
            msg = "CorrelationGroup cannot contain duplicate evidence IDs."
            raise ValueError(msg)
        return ids

    @property
    def total_evidence(self) -> int:
        """Total number of correlated evidence items in this group."""
        return len(self.evidence_ids)


class InvestigationTimeline(PlatformBaseModel):
    """Deterministic chronological timeline and explicit correlation groups."""

    investigation_id: str = Field(..., description="Target investigation identifier")
    events: tuple[TimelineEvent, ...] = Field(
        default=(),
        description="Chronologically sorted events (timestamp ASC, stable aggregate order on tie)",
    )
    correlation_groups: tuple[CorrelationGroup, ...] = Field(
        default=(),
        description="Explicit correlation groups for references shared by >= 2 evidence items",
    )

    @property
    def total_events(self) -> int:
        """Total number of chronological events on the timeline."""
        return len(self.events)

    @property
    def total_groups(self) -> int:
        """Total number of multi-member correlation groups."""
        return len(self.correlation_groups)
