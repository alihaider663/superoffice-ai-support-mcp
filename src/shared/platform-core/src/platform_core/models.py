"""Foundational domain models, base classes, and scalar types."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# Standard RFC3339 UTC serialization type
UtcTimestamp = Annotated[
    datetime,
    PlainSerializer(lambda dt: dt.astimezone(UTC).isoformat(), return_type=str),
]

# Standard Correlation Identifier type
CorrelationIdentifier = Annotated[
    str,
    Field(min_length=1, max_length=128, description="Unique correlation tracking identifier"),
]


class PlatformBaseModel(BaseModel):
    """Base model enforcing strict type validation and immutable value constraints."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class PrincipalIdentity(PlatformBaseModel):
    """Authenticated caller identity with role and privilege scopes."""

    user_id: str = Field(..., min_length=1, description="Unique subject or user identifier")
    role: str = Field(default="L1", description="Support engineer tier (L1, L2, L3)")
    scopes: tuple[str, ...] = Field(default=(), description="Orthogonal granted scopes")
    auth_method: str = Field(default="jwt", description="Authentication mechanism")


class AuditMetadata(PlatformBaseModel):
    """Audit metadata attached to state transitions and investigations."""

    correlation_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Trace correlation ID",
    )
    request_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Request identifier",
    )
    timestamp: UtcTimestamp = Field(default_factory=lambda: datetime.now(UTC))


class PageRequest(PlatformBaseModel):
    """Standard pagination request parameters."""

    page_number: int = Field(default=1, ge=1, description="1-indexed page number")
    page_size: int = Field(default=50, ge=1, le=100, description="Items per page")


class PageResponse(PlatformBaseModel):
    """Standard pagination envelope."""

    total_count: int = Field(ge=0, description="Total matching items across all pages")
    page_number: int = Field(ge=1, description="Current page number")
    page_size: int = Field(ge=1, description="Current page size")
    has_more: bool = Field(description="Whether subsequent pages are available")
