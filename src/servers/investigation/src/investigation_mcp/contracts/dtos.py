"""Public wire contracts and DTOs for the Investigation MCP Server."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, field_validator, model_validator

from platform_core.models import PlatformBaseModel


class DeadlockInvestigationInputDTO(PlatformBaseModel):
    """Public criteria for database deadlock analysis."""

    start_time: datetime | None = Field(
        default=None,
        description="Start of observation time window with explicit offset (e.g. '...Z')",
    )
    end_time: datetime | None = Field(
        default=None,
        description="End of observation time window with explicit offset (e.g. '...Z')",
    )
    limit: int | None = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum deadlock events to return (1..50, default 10)",
    )

    @field_validator("start_time", "end_time", mode="after")
    @classmethod
    def validate_aware_and_normalize(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None:
            raise ValueError("Datetime must include an explicit timezone offset.")
        return v.astimezone(UTC)

    @model_validator(mode="after")
    def validate_time_window(self) -> "DeadlockInvestigationInputDTO":
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time > self.end_time
        ):
            raise ValueError("start_time cannot be after end_time.")
        return self


class SlowQueryInvestigationInputDTO(PlatformBaseModel):
    """Public criteria for database slow query analysis."""

    start_time: datetime | None = Field(
        default=None,
        description="Start of observation time window with explicit offset (e.g. '...Z')",
    )
    end_time: datetime | None = Field(
        default=None,
        description="End of observation time window with explicit offset (e.g. '...Z')",
    )
    min_duration_ms: int = Field(
        default=1000,
        ge=1,
        description="Minimum execution duration threshold in milliseconds (default 1000ms)",
    )
    limit: int | None = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum slow queries to return (1..50, default 10)",
    )

    @field_validator("start_time", "end_time", mode="after")
    @classmethod
    def validate_aware_and_normalize(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return None
        if v.tzinfo is None:
            raise ValueError("Datetime must include an explicit timezone offset.")
        return v.astimezone(UTC)

    @model_validator(mode="after")
    def validate_time_window(self) -> "SlowQueryInvestigationInputDTO":
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time > self.end_time
        ):
            raise ValueError("start_time cannot be after end_time.")
        return self


class InvestigationDiagnosticsInputDTO(PlatformBaseModel):
    """Public opt-in selection for database diagnostic checks."""

    include_database_health: bool = Field(
        default=False,
        description="Explicit opt-in to execute database health check",
    )
    deadlocks: DeadlockInvestigationInputDTO | None = Field(
        default=None,
        description="Explicit opt-in criteria to search recent database deadlocks",
    )
    slow_queries: SlowQueryInvestigationInputDTO | None = Field(
        default=None,
        description="Explicit opt-in criteria to search slow executing database queries",
    )
    include_ticket_diagnostic: bool = Field(
        default=False,
        description="Explicit opt-in to inspect ticket database diagnostic record (y_logticket)",
    )
    include_blocking_sessions: bool = Field(
        default=False,
        description="Explicit opt-in to inspect active blocking sessions snapshot",
    )


class InvestigationSuperOfficeInputDTO(PlatformBaseModel):
    """Public criteria for SuperOffice CRM evidence collection."""

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


class InvestigationKnowledgeInputDTO(PlatformBaseModel):
    """Public criteria for Knowledge Base search."""

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


class InvestigationLogsInputDTO(PlatformBaseModel):
    """Public criteria for Application Logs search."""

    include_logs: bool = Field(
        default=False,
        description="Explicit opt-in to search application logs",
    )
    query: str | None = Field(
        default=None,
        max_length=256,
        description="Query text for log search",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=50,
        description="Maximum log excerpts to retrieve",
    )


class InvestigateIncidentRequestDTO(PlatformBaseModel):
    """Public MCP input contract for cross-domain incident investigation."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        str_strip_whitespace=False,
    )

    initial_hypothesis: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Explicit incident hypothesis to investigate",
    )
    ticket_id: int | None = Field(
        default=None,
        ge=1,
        description="Optional SuperOffice ticket ID to collect CRM ticket context",
    )
    superoffice: InvestigationSuperOfficeInputDTO | None = Field(
        default=None,
        description="Optional SuperOffice CRM collection criteria (e.g. audit trail)",
    )
    diagnostics: InvestigationDiagnosticsInputDTO | None = Field(
        default=None,
        description="Optional database diagnostic checks to execute",
    )
    knowledge: InvestigationKnowledgeInputDTO | None = Field(
        default=None,
        description="Optional knowledge base search options",
    )
    logs: InvestigationLogsInputDTO | None = Field(
        default=None,
        description="Optional application logs search options",
    )

    @field_validator("initial_hypothesis", mode="after")
    @classmethod
    def validate_no_surrounding_whitespace(cls, v: str) -> str:
        if v != v.strip():
            raise ValueError("Field cannot contain leading or trailing whitespace.")
        return v

    @model_validator(mode="after")
    def validate_at_least_one_source_selected(self) -> "InvestigateIncidentRequestDTO":
        has_ticket = self.ticket_id is not None
        has_diag = self.diagnostics is not None and (
            self.diagnostics.include_database_health
            or self.diagnostics.deadlocks is not None
            or self.diagnostics.slow_queries is not None
            or self.diagnostics.include_ticket_diagnostic
            or self.diagnostics.include_blocking_sessions
        )
        has_kb = self.knowledge is not None and self.knowledge.include_knowledge_search
        has_logs = self.logs is not None and self.logs.include_logs
        if not (has_ticket or has_diag or has_kb or has_logs):
            raise ValueError(
                "At least one investigation target or diagnostic check must be specified: "
                "provide 'ticket_id' and/or configure 'diagnostics', 'knowledge', or 'logs'."
            )
        return self


# ============================================================================
# Public Observation DTOs (Discriminated Union on observation_type)
# ============================================================================


class TicketObservationDTO(PlatformBaseModel):
    """SuperOffice CRM ticket observation."""

    observation_type: Literal["ticket"] = "ticket"
    ticket_id: int = Field(..., description="SuperOffice ticket identifier")
    title: str | None = Field(default=None, description="Sanitized ticket subject or title")
    status: str = Field(..., description="Ticket status")
    category: str = Field(..., description="Ticket category")
    priority: str = Field(..., description="Ticket priority level")
    sanitized_description: str | None = Field(
        default=None,
        description="Sanitized ticket problem description or symptom text",
    )
    sanitized_customer_reference: str | None = Field(
        default=None,
        description="Sanitized customer reference identifier",
    )


class TicketAuditObservationDTO(PlatformBaseModel):
    """SuperOffice CRM ticket audit trail action observation."""

    observation_type: Literal["ticket_audit"] = "ticket_audit"
    action_id: int = Field(..., description="Unique action identifier")
    ticket_id: int = Field(..., description="SuperOffice ticket identifier")
    action_code: int | None = Field(default=None, description="SuperOffice action code")
    action_name: str = Field(..., description="Descriptive action title")
    description: str = Field(default="", description="Action description")
    actor: str | None = Field(
        default=None,
        description="Actor login name or user ID representation",
    )
    field_changes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Granular field mutations associated with this action",
    )


class DatabaseHealthObservationDTO(PlatformBaseModel):
    """MSSQL database cluster health observation."""

    observation_type: Literal["database_health"] = "database_health"
    is_healthy: bool = Field(..., description="Whether database is responsive and healthy")
    active_connections: int = Field(..., description="Current active connection count")
    latency_ms: float = Field(..., description="Database probe latency in milliseconds")


class DeadlockObservationDTO(PlatformBaseModel):
    """MSSQL database deadlock observation."""

    observation_type: Literal["deadlock"] = "deadlock"
    deadlock_id: str = Field(..., description="Deterministic deadlock event identifier")
    victim_session_id: int = Field(..., description="Session ID chosen as deadlock victim")
    participating_session_count: int = Field(
        ..., description="Number of sessions participating in deadlock"
    )


class SlowQueryObservationDTO(PlatformBaseModel):
    """MSSQL slow-running query observation."""

    observation_type: Literal["slow_query"] = "slow_query"
    query_hash: str = Field(..., description="Stable query plan hash identifier")
    duration_ms: int = Field(..., description="Total execution duration in milliseconds")
    cpu_time_ms: int = Field(..., description="CPU processing time in milliseconds")
    logical_reads: int = Field(..., description="Number of logical page reads")
    execution_count: int = Field(..., description="Number of executions recorded")


class TicketDiagnosticObservationDTO(PlatformBaseModel):
    """MSSQL ticket database diagnostic activity observation."""

    observation_type: Literal["ticket_diagnostic"] = "ticket_diagnostic"
    ticket_id: int = Field(..., description="SuperOffice ticket identifier")
    has_db_activity: bool = Field(..., description="Whether ticket has DB diagnostic activity")
    recent_error_count: int = Field(..., description="Count of recent errors matching ticket")
    last_activity_time: datetime | None = Field(
        default=None, description="Timestamp of latest DB activity"
    )
    diagnostic_summary: str = Field(..., description="Database diagnostic summary")


class BlockingSessionObservationDTO(PlatformBaseModel):
    """MSSQL active blocking session observation."""

    observation_type: Literal["blocking_session"] = "blocking_session"
    blocking_session_id: int = Field(..., description="Head blocking session ID")
    blocked_session_id: int = Field(..., description="Blocked session ID")
    wait_duration_ms: int = Field(..., description="Wait duration in milliseconds")
    wait_type: str = Field(default="", description="MSSQL wait resource/type")


class LogExcerptObservationDTO(PlatformBaseModel):
    """Sanitized application or API log excerpt observation."""

    observation_type: Literal["log_excerpt"] = "log_excerpt"
    excerpt_id: str = Field(..., description="Unique log excerpt identifier")
    service_name: str = Field(..., description="Originating service name")
    severity: str = Field(..., description="Log severity")
    sanitized_message: str = Field(..., description="Sanitized log message")
    correlation_id: str | None = Field(default=None, description="Request correlation identifier")


class KnownIssueObservationDTO(PlatformBaseModel):
    """Knowledge base verified known issue observation."""

    observation_type: Literal["known_issue"] = "known_issue"
    issue_id: str = Field(..., description="Known issue identifier")
    title: str = Field(..., description="Known issue summary title")
    symptom_summary: str = Field(..., description="Observable symptoms")
    root_cause_summary: str = Field(..., description="Root cause explanation")
    workaround: str | None = Field(default=None, description="Recommended workaround")
    permanent_fix_reference: str | None = Field(
        default=None, description="Fix reference or hotfix ID"
    )
    affected_products: list[str] = Field(default_factory=list, description="Affected products")


class KnowledgeArticleObservationDTO(PlatformBaseModel):
    """Knowledge base article or runbook documentation observation."""

    observation_type: Literal["knowledge_article"] = "knowledge_article"
    document_id: str = Field(..., description="Document identifier")
    title: str = Field(..., description="Article title")
    content_excerpt: str = Field(..., description="Excerpt content")
    category: str = Field(..., description="Article category")
    relevance_score: float = Field(..., description="Relevance score")
    source_reference: str = Field(..., description="Source reference")


DiagnosticObservationUnion = Annotated[
    TicketObservationDTO
    | TicketAuditObservationDTO
    | DatabaseHealthObservationDTO
    | DeadlockObservationDTO
    | SlowQueryObservationDTO
    | TicketDiagnosticObservationDTO
    | BlockingSessionObservationDTO
    | LogExcerptObservationDTO
    | KnownIssueObservationDTO
    | KnowledgeArticleObservationDTO,
    Field(discriminator="observation_type"),
]

PublicEvidenceSource = Literal[
    "superoffice_crm",
    "mssql_diagnostics",
    "application_logs",
    "knowledge_base",
]


class DiagnosticEvidenceWireDTO(PlatformBaseModel):
    """Public representation of an observed diagnostic finding."""

    source: PublicEvidenceSource = Field(..., description="Originating domain source")
    timestamp: datetime = Field(..., description="Observation timestamp in UTC (ISO 8601)")
    data: DiagnosticObservationUnion = Field(
        ..., description="Structured observation payload conforming to observation_type"
    )


# ============================================================================
# Public Source Outcome & Response DTOs
# ============================================================================

PublicSourceType = Literal[
    "superoffice_crm",
    "mssql_diagnostics",
    "application_logs",
    "knowledge_base",
]

PublicSourceStatus = Literal[
    "SUCCESS",
    "NOT_CONFIGURED",
    "BLOCKED",
    "UNAVAILABLE",
    "FAILED",
]

PublicSourceErrorCode = Literal[
    "DIAGNOSTIC_LOGS_BLOCKED",
    "KNOWLEDGE_BASE_NOT_CONFIGURED",
    "SUPEROFFICE_UNAVAILABLE",
    "SUPEROFFICE_RETRIEVAL_FAILED",
    "DIAGNOSTICS_UNAVAILABLE",
    "DIAGNOSTICS_RETRIEVAL_FAILED",
    "SOURCE_EXECUTION_FAILED",
]


class InvestigationSourceOutcomeWireDTO(PlatformBaseModel):
    """Sanitized diagnostic source status report."""

    source: PublicSourceType = Field(..., description="Domain source identifier")
    status: PublicSourceStatus = Field(
        ..., description="Collection status across the domain source"
    )
    error_code: PublicSourceErrorCode | None = Field(
        default=None,
        description="Standardized error code if collection was not successful",
    )
    error_message: str | None = Field(
        default=None,
        description="Safe, sanitized explanation if collection was not successful",
    )

    @model_validator(mode="after")
    def validate_outcome_consistency(self) -> "InvestigationSourceOutcomeWireDTO":
        if self.status == "SUCCESS":
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("error_code and error_message must be None when status is SUCCESS")
        elif self.error_code is None or self.error_message is None:
            raise ValueError("error_code and error_message are required when status is not SUCCESS")
        return self


class HypothesisEvaluationWireDTO(PlatformBaseModel):
    """Grounded evaluation outcome for an incident hypothesis."""

    hypothesis_id: str = Field(..., description="Target hypothesis identifier")
    outcome: Literal["SUPPORTED", "REFUTED", "INCONCLUSIVE", "UNEVALUATED"] = Field(
        ..., description="Deterministic evaluation outcome"
    )


class InvestigateIncidentResponseDTO(PlatformBaseModel):
    """Immutable public wire contract for incident investigation results."""

    source_outcomes: tuple[InvestigationSourceOutcomeWireDTO, ...] = Field(
        ...,
        description="Diagnostic coverage and collection status across each domain source",
    )
    evidence: tuple[DiagnosticEvidenceWireDTO, ...] = Field(
        default=(),
        description="Chronologically ordered diagnostic evidence items observed across sources",
    )
    hypothesis_evaluation: HypothesisEvaluationWireDTO | None = Field(
        default=None,
        description="Deterministic evaluation outcome of the incident hypothesis",
    )
