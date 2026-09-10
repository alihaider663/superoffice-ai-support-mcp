"""Data transfer objects and bounded result envelopes for Diagnostics and Log boundaries."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, model_validator

from platform_core.models import PlatformBaseModel

# ============================================================================
# 1. Bounded Diagnostic Result Envelope (Localized to Diagnostics)
# ============================================================================


class BoundedDiagnosticResultDTO[T: PlatformBaseModel](PlatformBaseModel):
    """Generic bounded result envelope for diagnostic and log query results."""

    items: tuple[T, ...] = Field(default=(), description="Tuple of diagnostic records in batch")
    returned_count: int = Field(
        ...,
        ge=0,
        description="Exact number of items in this response (matches len(items))",
    )
    total_matched: int | None = Field(
        default=None,
        ge=0,
        description="Total matching items if known; must be >= returned_count",
    )
    is_truncated: bool = Field(
        default=False,
        description="Whether additional matching records exist beyond this batch",
    )

    @model_validator(mode="after")
    def validate_envelope_invariants(self) -> "BoundedDiagnosticResultDTO[T]":
        """Enforce internal consistency between items, returned_count, and total_matched."""
        actual_len = len(self.items)
        if self.returned_count != actual_len:
            raise ValueError(
                f"returned_count ({self.returned_count}) must equal len(items) ({actual_len})"
            )
        if self.total_matched is not None and self.total_matched < self.returned_count:
            raise ValueError(
                f"total_matched ({self.total_matched}) cannot be less than "
                f"returned_count ({self.returned_count})"
            )
        return self


# ============================================================================
# 2. Diagnostic Request / Criteria DTOs
# ============================================================================


class SlowQueryCriteriaDTO(PlatformBaseModel):
    """Structured criteria for finding slow database queries."""

    start_time: datetime | None = Field(
        default=None,
        description="Start of observation time window (UTC)",
    )
    end_time: datetime | None = Field(
        default=None,
        description="End of observation time window (UTC)",
    )
    min_duration_ms: int = Field(
        default=1000,
        ge=1,
        description="Minimum execution duration threshold in milliseconds",
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        description="Optional caller requested limit bound",
    )


class DeadlockCriteriaDTO(PlatformBaseModel):
    """Structured criteria for querying recent deadlock events."""

    start_time: datetime | None = Field(
        default=None,
        description="Start of observation time window (UTC)",
    )
    end_time: datetime | None = Field(
        default=None,
        description="End of observation time window (UTC)",
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        description="Optional caller requested limit bound",
    )


class BlockingSessionCriteriaDTO(PlatformBaseModel):
    """Structured criteria for querying active blocking sessions."""

    min_blocked_duration_ms: int = Field(
        default=5000,
        ge=1,
        description="Minimum blocked duration threshold in milliseconds",
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        description="Optional caller requested limit bound",
    )


class TicketDiagnosticCriteriaDTO(PlatformBaseModel):
    """Criteria for ticket-scoped diagnostic record lookup."""

    ticket_id: int = Field(..., ge=1, description="Unique ticket identifier")


class LogSearchCriteriaDTO(PlatformBaseModel):
    """Structured criteria for searching application and API logs."""

    start_time: datetime | None = Field(
        default=None,
        description="Start of log time window (UTC)",
    )
    end_time: datetime | None = Field(
        default=None,
        description="End of log time window (UTC)",
    )
    service_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Target service or application name (e.g. auth-service, web-api)",
    )
    severity: str | None = Field(
        default=None,
        description="Log severity level filter (e.g. INFO, WARN, ERROR, CRITICAL)",
    )
    correlation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Request correlation or trace identifier",
    )
    ticket_id: int | None = Field(
        default=None,
        ge=1,
        description="Associated ticket identifier if tagged in logs",
    )
    query_text: str | None = Field(
        default=None,
        max_length=256,
        description="Constrained literal search term (treated as plain data, not query syntax)",
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        description="Optional caller requested limit bound",
    )


# ============================================================================
# 3. Normalized Database Health DTO
# ============================================================================


class DatabaseBackupStatusDTO(PlatformBaseModel):
    """Structured backup status information from SQL Server backup history."""

    backup_found: bool | None = Field(
        ...,
        description="Whether successful backup history exists, or None if unavailable",
    )
    latest_backup_at: datetime | None = Field(
        default=None,
        description=(
            "SQL Server-recorded timestamp of the latest backup of any type without timezone "
            "offset. TIMEZONE IS UNASSERTED. Clients MUST NOT append 'Z', label as UTC, or "
            "perform timezone conversions without validated timezone information."
        ),
    )
    latest_backup_type: str | None = Field(
        default=None,
        description="Backup type of the latest successful backup (FULL, DIFFERENTIAL, LOG, etc.)",
    )
    latest_full_backup_at: datetime | None = Field(
        default=None,
        description=(
            "SQL Server-recorded timestamp of the latest successful FULL backup without timezone "
            "offset. TIMEZONE IS UNASSERTED. Clients MUST NOT append 'Z', label as UTC, or "
            "perform timezone conversions without validated timezone information."
        ),
    )
    latest_differential_backup_at: datetime | None = Field(
        default=None,
        description=(
            "SQL Server-recorded timestamp of the latest successful DIFFERENTIAL backup without "
            "timezone offset. TIMEZONE IS UNASSERTED. Clients MUST NOT append 'Z', label as UTC, "
            "or perform timezone conversions without validated timezone information."
        ),
    )
    latest_log_backup_at: datetime | None = Field(
        default=None,
        description=(
            "SQL Server-recorded timestamp of the latest successful TRANSACTION LOG backup without "
            "timezone offset. TIMEZONE IS UNASSERTED. Clients MUST NOT append 'Z', label as UTC, "
            "or perform timezone conversions without validated timezone information."
        ),
    )
    status: str = Field(
        default="AVAILABLE",
        description=(
            "Status of backup history inspection: AVAILABLE, UNAVAILABLE, or DEGRADED. "
            "status=AVAILABLE means backup-history inspection succeeded. It does NOT mean the "
            "backup is healthy, fresh, policy-compliant, or restorable (no backup freshness SLA "
            "is defined)."
        ),
    )
    error_message: str | None = Field(
        default=None,
        description=(
            "Safe diagnostic error message if backup history inspection was unavailable. "
            "error_message=null means only that backup-history retrieval did not report an error; "
            "it does NOT mean physical backup file verification succeeded."
        ),
    )


DatabaseConnectivityState = Literal[
    "CONNECTED",
    "DNS_RESOLUTION_FAILURE",
    "TCP_CONNECTIVITY_FAILURE",
    "TCP_CONNECTIVITY_TIMEOUT",
    "DATABASE_AUTHENTICATION_FAILURE",
    "DATABASE_CONNECTION_FAILURE",
    "DATABASE_CONNECTION_TIMEOUT",
    "DATABASE_QUERY_FAILURE",
    "DATABASE_QUERY_TIMEOUT",
    "UNKNOWN",
]


class DatabaseConnectivityDTO(PlatformBaseModel):
    """Factual stage-level connectivity status for configured database endpoint."""

    state: DatabaseConnectivityState = Field(
        ...,
        description=(
            "Observed connectivity state: CONNECTED, DNS_RESOLUTION_FAILURE, "
            "TCP_CONNECTIVITY_FAILURE, TCP_CONNECTIVITY_TIMEOUT, "
            "DATABASE_AUTHENTICATION_FAILURE, DATABASE_CONNECTION_FAILURE, "
            "DATABASE_CONNECTION_TIMEOUT, DATABASE_QUERY_FAILURE, "
            "DATABASE_QUERY_TIMEOUT, or UNKNOWN. Represents observed failure boundary only."
        ),
    )
    observed_failure: str | None = Field(
        default=None,
        description="Factual, sanitized description of observed failure boundary.",
    )


class DatabaseHealthDomainDTO(PlatformBaseModel):
    """Normalized internal database health indicators."""

    is_healthy: bool = Field(..., description="High-level availability state")
    status_summary: str = Field(..., description="High-level status summary (e.g. ONLINE)")
    active_connections: int = Field(
        default=0,
        ge=0,
        description="Current approximate active connection count",
    )
    latency_ms: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Observed round-trip ping/DMV latency in milliseconds. Observational diagnostic "
            "measurement only; does not prove client-side timeout thresholds or saturation."
        ),
    )
    collected_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Collection timestamp in UTC",
    )
    backup_status: DatabaseBackupStatusDTO | None = Field(
        default=None,
        description="SQL Server database backup status and history",
    )
    connectivity: DatabaseConnectivityDTO | None = Field(
        default=None,
        description=(
            "Factual connectivity diagnostic observation for the configured database endpoint"
        ),
    )


# ============================================================================
# 4. Internal Domain Diagnostic DTOs (Restricted / Adapter Layer)
# ============================================================================


class SlowQueryDomainDTO(PlatformBaseModel):
    """Internal domain representation of a slow query event."""

    query_hash: str = Field(..., description="Normalized query fingerprint / plan hash")
    duration_ms: int = Field(..., ge=0, description="Execution duration in milliseconds")
    cpu_time_ms: int = Field(default=0, ge=0, description="Total CPU time in milliseconds")
    logical_reads: int = Field(default=0, ge=0, description="Total logical read count")
    execution_count: int = Field(default=1, ge=1, description="Execution frequency count")
    last_execution_time: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last execution timestamp (UTC)",
    )
    summary: str = Field(
        default="",
        description="Safe, non-sensitive diagnostic summary of query intent",
    )


class DeadlockDomainDTO(PlatformBaseModel):
    """Internal domain representation of a database deadlock event."""

    deadlock_id: str = Field(..., description="Deterministic deadlock event identifier")
    occurred_at: datetime = Field(..., description="Deadlock detection timestamp (UTC)")
    victim_session_id: int = Field(..., ge=1, description="Killed victim session ID")
    participating_session_count: int = Field(
        ...,
        ge=2,
        description="Number of sessions in deadlock cycle",
    )
    resource_description: str = Field(
        default="",
        description="High-level classification of contentious resource (e.g. Page Lock)",
    )
    summary: str = Field(default="", description="Safe summary of deadlock incident")


class BlockingSessionDomainDTO(PlatformBaseModel):
    """Internal domain representation of an active blocking session."""

    blocked_session_id: int = Field(..., ge=1, description="Identifier of blocked session")
    blocking_session_id: int = Field(..., ge=1, description="Identifier of head blocking session")
    wait_duration_ms: int = Field(
        ...,
        ge=0,
        description="Duration the session has been waiting in milliseconds",
    )
    wait_type: str = Field(
        default="",
        description="MSSQL wait category or type (e.g. LCK_M_X)",
    )
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Detection timestamp in UTC",
    )


class TicketDiagnosticRecordDomainDTO(PlatformBaseModel):
    """Diagnostic activity record scoped to a ticket identifier."""

    ticket_id: int = Field(..., ge=1, description="Unique ticket identifier")
    has_db_activity: bool = Field(
        default=False,
        description="Whether recent database activity references this ticket",
    )
    recent_error_count: int = Field(
        default=0,
        ge=0,
        description="Count of recent errors matching ticket context",
    )
    last_activity_time: datetime | None = Field(
        default=None,
        description="Timestamp of latest DB activity for ticket",
    )
    diagnostic_summary: str = Field(
        default="",
        description="Safe diagnostic summary for ticket database state",
    )


# ============================================================================
# 5. Internal Log Record DTO (Restricted) vs AI-Safe Log Excerpt DTO
# ============================================================================


class LogRecordDomainDTO(PlatformBaseModel):
    """RESTRICTED: Internal application/API log record from backend log search.

    May contain unredacted message text, trace IDs, and internal metadata.
    Must NOT be passed directly to the AI model without sanitization.
    """

    log_id: str = Field(..., description="Unique log event identifier")
    timestamp: datetime = Field(..., description="Log generation UTC timestamp")
    service_name: str = Field(..., description="Originating service or application name")
    severity: str = Field(..., description="Log severity (INFO, WARN, ERROR, CRITICAL)")
    message: str = Field(
        ...,
        description="RESTRICTED: Raw internal log message text, potentially containing PII",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Request correlation or trace identifier",
    )
    ticket_id: int | None = Field(
        default=None,
        ge=1,
        description="Associated ticket identifier if tagged",
    )
    raw_context: dict[str, str] = Field(
        default_factory=dict,
        description="RESTRICTED: Key-value context tags",
    )


class SanitizedLogExcerptDTO(PlatformBaseModel):
    """AI-FACING: Sanitized and minimized log excerpt safe for AI investigation context.

    All PII, authentication tokens, connection strings, and credentials have been scrubbed.
    """

    excerpt_id: str = Field(..., description="Unique sanitized excerpt identifier")
    timestamp: datetime = Field(..., description="Log generation UTC timestamp")
    service_name: str = Field(..., description="Originating service name")
    severity: str = Field(..., description="Log level (INFO, WARN, ERROR)")
    sanitized_message: str = Field(
        ...,
        description="PII-scrubbed, secret-masked log message text for AI context",
    )
    correlation_id: str | None = Field(
        default=None,
        description="Request correlation or trace identifier",
    )
