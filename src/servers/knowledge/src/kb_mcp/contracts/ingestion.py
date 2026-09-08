"""Contracts, DTOs, and Enums for Knowledge Ingestion Admission (Gate 7D.5B)."""

from datetime import datetime
from enum import StrEnum

from pydantic import ConfigDict, Field

from platform_core.models import PlatformBaseModel


class IngestionSourceKind(StrEnum):
    """Permitted source kinds for knowledge ingestion (Local-v1 frozen set)."""

    MARKDOWN_DOCUMENT = "markdown_document"
    TEXT_DOCUMENT = "text_document"
    RUNBOOK_JSON = "runbook_json"
    KNOWN_ISSUE_JSON = "known_issue_json"


class CorpusCategory(StrEnum):
    """Allowlisted conceptual corpus categories for admitted knowledge items."""

    DOCUMENTATION = "documentation"
    SOP = "sop"
    RUNBOOK = "runbook"
    KNOWN_ISSUE = "known_issue"
    INCIDENT_PATTERN = "incident_pattern"


class ProhibitedSourceClassification(StrEnum):
    """Prohibited source classifications subject to immediate fail-closed rejection."""

    CUSTOMER_ATTACHMENT = "customer_attachment"
    LIVE_CRM = "live_crm"
    CUSTOMER_EXPORT = "customer_export"
    RAW_TICKET_DUMP = "raw_ticket_dump"
    CUSTOMER_INTERACTION_TRANSCRIPT = "customer_interaction_transcript"


class AdmissionDecision(StrEnum):
    """Admission decision outcome."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class AdmissionReasonCode(StrEnum):
    """Safe, high-level, non-leaking admission decision reason codes."""

    SECRET_DETECTED = "SECRET_DETECTED"
    PII_DETECTED = "PII_DETECTED"
    CUSTOMER_ATTACHMENT_DETECTED = "CUSTOMER_ATTACHMENT_DETECTED"
    PROHIBITED_SOURCE_CLASSIFICATION = "PROHIBITED_SOURCE_CLASSIFICATION"
    UNSUPPORTED_SOURCE_KIND = "UNSUPPORTED_SOURCE_KIND"
    UNSUPPORTED_CATEGORY = "UNSUPPORTED_CATEGORY"
    CATEGORY_MISMATCH = "CATEGORY_MISMATCH"
    SIZE_LIMIT_EXCEEDED = "SIZE_LIMIT_EXCEEDED"
    SOURCE_TOO_SHORT = "SOURCE_TOO_SHORT"
    FORMAT_ERROR = "FORMAT_ERROR"
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    INVALID_PROVENANCE = "INVALID_PROVENANCE"
    INVALID_SOURCE_NAME = "INVALID_SOURCE_NAME"
    EMPTY_CONTENT = "EMPTY_CONTENT"


# ============================================================================
# Ingestion Boundary Input DTO
# ============================================================================


class AdmissionSourceInputDTO(PlatformBaseModel):
    """In-memory candidate source submitted for ingestion admission evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Logical display name or basename only (no physical paths)",
    )
    source_kind: IngestionSourceKind = Field(
        ...,
        description="Explicit source kind declaration",
    )
    corpus_category: CorpusCategory = Field(
        ...,
        description="Target corpus category classification",
    )
    raw_bytes: bytes = Field(
        ...,
        description="Raw byte content of the candidate source",
    )
    classification: str | None = Field(
        default=None,
        description="Optional security classification label (e.g. customer_attachment, live_crm)",
    )


# ============================================================================
# Sanitized Admitted Payload DTOs
# ============================================================================


class SanitizedDocumentPayloadDTO(PlatformBaseModel):
    """Sanitized, normalized free-text document payload (Markdown or Plain Text)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str = Field(..., description="Safe logical display name")
    source_kind: IngestionSourceKind = Field(..., description="Document source kind")
    corpus_category: CorpusCategory = Field(..., description="Admitted corpus category")
    canonical_text: str = Field(..., description="Sanitized, normalized UTF-8 text")


class SanitizedRunbookPayloadDTO(PlatformBaseModel):
    """Sanitized, normalized operational runbook payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str = Field(..., description="Safe logical display name")
    runbook_id: str = Field(..., description="Validated runbook identifier")
    title: str = Field(..., description="Sanitized runbook title")
    problem_description: str = Field(..., description="Sanitized problem statement")
    diagnostic_steps: tuple[str, ...] = Field(
        ...,
        description="Sanitized, ordered diagnostic investigation steps",
    )
    remediation_steps: tuple[str, ...] = Field(
        ...,
        description="Sanitized, ordered recovery steps",
    )
    product: str | None = Field(default=None, description="Optional associated product name")
    verified_version: str | None = Field(
        default=None,
        description="Optional verified product version",
    )
    last_reviewed: datetime | None = Field(
        default=None,
        description="Optional review verification timestamp",
    )
    source_reference: str = Field(
        ...,
        description="Safe runbook reference URI (runbook://...)",
    )
    canonical_text: str = Field(
        ...,
        description="Deterministic composite text for indexing and retrieval",
    )


class SanitizedKnownIssuePayloadDTO(PlatformBaseModel):
    """Sanitized, normalized verified known issue payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_name: str = Field(..., description="Safe logical display name")
    issue_id: str = Field(..., description="Validated known issue identifier")
    title: str = Field(..., description="Sanitized issue title")
    symptom_summary: str = Field(..., description="Sanitized symptom description")
    root_cause_summary: str = Field(..., description="Sanitized root cause explanation")
    workaround: str | None = Field(default=None, description="Sanitized workaround instructions")
    permanent_fix_reference: str | None = Field(
        default=None,
        description="Safe fix reference identifier",
    )
    affected_products: tuple[str, ...] = Field(
        default=(),
        description="Sanitized affected products",
    )
    affected_versions: tuple[str, ...] = Field(
        default=(),
        description="Sanitized affected versions",
    )
    category: str = Field(default="general", description="Issue category classification")
    source_reference: str = Field(
        ...,
        description="Safe known issue reference URI (known-issue://...)",
    )
    canonical_text: str = Field(
        ...,
        description="Deterministic composite text for indexing and retrieval",
    )


type SanitizedIngestionPayload = (
    SanitizedDocumentPayloadDTO | SanitizedRunbookPayloadDTO | SanitizedKnownIssuePayloadDTO
)


# ============================================================================
# Admission Result
# ============================================================================


class AdmissionResult(PlatformBaseModel):
    """Final decision and sanitized payload from the ingestion admission boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: AdmissionDecision = Field(..., description="Admission outcome decision")
    reason_code: AdmissionReasonCode | None = Field(
        default=None,
        description="Safe categorical reason code for rejection or failure",
    )
    message: str = Field(default="", description="Safe, non-leaking diagnostic message")
    sanitized_payload: SanitizedIngestionPayload | None = Field(
        default=None,
        description="Sanitized payload (present only if decision is APPROVED)",
    )
    pii_redaction_count: int = Field(
        default=0,
        ge=0,
        description="Total count of incidental PII occurrences redacted",
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description="Safe non-sensitive operational warnings",
    )
