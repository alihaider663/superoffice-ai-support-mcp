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
    source_reference: str | None = Field(
        default=None,
        max_length=128,
        description="Optional explicit logical provenance reference (e.g. docs://..., sop://...)",
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
    source_reference: str | None = Field(
        default=None,
        max_length=128,
        description="Validated logical provenance reference",
    )


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


# ============================================================================
# Canonical Document & Artifact DTOs (Gate 7D.5C / Local-v1)
# ============================================================================


class CanonicalKnowledgeDocumentDTO(PlatformBaseModel):
    """Immutable, approved canonical knowledge document ready for artifact storage and indexing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Deterministic document identifier (doc_<24_hex>)",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Sanitized document title",
    )
    document_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Allowlisted document type category",
    )
    source_reference: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Safe logical provenance reference URI",
    )
    canonical_content: str = Field(
        ...,
        min_length=1,
        description="Sanitized, normalized canonical UTF-8 content",
    )
    content_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Deterministic SHA-256 lowercase hex digest of canonical_content",
    )
    corpus_category: CorpusCategory = Field(
        ...,
        description="Associated corpus category",
    )
    structured_payload: SanitizedRunbookPayloadDTO | SanitizedKnownIssuePayloadDTO | None = Field(
        default=None,
        description="Optional parsed structured payload for runbooks or known issues",
    )


class StagedArtifactToken(PlatformBaseModel):
    """Opaque reference token for a staged artifact in temporary storage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    staging_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Safe temporary staging identifier (e.g. doc_<hash>_<uuid>.tmp)",
    )
    document_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Deterministic document identifier",
    )
    document_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Allowlisted document type",
    )
    content_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Expected SHA-256 content hash",
    )


class ApprovedArtifactRecord(PlatformBaseModel):
    """Logical descriptor of an approved, content-addressed artifact in storage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Allowlisted document type",
    )
    document_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Deterministic document identifier",
    )
    content_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="SHA-256 content hash",
    )


# ============================================================================
# Deterministic Chunking & Transaction Persistence DTOs (Gate 7D.5D / Local-v1)
# ============================================================================


class ChunkDraftDTO(PlatformBaseModel):
    """Pre-embedding draft chunk produced by DeterministicChunker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Deterministic chunk identifier (<doc_id>_c<idx:04d>)",
    )
    document_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Deterministic document identifier",
    )
    chunk_index: int = Field(
        ...,
        ge=0,
        description="0-based sequential chunk index",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="Sanitized chunk text content",
    )


class EmbeddedChunkDTO(PlatformBaseModel):
    """DB-ready chunk enriched with validated dense vector embedding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Deterministic chunk identifier (<doc_id>_c<idx:04d>)",
    )
    document_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Deterministic document identifier",
    )
    chunk_index: int = Field(
        ...,
        ge=0,
        description="0-based sequential chunk index",
    )
    content: str = Field(
        ...,
        min_length=1,
        description="Sanitized chunk text content",
    )
    embedding: tuple[float, ...] = Field(
        ...,
        min_length=384,
        max_length=384,
        description="384-dimensional dense vector embedding",
    )


class DocumentStateDTO(PlatformBaseModel):
    """Lightweight document state descriptor for fast-path idempotency checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Deterministic document identifier",
    )
    content_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Current 64-char SHA-256 content hash in database",
    )
    version: int = Field(
        ...,
        ge=1,
        description="Current document version in database",
    )


class IngestionStatus(StrEnum):
    """Outcome status of an ingestion operation."""

    APPROVED = "APPROVED"
    UNCHANGED = "UNCHANGED"


class IngestionResultDTO(PlatformBaseModel):
    """Safe logical result returned by KnowledgeIngestionCoordinator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: IngestionStatus = Field(..., description="Ingestion outcome status")
    document_id: str = Field(..., min_length=1, max_length=64, description="Document identifier")
    source_reference: str = Field(
        ..., min_length=1, max_length=128, description="Logical provenance reference"
    )
    content_hash: str = Field(..., min_length=64, max_length=64, description="SHA-256 content hash")
    version: int = Field(..., ge=1, description="Committed document version")
    chunk_count: int = Field(..., ge=0, description="Count of persisted chunks (0 if UNCHANGED)")
