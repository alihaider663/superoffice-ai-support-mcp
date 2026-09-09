"""Canonical document identity, provenance validation, content hashing, and DTO construction.

Gate 7D.5C: Frozen Canonical Identity & Provenance Invariants.
"""

import hashlib
import re
from typing import Final

from kb_mcp.contracts.constants import (
    ALLOWED_DOCUMENT_TYPES,
    DOCUMENT_ID_HASH_CHARS,
    DOCUMENT_ID_MAX_LENGTH,
    DOCUMENT_ID_PREFIX,
    DOCUMENT_TYPE_MAX_LENGTH,
    SOURCE_REFERENCE_MAX_LENGTH,
)
from kb_mcp.contracts.errors import KnowledgeAdmissionError
from kb_mcp.contracts.ingestion import (
    CanonicalKnowledgeDocumentDTO,
    CorpusCategory,
    SanitizedDocumentPayloadDTO,
    SanitizedIngestionPayload,
    SanitizedKnownIssuePayloadDTO,
    SanitizedRunbookPayloadDTO,
)

# Unsafe reference patterns: drive letters, backslashes, UNC paths, credentials, traversal
_RE_UNSAFE_PROVENANCE: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z]:|\\|://[^/\s]+:[^/\s]+@|\.\."
)

_SCHEME_CATEGORY_MAP: Final[dict[CorpusCategory, str]] = {
    CorpusCategory.DOCUMENTATION: "docs://",
    CorpusCategory.SOP: "sop://",
    CorpusCategory.RUNBOOK: "runbook://",
    CorpusCategory.KNOWN_ISSUE: "known-issue://",
    CorpusCategory.INCIDENT_PATTERN: "incident-pattern://",
}


def validate_provenance(source_reference: str, corpus_category: CorpusCategory) -> None:
    """Validate logical provenance URI against approved schemes and security constraints.

    Args:
        source_reference: Logical provenance URI (e.g. docs://..., runbook://...).
        corpus_category: Admitted corpus category.

    Raises:
        KnowledgeAdmissionError: If scheme is invalid, unsafe, or mismatched with category.
    """
    ref = (source_reference or "").strip()
    if not ref:
        raise KnowledgeAdmissionError(
            "Source reference cannot be empty or whitespace-only.",
            error_code="INVALID_PROVENANCE",
        )

    if len(ref) > SOURCE_REFERENCE_MAX_LENGTH:
        raise KnowledgeAdmissionError(
            f"Source reference length ({len(ref)}) exceeds max {SOURCE_REFERENCE_MAX_LENGTH}.",
            error_code="INVALID_PROVENANCE",
        )

    if _RE_UNSAFE_PROVENANCE.search(ref):
        raise KnowledgeAdmissionError(
            "Source reference cannot contain drive letters, backslashes, UNC paths, "
            "credentials, or traversal sequences.",
            error_code="INVALID_PROVENANCE",
        )

    expected_scheme = _SCHEME_CATEGORY_MAP.get(corpus_category)
    if not expected_scheme or not ref.startswith(expected_scheme):
        raise KnowledgeAdmissionError(
            f"Source reference scheme mismatch for category '{corpus_category.value}'. "
            f"Must start with '{expected_scheme}'.",
            error_code="INVALID_PROVENANCE",
        )

    path_part = ref[len(expected_scheme) :].strip("/")
    if not path_part:
        raise KnowledgeAdmissionError(
            "Source reference must have a non-empty resource path after the scheme.",
            error_code="INVALID_PROVENANCE",
        )


def compute_content_hash(canonical_content: str) -> str:
    """Compute exact deterministic SHA-256 lowercase hex digest for canonical UTF-8 content.

    Args:
        canonical_content: Sanitized, normalized UTF-8 text.

    Returns:
        64-character lowercase hex digest string.

    Raises:
        KnowledgeAdmissionError: If content is empty or whitespace-only.
    """
    if not canonical_content or not canonical_content.strip():
        raise KnowledgeAdmissionError(
            "Cannot compute content hash for empty or whitespace-only canonical text.",
            error_code="EMPTY_CONTENT",
        )

    return hashlib.sha256(canonical_content.encode("utf-8")).hexdigest().lower()


def generate_document_id(logical_source_identity: str, document_type: str) -> str:
    """Generate deterministic document identifier: doc_ + SHA256(identity:type)[:24].

    Args:
        logical_source_identity: Stable logical identity (e.g. source_reference or ID).
        document_type: Allowlisted document type (e.g. documentation, runbook).

    Returns:
        Deterministic document identifier string (<= 64 chars).

    Raises:
        KnowledgeAdmissionError: If document_type is not allowlisted or identity is empty.
    """
    identity = (logical_source_identity or "").strip()
    doc_type = (document_type or "").strip()

    if not identity:
        raise KnowledgeAdmissionError(
            "Logical source identity cannot be empty.",
            error_code="INVALID_PROVENANCE",
        )

    if doc_type not in ALLOWED_DOCUMENT_TYPES:
        raise KnowledgeAdmissionError(
            f"Document type '{doc_type}' is not in allowlisted types: "
            f"{sorted(ALLOWED_DOCUMENT_TYPES)}.",
            error_code="INVALID_DOCUMENT_TYPE",
        )

    raw_key = f"{identity}:{doc_type}"
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:DOCUMENT_ID_HASH_CHARS]
    doc_id = f"{DOCUMENT_ID_PREFIX}{digest}"

    if len(doc_id) > DOCUMENT_ID_MAX_LENGTH:
        raise KnowledgeAdmissionError(
            f"Generated document_id exceeds maximum length of {DOCUMENT_ID_MAX_LENGTH}.",
            error_code="INVALID_DOCUMENT_ID",
        )

    return doc_id


def _build_runbook_canonical_dto(
    payload: SanitizedRunbookPayloadDTO,
    source_reference: str | None = None,
) -> CanonicalKnowledgeDocumentDTO:
    """Build canonical DTO for an operational runbook."""
    doc_type = "runbook"
    category = CorpusCategory.RUNBOOK
    src_ref = source_reference or payload.source_reference
    validate_provenance(src_ref, category)
    content_hash = compute_content_hash(payload.canonical_text)
    document_id = generate_document_id(src_ref, doc_type)

    return CanonicalKnowledgeDocumentDTO(
        document_id=document_id,
        title=payload.title[:255],
        document_type=doc_type[:DOCUMENT_TYPE_MAX_LENGTH],
        source_reference=src_ref[:SOURCE_REFERENCE_MAX_LENGTH],
        canonical_content=payload.canonical_text,
        content_hash=content_hash,
        corpus_category=category,
        structured_payload=payload,
    )


def _build_known_issue_canonical_dto(
    payload: SanitizedKnownIssuePayloadDTO,
    source_reference: str | None = None,
) -> CanonicalKnowledgeDocumentDTO:
    """Build canonical DTO for a verified known issue."""
    doc_type = "known_issue"
    category = CorpusCategory.KNOWN_ISSUE
    src_ref = source_reference or payload.source_reference
    validate_provenance(src_ref, category)
    content_hash = compute_content_hash(payload.canonical_text)
    document_id = generate_document_id(src_ref, doc_type)

    return CanonicalKnowledgeDocumentDTO(
        document_id=document_id,
        title=payload.title[:255],
        document_type=doc_type[:DOCUMENT_TYPE_MAX_LENGTH],
        source_reference=src_ref[:SOURCE_REFERENCE_MAX_LENGTH],
        canonical_content=payload.canonical_text,
        content_hash=content_hash,
        corpus_category=category,
        structured_payload=payload,
    )


def _extract_document_title(
    payload: SanitizedDocumentPayloadDTO,
    title_override: str | None,
) -> str:
    """Extract or derive title for a general document."""
    if title_override and title_override.strip():
        return title_override.strip()[:255]

    for line in payload.canonical_text.splitlines():
        sline = line.strip()
        if sline.startswith("# "):
            return sline[2:].strip()[:255]

    clean_name = re.sub(r"\.(md|txt)$", "", payload.source_name, flags=re.IGNORECASE).strip()
    return clean_name[:255]


def _build_general_document_canonical_dto(
    payload: SanitizedDocumentPayloadDTO,
    title: str | None = None,
    source_reference: str | None = None,
) -> CanonicalKnowledgeDocumentDTO:
    """Build canonical DTO for a general Markdown or PlainText document."""
    category = payload.corpus_category
    doc_type = category.value
    if doc_type not in ALLOWED_DOCUMENT_TYPES:
        raise KnowledgeAdmissionError(
            f"Corpus category '{category.value}' does not map to an allowlisted document type.",
            error_code="INVALID_DOCUMENT_TYPE",
        )

    if source_reference:
        src_ref = source_reference
    elif payload.source_reference:
        src_ref = payload.source_reference
    else:
        clean_name = re.sub(r"\.(md|txt)$", "", payload.source_name, flags=re.IGNORECASE).strip()
        scheme = _SCHEME_CATEGORY_MAP[category]
        src_ref = f"{scheme}{clean_name}"

    validate_provenance(src_ref, category)
    doc_title = _extract_document_title(payload, title)
    content_hash = compute_content_hash(payload.canonical_text)
    document_id = generate_document_id(src_ref, doc_type)

    return CanonicalKnowledgeDocumentDTO(
        document_id=document_id,
        title=doc_title,
        document_type=doc_type[:DOCUMENT_TYPE_MAX_LENGTH],
        source_reference=src_ref[:SOURCE_REFERENCE_MAX_LENGTH],
        canonical_content=payload.canonical_text,
        content_hash=content_hash,
        corpus_category=category,
        structured_payload=None,
    )


def build_canonical_document(
    sanitized_payload: SanitizedIngestionPayload,
    title: str | None = None,
    source_reference: str | None = None,
) -> CanonicalKnowledgeDocumentDTO:
    """Transform an approved 7D.5B sanitized payload into CanonicalKnowledgeDocumentDTO.

    Args:
        sanitized_payload: Approved 7D.5B sanitized payload.
        title: Optional override title for general documents.
        source_reference: Optional override logical provenance reference.

    Returns:
        CanonicalKnowledgeDocumentDTO with verified deterministic identity and content hash.

    Raises:
        TypeError: If input is not an approved SanitizedIngestionPayload.
        KnowledgeAdmissionError: If provenance validation or identity generation fails.
    """
    if isinstance(sanitized_payload, SanitizedRunbookPayloadDTO):
        return _build_runbook_canonical_dto(sanitized_payload, source_reference)

    if isinstance(sanitized_payload, SanitizedKnownIssuePayloadDTO):
        return _build_known_issue_canonical_dto(sanitized_payload, source_reference)

    if isinstance(sanitized_payload, SanitizedDocumentPayloadDTO):
        return _build_general_document_canonical_dto(sanitized_payload, title, source_reference)

    raise TypeError(
        f"Unsupported payload type '{type(sanitized_payload).__name__}'. "
        "Must be an approved SanitizedIngestionPayload."
    )
