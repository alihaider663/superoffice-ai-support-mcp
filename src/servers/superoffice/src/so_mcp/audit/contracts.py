"""Contracts, DTOs, and mappings for SuperOffice ticket audit trail and change history."""

from datetime import datetime
from typing import Any

from pydantic import Field

from platform_core.errors import IntegrationError, ResourceNotFoundError
from platform_core.models import PlatformBaseModel


class SuperOfficeAuditError(IntegrationError):
    """Base error for SuperOffice ticket audit and history failures."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "SUPEROFFICE_AUDIT_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            system_name="SuperOffice",
            error_code=error_code,
            details=details,
        )


class SuperOfficeTicketAuditNotFoundError(ResourceNotFoundError):
    """Raised when an audit trail is requested for a nonexistent ticket."""

    def __init__(self, ticket_id: int) -> None:
        super().__init__(resource_type="SuperOffice Ticket", identifier=ticket_id)


# Standard SuperOffice log_action codes to descriptive names
SUPEROFFICE_STANDARD_LOG_ACTION_MAP: dict[int, str] = {
    1: "Ticket split",
    2: "Ticket created",
    3: "Message added",
    4: "Message edited",
    5: "Message deleted",
    6: "Ticket deleted",
    13: "Ticket updated",
    14: "Ticket merged",
    28: "Field values modified",
    32: "Read by owner",
    37: "Created by user",
}

# Standard SuperOffice log_change codes: mapping code -> (field_name, display_name)
SUPEROFFICE_STANDARD_LOG_CHANGE_MAP: dict[int, tuple[str, str]] = {
    1: ("registered", "Registered Timestamp"),
    2: ("title", "Title / Subject"),
    3: ("last_changed", "Last Changed Timestamp"),
    4: ("updated", "Updated Timestamp"),
    11: ("created_by", "Created By"),
    12: ("owner_id", "Owner / Assigned User"),
    13: ("priority_id", "Priority"),
    17: ("status_id", "Status"),
    22: ("category_id", "Category"),
    23: ("cust_id", "Customer Contact"),
    26: ("read_status", "Read Status"),
    27: ("activated", "Activated Timestamp"),
    28: ("field_change", "Field Change"),
    29: ("associate_id", "Associate"),
    33: ("extra_field", "Custom Extra Field"),
    34: ("deadline", "Deadline / Alert"),
    35: ("status", "Status Change"),
    36: ("registered_time", "Registered Timestamp"),
    49: ("snooze", "Snooze / Alert"),
}


class TicketLogMilestoneDTO(PlatformBaseModel):
    """High-level milestone log entry from dbo.ticket_log."""

    id: int = Field(..., description="Unique ticket_log row identifier")
    occurred_at: datetime | None = Field(default=None, description="Event occurrence timestamp")
    actor: str | None = Field(default=None, description="Actor login name or system tag")
    event_code: int | None = Field(default=None, description="SuperOffice log_code")
    description: str = Field(default="", description="Human-readable event summary")


class TicketFieldChangeDTO(PlatformBaseModel):
    """Atomic before/after field modification from dbo.ticket_log_change."""

    id: int = Field(..., description="Unique ticket_log_change row identifier")
    action_id: int = Field(..., description="Parent ticket_log_action identifier")
    field_name: str = Field(..., description="Normalized field name (standard or x_*)")
    display_name: str = Field(..., description="Human-readable field label")
    is_extra_field: bool = Field(
        default=False, description="Whether this is a user-defined extra field"
    )
    extra_field_id: int = Field(
        default=-1, description="Underlying extra_field_id (-1 for standard fields)"
    )
    change_type_code: int | None = Field(default=None, description="SuperOffice log_change code")
    from_value: str = Field(default="", description="Previous state or value")
    to_value: str = Field(default="", description="New state or value")


class TicketActionItemDTO(PlatformBaseModel):
    """Timestamped ticket action event from dbo.ticket_log_action."""

    action_id: int = Field(..., description="Unique ticket_log_action identifier")
    occurred_at: datetime | None = Field(default=None, description="Action timestamp")
    actor: str = Field(..., description="Actor login name or user ID representation")
    user_id: int = Field(..., description="Internal user ID (dbo.ejuser.id)")
    customer_id: int = Field(..., description="Customer ID (-1 if internal user)")
    action_code: int | None = Field(default=None, description="SuperOffice log_action code")
    action_name: str = Field(default="Unknown Action", description="Standard action description")
    description: str = Field(default="", description="Action description text")
    details: str | None = Field(default=None, description="Extended action details")
    changes: tuple[TicketFieldChangeDTO, ...] = Field(
        default=(),
        description="Granular field changes associated with this action",
    )


class TicketAuditCriteriaDTO(PlatformBaseModel):
    """Criteria for fetching ticket audit trail."""

    ticket_id: int = Field(..., ge=1, description="Target ticket identifier")
    include_field_changes: bool = Field(
        default=True,
        description="Whether to include atomic before/after field transitions",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum action records to return (1-100)",
    )


class TicketAuditTrailDTO(PlatformBaseModel):
    """Comprehensive chronological audit trail for a SuperOffice ticket."""

    ticket_id: int = Field(..., ge=1, description="Target ticket identifier")
    milestone_logs: tuple[TicketLogMilestoneDTO, ...] = Field(
        default=(),
        description="High-level milestone log entries (from ticket_log)",
    )
    actions: tuple[TicketActionItemDTO, ...] = Field(
        default=(),
        description="Timestamped user and system actions with field transitions",
    )
    total_milestones: int = Field(default=0, ge=0, description="Total milestone records returned")
    total_actions: int = Field(default=0, ge=0, description="Total action records returned")
    total_changes: int = Field(
        default=0, ge=0, description="Total field change transitions returned"
    )
