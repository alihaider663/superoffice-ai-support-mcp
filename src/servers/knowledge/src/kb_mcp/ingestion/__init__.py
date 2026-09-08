"""Knowledge ingestion admission, parsing, normalization, and sanitization boundary (Gate 7D.5B)."""

from kb_mcp.ingestion.eligibility import (
    CorpusEligibilityPolicy,
    EligibilityResult,
)
from kb_mcp.ingestion.normalization import normalize_text
from kb_mcp.ingestion.parsers import (
    KnownIssueJsonParser,
    MarkdownParser,
    ParsedKnownIssueModel,
    ParsedRunbookModel,
    PlainTextParser,
    RunbookJsonParser,
    decode_strict_utf8,
)
from kb_mcp.ingestion.sanitizer import (
    KnowledgeSanitizer,
    SanitizationOutcome,
    is_safe_placeholder,
)
from kb_mcp.ingestion.service import KnowledgeAdmissionService

__all__ = [
    "CorpusEligibilityPolicy",
    "EligibilityResult",
    "KnowledgeAdmissionService",
    "KnowledgeSanitizer",
    "KnownIssueJsonParser",
    "MarkdownParser",
    "ParsedKnownIssueModel",
    "ParsedRunbookModel",
    "PlainTextParser",
    "RunbookJsonParser",
    "SanitizationOutcome",
    "decode_strict_utf8",
    "is_safe_placeholder",
    "normalize_text",
]
