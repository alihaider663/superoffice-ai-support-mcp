"""Security interfaces, policy engines, and sanitization protocols."""

from typing import Any, Protocol, runtime_checkable

from platform_security.models import (
    AttachmentMetadata,
    AuthorizationDecision,
    PIIRedactionResult,
    SecurityContext,
)


@runtime_checkable
class Authenticator(Protocol):
    """Protocol for validating inbound credentials and producing a SecurityContext."""

    async def authenticate(self, credentials_or_token: str) -> SecurityContext:
        """Validate credentials or token and return a verified SecurityContext."""
        ...


@runtime_checkable
class Authorizer(Protocol):
    """Protocol for enforcing RBAC permissions and access policies."""

    async def authorize(
        self,
        context: SecurityContext,
        action: str,
        resource: str | None = None,
    ) -> AuthorizationDecision:
        """Evaluate if the principal is authorized to perform action on resource."""
        ...


@runtime_checkable
class PolicyEngine(Protocol):
    """Protocol for evaluating multi-dimensional security policies."""

    def evaluate_policy(
        self,
        principal_role: str,
        tool_name: str,
        environment: str = "production",
        context_attributes: dict[str, Any] | None = None,
    ) -> AuthorizationDecision:
        """Synchronously evaluate security policy rules."""
        ...


@runtime_checkable
class PIIFilter(Protocol):
    """Protocol for scanning and redacting sensitive PII from string buffers."""

    def redact(self, text: str) -> PIIRedactionResult:
        """Scan text and replace sensitive patterns with redaction tokens."""
        ...


@runtime_checkable
class OutputSanitizer(Protocol):
    """Protocol for sanitizing arbitrary nested data structures before AI emission."""

    def sanitize(self, payload: Any) -> Any:
        """Deeply inspect and sanitize data structure, masking PII and scrubbed fields."""
        ...


@runtime_checkable
class AttachmentPolicy(Protocol):
    """Protocol for evaluating attachment access authorization."""

    def is_access_permitted(
        self,
        metadata: AttachmentMetadata,
        context: SecurityContext,
    ) -> AuthorizationDecision:
        """Determine if raw attachment payload extraction is permitted."""
        ...
