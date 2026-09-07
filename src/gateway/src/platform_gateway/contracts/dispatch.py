"""Gateway normalized internal dispatch request and response models."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import Field, field_validator

from platform_core.models import (
    CorrelationIdentifier,
    PlatformBaseModel,
    UtcTimestamp,
)
from platform_gateway.contracts.types import JsonObject, JsonValue, is_json_compatible
from platform_security.models import SecurityContext


class SanitizedErrorPayload(PlatformBaseModel):
    """Domain-neutral sanitized error payload safe for transport and AI clients."""

    error: str = Field(..., description="Machine-readable error classification code")
    message: str = Field(..., description="Sanitized human-readable error message")
    correlation_id: str | None = Field(
        default=None,
        description="Preserved correlation identifier",
    )
    timestamp: UtcTimestamp = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Error occurrence timestamp",
    )


class GatewayDispatchRequest(PlatformBaseModel):
    """Normalized internal dispatch request envelope sent to downstream transport.

    CRITICAL TRUST BOUNDARY:
    The security_context field represents internal trusted context derived by the Gateway
    authentication and policy evaluation engine from validated credentials / JWTs.
    External AI / LLM clients CANNOT construct or self-declare their own SecurityContext.
    """

    tool_name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Canonical requested MCP tool name",
    )
    arguments: JsonObject = Field(
        default_factory=dict,
        description="JSON-compatible tool invocation arguments",
    )
    security_context: SecurityContext = Field(
        ...,
        description="Trusted caller security context after Gateway authentication",
    )
    correlation_id: CorrelationIdentifier = Field(
        default_factory=lambda: str(uuid4()),
        description="Request correlation identifier for end-to-end tracing",
    )

    @field_validator("arguments", mode="before")
    @classmethod
    def validate_arguments_json_compatible(cls, v: object) -> object:
        """Enforce strict JSON compatibility on raw arguments before coercion."""
        if not is_json_compatible(v):
            raise ValueError("Arguments must strictly contain JSON-compatible data types.")
        return v


class GatewayDispatchResponse(PlatformBaseModel):
    """Normalized domain-neutral response envelope received from downstream transport."""

    tool_name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Canonical tool name invoked",
    )
    success: bool = Field(
        ...,
        description="Whether the downstream invocation succeeded",
    )
    result: JsonValue | None = Field(
        default=None,
        description="JSON-compatible result payload if successful",
    )
    error: SanitizedErrorPayload | None = Field(
        default=None,
        description="Sanitized error payload if dispatch failed",
    )
    correlation_id: CorrelationIdentifier = Field(
        default_factory=lambda: str(uuid4()),
        description="Preserved request correlation identifier",
    )

    @field_validator("result", mode="before")
    @classmethod
    def validate_result_json_compatible(cls, v: object) -> object:
        """Enforce strict JSON compatibility on raw result before coercion."""
        if v is not None and not is_json_compatible(v):
            raise ValueError("Result must strictly contain JSON-compatible data types.")
        return v
