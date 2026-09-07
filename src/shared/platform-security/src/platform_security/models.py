"""Security data structures, authorization decisions, and sanitization models."""

from typing import Any

from pydantic import Field

from platform_core.models import PlatformBaseModel, PrincipalIdentity


class SecurityContext(PlatformBaseModel):
    """Cryptographically verifiable security context propagated across services."""

    principal: PrincipalIdentity
    token_id: str = Field(..., description="Unique token/session identifier")
    is_authenticated: bool = Field(default=True, description="Authentication confirmation")
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Contextual claims and attributes",
    )


class AuthorizationDecision(PlatformBaseModel):
    """Result of an authorization policy evaluation."""

    is_allowed: bool = Field(..., description="Whether action is authorized")
    reason: str = Field(default="", description="Diagnostic explanation for decision")
    denial_code: str | None = Field(default=None, description="Standard denial classification code")


class PIIRedactionResult(PlatformBaseModel):
    """Result of a PII scrubbing and masking operation."""

    sanitized_text: str = Field(..., description="Masked output string safe for AI consumption")
    redactions_count: int = Field(
        default=0,
        description="Total number of sensitive patterns redacted",
    )
    redacted_categories: tuple[str, ...] = Field(
        default=(),
        description="Classifications of redacted data",
    )


class AttachmentMetadata(PlatformBaseModel):
    """Safe metadata description of an attachment (without raw content)."""

    attachment_id: str | int = Field(..., description="Unique attachment ID")
    filename: str = Field(..., description="Sanitized filename")
    mime_type: str = Field(..., description="Declared MIME classification")
    size_bytes: int = Field(..., ge=0, description="File size in bytes")
    md5_hash: str = Field(..., description="MD5 content digest for integrity verification")
    is_content_authorized: bool = Field(
        default=False,
        description="Whether content retrieval is authorized",
    )
