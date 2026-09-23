"""Data transfer objects and pagination models for SuperOffice domain entities."""

from datetime import UTC, datetime

from pydantic import Field

from platform_core.models import PlatformBaseModel
from platform_security.models import AttachmentMetadata

# ============================================================================
# 1. Search Criteria & Pagination DTOs (Localized to SuperOffice)
# ============================================================================


class SuperOfficePageRequest(PlatformBaseModel):
    """Pagination request parameters for SuperOffice queries."""

    page: int = Field(default=1, ge=1, description="1-indexed page number")
    page_size: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Items requested per page (max 100)",
    )


class SuperOfficePageResponse[T: PlatformBaseModel](PlatformBaseModel):
    """Generic bounded pagination envelope for SuperOffice query results."""

    items: tuple[T, ...] = Field(default=(), description="Page items")
    page: int = Field(..., ge=1, description="Current page number")
    page_size: int = Field(..., ge=1, description="Page size limit")
    total_items: int | None = Field(default=None, ge=0, description="Total matching items if known")
    has_next_page: bool = Field(default=False, description="Whether subsequent pages are available")


class TicketSearchCriteriaDTO(PlatformBaseModel):
    """Structured criteria for searching SuperOffice tickets."""

    title: str | None = Field(default=None, description="Ticket title substring filter")
    category: str | None = Field(default=None, description="Ticket category name filter")
    status: str | None = Field(default=None, description="Ticket status filter (e.g. Open)")
    category_id: int | None = Field(default=None, ge=1, description="Ticket category identifier")
    customer_id: int | None = Field(default=None, ge=1, description="Customer company or person ID")
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Page size limit")


class CompanySearchCriteriaDTO(PlatformBaseModel):
    """Structured criteria for searching SuperOffice companies."""

    name: str | None = Field(default=None, min_length=1, description="Company name prefix/match")
    category: str | None = Field(default=None, description="Company category name or code filter")
    company_id: int | None = Field(default=None, ge=1, description="Company numeric identifier")
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Page size limit")


class PersonSearchCriteriaDTO(PlatformBaseModel):
    """Structured criteria for searching SuperOffice persons/contacts."""

    name: str | None = Field(default=None, min_length=1, description="Person name prefix/match")
    email: str | None = Field(default=None, min_length=3, description="Person email address match")
    company_id: int | None = Field(default=None, ge=1, description="Associated company ID")
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Page size limit")


# ============================================================================
# 2. Internal Domain DTOs (Integration Adapter / Trusted Service Layer Boundary)
# ============================================================================


class TicketSummaryDomainDTO(PlatformBaseModel):
    """Internal domain summary representation of a ticket."""

    ticket_id: int = Field(..., ge=1, description="Unique ticket identifier")
    title: str = Field(..., description="Ticket subject title")
    status: str = Field(..., description="Ticket status")
    category: str = Field(..., description="Ticket category")
    priority: str = Field(..., description="Ticket priority level")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TicketDetailDomainDTO(PlatformBaseModel):
    """Internal domain detailed representation of a ticket."""

    ticket_id: int = Field(..., ge=1, description="Unique ticket identifier")
    title: str = Field(..., description="Ticket subject title")
    status: str = Field(..., description="Ticket status")
    category: str = Field(..., description="Ticket category")
    priority: str = Field(..., description="Ticket priority level")
    description: str = Field(default="", description="Internal unredacted ticket body description")
    assigned_to: str | None = Field(default=None, description="Assigned internal agent identifier")
    customer_id: int | None = Field(default=None, ge=1, description="Associated customer ID")
    customer_reference: str | None = Field(
        default=None, description="Internal customer reference code"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TicketMessageDomainDTO(PlatformBaseModel):
    """Internal domain representation of a ticket message exchange."""

    message_id: int = Field(..., ge=1, description="Message identifier")
    ticket_id: int = Field(..., ge=1, description="Parent ticket identifier")
    author: str = Field(..., description="Internal author name or email")
    author_type: str = Field(
        default="CUSTOMER",
        description="Author classification (CUSTOMER, AGENT, SYSTEM)",
    )
    body: str = Field(default="", description="Internal unredacted message text body")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    attachments: tuple[AttachmentMetadata, ...] = Field(
        default=(), description="Metadata of attached files"
    )


class CompanyDomainDTO(PlatformBaseModel):
    """Internal domain representation of a company."""

    company_id: int = Field(..., ge=1, description="Unique company identifier")
    name: str = Field(..., description="Company legal or trade name")
    department: str | None = Field(default=None, description="Company department")
    org_number: str | None = Field(default=None, description="Organization registration number")


class PersonDomainDTO(PlatformBaseModel):
    """Internal domain representation of a person/contact."""

    person_id: int = Field(..., ge=1, description="Unique person identifier")
    first_name: str = Field(..., description="Given name")
    last_name: str = Field(..., description="Family name")
    email: str | None = Field(default=None, description="Email address")
    phone: str | None = Field(default=None, description="Telephone number")
    company_id: int | None = Field(default=None, ge=1, description="Associated company identifier")


# ============================================================================
# 3. Minimized AI-Facing DTOs (Constructed post-PII scrubbing for AI Context)
# ============================================================================


class MinimizedTicketSummaryDTO(PlatformBaseModel):
    """AI-facing sanitized summary of a ticket."""

    ticket_id: int = Field(..., ge=1, description="Unique ticket identifier")
    title: str = Field(..., description="Ticket subject title")
    status: str = Field(..., description="Ticket status")
    category: str = Field(..., description="Ticket category")
    priority: str = Field(..., description="Ticket priority level")
    created_at: datetime = Field(..., description="Creation UTC timestamp")


class MinimizedTicketDetailDTO(PlatformBaseModel):
    """AI-facing sanitized detail of a ticket with masked PII and safe references."""

    ticket_id: int = Field(..., ge=1, description="Unique ticket identifier")
    title: str = Field(..., description="Ticket subject title")
    status: str = Field(..., description="Ticket status")
    category: str = Field(..., description="Ticket category")
    priority: str = Field(..., description="Ticket priority level")
    sanitized_description: str = Field(..., description="PII-scrubbed ticket description body")
    sanitized_customer_reference: str | None = Field(
        default=None,
        description="Opaque, non-PII internal customer reference code",
    )
    assigned_agent_id: str | None = Field(
        default=None,
        description="Opaque identifier of assigned support agent",
    )
    created_at: datetime = Field(..., description="Creation UTC timestamp")


class MinimizedTicketMessageDTO(PlatformBaseModel):
    """AI-facing sanitized ticket message item."""

    message_id: int = Field(..., ge=1, description="Message identifier")
    ticket_id: int = Field(..., ge=1, description="Parent ticket identifier")
    author_type: str = Field(..., description="Author classification (CUSTOMER, AGENT, SYSTEM)")
    sanitized_body: str = Field(..., description="PII-scrubbed message text body")
    created_at: datetime = Field(..., description="Creation UTC timestamp")
    attachments: tuple[AttachmentMetadata, ...] = Field(
        default=(),
        description="Safe metadata for attachments (no binary content)",
    )


class MinimizedCompanyDTO(PlatformBaseModel):
    """AI-facing sanitized company reference."""

    company_id: int = Field(..., ge=1, description="Company identifier")
    name: str = Field(..., description="Company name")


class MinimizedPersonDTO(PlatformBaseModel):
    """AI-facing sanitized person reference with customer PII removed."""

    person_id: int = Field(..., ge=1, description="Person identifier")
    display_name: str = Field(..., description="Sanitized display name or role label")
    company_id: int | None = Field(default=None, ge=1, description="Associated company identifier")
