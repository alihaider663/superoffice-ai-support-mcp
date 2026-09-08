"""Parsers for Knowledge source documents and structured artifacts (Gate 7D.5B)."""

import json
import re
from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, ValidationError, field_validator

from kb_mcp.contracts.constants import (
    KNOWN_ISSUE_CATEGORY_MAX_LENGTH,
    KNOWN_ISSUE_FIX_REF_MAX_LENGTH,
    KNOWN_ISSUE_ID_MAX_LENGTH,
    KNOWN_ISSUE_ID_MIN_LENGTH,
    KNOWN_ISSUE_MAX_AFFECTED_PRODUCTS,
    KNOWN_ISSUE_MAX_AFFECTED_VERSIONS,
    KNOWN_ISSUE_PRODUCT_MAX_LENGTH,
    KNOWN_ISSUE_ROOT_CAUSE_MAX_CHARS,
    KNOWN_ISSUE_SOURCE_REF_MAX_LENGTH,
    KNOWN_ISSUE_SYMPTOM_MAX_CHARS,
    KNOWN_ISSUE_SYMPTOM_MIN_CHARS,
    KNOWN_ISSUE_TITLE_MAX_LENGTH,
    KNOWN_ISSUE_TITLE_MIN_LENGTH,
    KNOWN_ISSUE_VERSION_MAX_LENGTH,
    KNOWN_ISSUE_WORKAROUND_MAX_CHARS,
    RUNBOOK_ID_MAX_LENGTH,
    RUNBOOK_ID_MIN_LENGTH,
    RUNBOOK_MAX_STEPS,
    RUNBOOK_MIN_STEPS,
    RUNBOOK_PROBLEM_DESC_MAX_CHARS,
    RUNBOOK_PROBLEM_DESC_MIN_CHARS,
    RUNBOOK_PRODUCT_MAX_LENGTH,
    RUNBOOK_SOURCE_REF_MAX_LENGTH,
    RUNBOOK_STEP_MAX_LENGTH,
    RUNBOOK_TITLE_MAX_LENGTH,
    RUNBOOK_TITLE_MIN_LENGTH,
    RUNBOOK_VERIFIED_VERSION_MAX_LENGTH,
)
from kb_mcp.contracts.errors import KnowledgeSourceFormatError
from platform_core.models import PlatformBaseModel

# Regex pattern rejecting drive letters, UNC paths, backslashes, and credentials in URIs
_RE_UNSAFE_REF = re.compile(r"^[a-zA-Z]:|\\|://[^/\s]+:[^/\s]+@")


# ============================================================================
# Pydantic Ingestion Models (Extra Forbidden)
# ============================================================================


class ParsedRunbookModel(PlatformBaseModel):
    """Raw parsed Runbook JSON schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runbook_id: str = Field(
        ...,
        min_length=RUNBOOK_ID_MIN_LENGTH,
        max_length=RUNBOOK_ID_MAX_LENGTH,
    )
    title: str = Field(
        ...,
        min_length=RUNBOOK_TITLE_MIN_LENGTH,
        max_length=RUNBOOK_TITLE_MAX_LENGTH,
    )
    problem_description: str = Field(
        ...,
        min_length=RUNBOOK_PROBLEM_DESC_MIN_CHARS,
        max_length=RUNBOOK_PROBLEM_DESC_MAX_CHARS,
    )
    diagnostic_steps: list[str] = Field(
        ...,
        min_length=RUNBOOK_MIN_STEPS,
        max_length=RUNBOOK_MAX_STEPS,
    )
    remediation_steps: list[str] = Field(
        ...,
        min_length=RUNBOOK_MIN_STEPS,
        max_length=RUNBOOK_MAX_STEPS,
    )
    source_reference: str = Field(..., min_length=1, max_length=RUNBOOK_SOURCE_REF_MAX_LENGTH)
    product: str | None = Field(default=None, max_length=RUNBOOK_PRODUCT_MAX_LENGTH)
    verified_version: str | None = Field(
        default=None,
        max_length=RUNBOOK_VERIFIED_VERSION_MAX_LENGTH,
    )
    last_reviewed: datetime | None = Field(default=None)

    @field_validator("diagnostic_steps", "remediation_steps")
    @classmethod
    def validate_steps(cls, steps: list[str]) -> list[str]:
        for step in steps:
            s = step.strip()
            if not s:
                raise ValueError("Step cannot be empty or whitespace-only.")
            if len(step) > RUNBOOK_STEP_MAX_LENGTH:
                raise ValueError(
                    f"Step length ({len(step)}) exceeds max {RUNBOOK_STEP_MAX_LENGTH} characters."
                )
        return steps

    @field_validator("source_reference")
    @classmethod
    def validate_source_ref(cls, v: str) -> str:
        s = v.strip()
        if not s.startswith("runbook://"):
            raise ValueError("Runbook source_reference must start with 'runbook://'.")
        if _RE_UNSAFE_REF.search(s):
            raise ValueError(
                "Runbook source_reference cannot contain drive letters, backslashes, "
                "UNC paths, or credentials."
            )
        return s


class ParsedKnownIssueModel(PlatformBaseModel):
    """Raw parsed Known Issue JSON schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    issue_id: str = Field(
        ...,
        min_length=KNOWN_ISSUE_ID_MIN_LENGTH,
        max_length=KNOWN_ISSUE_ID_MAX_LENGTH,
    )
    title: str = Field(
        ...,
        min_length=KNOWN_ISSUE_TITLE_MIN_LENGTH,
        max_length=KNOWN_ISSUE_TITLE_MAX_LENGTH,
    )
    symptom_summary: str = Field(
        ...,
        min_length=KNOWN_ISSUE_SYMPTOM_MIN_CHARS,
        max_length=KNOWN_ISSUE_SYMPTOM_MAX_CHARS,
    )
    root_cause_summary: str = Field(
        default="",
        max_length=KNOWN_ISSUE_ROOT_CAUSE_MAX_CHARS,
    )
    workaround: str | None = Field(
        default=None,
        max_length=KNOWN_ISSUE_WORKAROUND_MAX_CHARS,
    )
    permanent_fix_reference: str | None = Field(
        default=None,
        max_length=KNOWN_ISSUE_FIX_REF_MAX_LENGTH,
    )
    affected_products: list[str] = Field(
        default_factory=list,
        max_length=KNOWN_ISSUE_MAX_AFFECTED_PRODUCTS,
    )
    affected_versions: list[str] = Field(
        default_factory=list,
        max_length=KNOWN_ISSUE_MAX_AFFECTED_VERSIONS,
    )
    category: str = Field(
        default="general",
        min_length=1,
        max_length=KNOWN_ISSUE_CATEGORY_MAX_LENGTH,
    )
    source_reference: str = Field(
        ...,
        min_length=1,
        max_length=KNOWN_ISSUE_SOURCE_REF_MAX_LENGTH,
    )

    @field_validator("affected_products")
    @classmethod
    def validate_products(cls, prods: list[str]) -> list[str]:
        for p in prods:
            if len(p) > KNOWN_ISSUE_PRODUCT_MAX_LENGTH:
                raise ValueError(
                    f"Product length ({len(p)}) exceeds max "
                    f"{KNOWN_ISSUE_PRODUCT_MAX_LENGTH} characters."
                )
        return prods

    @field_validator("affected_versions")
    @classmethod
    def validate_versions(cls, vers: list[str]) -> list[str]:
        for v in vers:
            if len(v) > KNOWN_ISSUE_VERSION_MAX_LENGTH:
                raise ValueError(
                    f"Version length ({len(v)}) exceeds max "
                    f"{KNOWN_ISSUE_VERSION_MAX_LENGTH} characters."
                )
        return vers

    @field_validator("source_reference")
    @classmethod
    def validate_source_ref(cls, v: str) -> str:
        s = v.strip()
        if not s.startswith("known-issue://"):
            raise ValueError("Known issue source_reference must start with 'known-issue://'.")
        if _RE_UNSAFE_REF.search(s):
            raise ValueError(
                "source_reference cannot contain drive letters, backslashes, "
                "UNC paths, or credentials."
            )
        return s

    @field_validator("permanent_fix_reference")
    @classmethod
    def validate_fix_ref(cls, v: str | None) -> str | None:
        if v is not None:
            s = v.strip()
            if _RE_UNSAFE_REF.search(s):
                raise ValueError(
                    "permanent_fix_reference cannot contain drive letters, backslashes, "
                    "UNC paths, or credentials."
                )
            return s
        return None


# ============================================================================
# Parsers
# ============================================================================


def decode_strict_utf8(raw_bytes: bytes) -> str:
    """Decode raw bytes using strict UTF-8; raise KnowledgeSourceFormatError on invalid bytes."""
    try:
        return raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise KnowledgeSourceFormatError(
            "Source content is not valid strict UTF-8 encoded text.",
            details={"encoding": "utf-8", "reason": "strict_decode_failed"},
        ) from exc


class MarkdownParser:
    """Parses Markdown source documents without HTML rendering or external loading."""

    def parse(self, raw_bytes: bytes) -> str:
        """Decode and validate Markdown content."""
        text = decode_strict_utf8(raw_bytes)
        if not text.strip():
            raise KnowledgeSourceFormatError(
                "Markdown document content is empty or whitespace-only."
            )
        return text


class PlainTextParser:
    """Parses plain text source documents."""

    def parse(self, raw_bytes: bytes) -> str:
        """Decode and validate plain text content."""
        text = decode_strict_utf8(raw_bytes)
        if not text.strip():
            raise KnowledgeSourceFormatError(
                "Plain text document content is empty or whitespace-only."
            )
        return text


class RunbookJsonParser:
    """Parses and validates operational Runbook JSON artifacts."""

    def parse(self, raw_bytes: bytes) -> ParsedRunbookModel:
        """Decode, parse JSON, and validate against Runbook schema."""
        text = decode_strict_utf8(raw_bytes)
        try:
            raw_data: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            raise KnowledgeSourceFormatError(
                "Malformed JSON in runbook document.",
                details={"parser": "RunbookJsonParser", "line": exc.lineno, "col": exc.colno},
            ) from exc

        if not isinstance(raw_data, dict):
            raise KnowledgeSourceFormatError("Runbook JSON root must be an object.")

        try:
            return ParsedRunbookModel.model_validate(raw_data)
        except ValidationError as exc:
            raise KnowledgeSourceFormatError(
                "Runbook schema validation failed.",
                details={"errors_count": len(exc.errors())},
            ) from exc


class KnownIssueJsonParser:
    """Parses and validates Known Issue JSON artifacts."""

    def parse(self, raw_bytes: bytes) -> ParsedKnownIssueModel:
        """Decode, parse JSON, and validate against Known Issue schema."""
        text = decode_strict_utf8(raw_bytes)
        try:
            raw_data: Any = json.loads(text)
        except json.JSONDecodeError as exc:
            raise KnowledgeSourceFormatError(
                "Malformed JSON in known issue document.",
                details={"parser": "KnownIssueJsonParser", "line": exc.lineno, "col": exc.colno},
            ) from exc

        if not isinstance(raw_data, dict):
            raise KnowledgeSourceFormatError("Known Issue JSON root must be an object.")

        try:
            return ParsedKnownIssueModel.model_validate(raw_data)
        except ValidationError as exc:
            raise KnowledgeSourceFormatError(
                "Known Issue schema validation failed.",
                details={"errors_count": len(exc.errors())},
            ) from exc
