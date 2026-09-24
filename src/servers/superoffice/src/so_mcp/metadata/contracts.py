"""Contracts, DTOs, and error classes for SuperOffice metadata and administration."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SuperOfficeMetadataError(Exception):
    """Domain exception raised when metadata queries fail or timeout."""

    def __init__(
        self,
        message: str,
        error_code: str = "METADATA_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}


class AssociateDetailCriteriaDTO(BaseModel):
    """Criteria for looking up an internal SuperOffice associate/user."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    associate_id: int | None = Field(
        default=None, description="SuperOffice associate ID or ejuser ID"
    )
    username: str | None = Field(default=None, description="Username or login name")


class AssociateDetailDTO(BaseModel):
    """Detailed profile of an internal SuperOffice consultant or support engineer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    associate_id: int
    ejuser_id: int | None = None
    name: str
    username: str
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    email: str = ""
    group_id: int | None = None
    group_name: str | None = None
    is_active: bool = True
    default_category_id: int | None = None


class TicketCategoryItemDTO(BaseModel):
    """SuperOffice ticket category from EJ_CATEGORY."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category_id: int
    name: str
    fullname: str
    parent_id: int
    delegate_method: int
    notification_email: str | None = None
    closing_status: int


class TicketPriorityItemDTO(BaseModel):
    """SuperOffice ticket priority from TICKET_PRIORITY."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    priority_id: int
    name: str
    status: int
    sort_order: int
    flags: int


class TicketStatusItemDTO(BaseModel):
    """SuperOffice ticket status from TICKET_STATUS."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status_id: int
    name: str
    status_type: int
    ts_rank: int
    time_counter: int
    is_deleted: bool


class UserGroupItemDTO(BaseModel):
    """SuperOffice user group/department from USERGROUP."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    group_id: int
    name: str
    rank: int


class TicketMetadataListsCriteriaDTO(BaseModel):
    """Filter criteria for ticket metadata lists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    list_type: Literal["all", "category", "priority", "status", "group", "user_group"] = Field(
        default="all", description="Type of list to retrieve"
    )


class TicketMetadataListsDTO(BaseModel):
    """Collection of ticket metadata lookup tables."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    categories: tuple[TicketCategoryItemDTO, ...] = ()
    priorities: tuple[TicketPriorityItemDTO, ...] = ()
    statuses: tuple[TicketStatusItemDTO, ...] = ()
    user_groups: tuple[UserGroupItemDTO, ...] = ()
    total_categories: int = 0
    total_priorities: int = 0
    total_statuses: int = 0
    total_user_groups: int = 0


class ScheduledTaskItemDTO(BaseModel):
    """Scheduled background job executing a CRMScript from SCHEDULE and SCHEDULED_TASK."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: int
    schedule_id: int
    task_name: str
    script_id: int | None = None
    script_identifier: str | None = None
    script_include_id: str | None = None
    is_disabled: bool = False
    execution_status: int = 0
    minute_interval: int | None = None
    last_execution: str | None = None
    next_execution: str | None = None
    execution_time_ms: int | None = None
    error_message: str | None = None
    last_error: str | None = None
    retries: int = 0


class SystemEventsCriteriaDTO(BaseModel):
    """Criteria for filtering scheduled tasks and system event hooks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_type: Literal["all", "scheduled_task", "system_event"] = Field(
        default="all", description="Target event category"
    )
    include_disabled: bool = Field(default=True, description="Include disabled scheduled tasks")
    only_errors: bool = Field(
        default=False,
        description="Filter only to tasks with error status or messages",
    )
    query: str | None = Field(default=None, max_length=100, description="Optional search keyword")
    limit: int = Field(default=50, ge=1, le=100, description="Maximum number of items to return")


class SystemEventsResultDTO(BaseModel):
    """Response containing scheduled tasks and system event hooks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_tasks: int = 0
    returned_tasks: int = 0
    tasks: tuple[ScheduledTaskItemDTO, ...] = ()
