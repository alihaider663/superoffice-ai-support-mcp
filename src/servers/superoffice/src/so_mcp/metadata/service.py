"""Application service for SuperOffice metadata, administration, and scheduled tasks."""

import logging

from platform_security.interfaces import OutputSanitizer
from platform_security.sanitization import RecursiveOutputSanitizer
from so_mcp.metadata.contracts import (
    AssociateDetailCriteriaDTO,
    AssociateDetailDTO,
    ScheduledTaskItemDTO,
    SystemEventsCriteriaDTO,
    SystemEventsResultDTO,
    TicketCategoryItemDTO,
    TicketMetadataListsCriteriaDTO,
    TicketMetadataListsDTO,
)
from so_mcp.metadata.repository import MetadataRepositoryProtocol

logger = logging.getLogger(__name__)


class SuperOfficeMetadataService:
    """Service providing SuperOffice administrative lookup with PII and credential sanitization."""

    def __init__(
        self,
        repository: MetadataRepositoryProtocol,
        sanitizer: OutputSanitizer | None = None,
    ) -> None:
        self._repository = repository
        self._sanitizer = sanitizer or RecursiveOutputSanitizer()

    def _sanitize_string(self, text: str | None) -> str:
        if not text:
            return ""
        sanitized = self._sanitizer.sanitize(text)
        return str(sanitized) if sanitized is not None else ""

    def _sanitize_optional_string(self, text: str | None) -> str | None:
        if text is None:
            return None
        sanitized = self._sanitizer.sanitize(text)
        return str(sanitized) if sanitized is not None else None

    async def get_associate_details(
        self, criteria: AssociateDetailCriteriaDTO
    ) -> AssociateDetailDTO | None:
        """Retrieve sanitized associate/user profile."""
        profile = await self._repository.get_associate_details(criteria)
        if profile is None:
            return None

        return AssociateDetailDTO(
            associate_id=profile.associate_id,
            ejuser_id=profile.ejuser_id,
            name=self._sanitize_string(profile.name),
            username=self._sanitize_string(profile.username),
            first_name=self._sanitize_optional_string(profile.first_name),
            last_name=self._sanitize_optional_string(profile.last_name),
            title=self._sanitize_optional_string(profile.title),
            email=self._sanitize_string(profile.email),
            group_id=profile.group_id,
            group_name=self._sanitize_optional_string(profile.group_name),
            is_active=profile.is_active,
            default_category_id=profile.default_category_id,
        )

    async def get_ticket_metadata_lists(
        self, criteria: TicketMetadataListsCriteriaDTO
    ) -> TicketMetadataListsDTO:
        """Retrieve reference lists for categories, priorities, statuses, and groups."""
        raw_lists = await self._repository.get_ticket_metadata_lists(criteria)

        sanitized_cats = tuple(
            TicketCategoryItemDTO(
                category_id=c.category_id,
                name=c.name,
                fullname=c.fullname,
                parent_id=c.parent_id,
                delegate_method=c.delegate_method,
                notification_email=self._sanitize_optional_string(c.notification_email),
                closing_status=c.closing_status,
            )
            for c in raw_lists.categories
        )

        return TicketMetadataListsDTO(
            categories=sanitized_cats,
            priorities=raw_lists.priorities,
            statuses=raw_lists.statuses,
            user_groups=raw_lists.user_groups,
            total_categories=raw_lists.total_categories,
            total_priorities=raw_lists.total_priorities,
            total_statuses=raw_lists.total_statuses,
            total_user_groups=raw_lists.total_user_groups,
        )

    async def list_system_events_and_triggers(
        self, criteria: SystemEventsCriteriaDTO
    ) -> SystemEventsResultDTO:
        """Retrieve scheduled background jobs with sanitized error messages."""
        res = await self._repository.list_system_events_and_triggers(criteria)

        sanitized_tasks = tuple(
            ScheduledTaskItemDTO(
                task_id=t.task_id,
                schedule_id=t.schedule_id,
                task_name=t.task_name,
                script_id=t.script_id,
                script_identifier=t.script_identifier,
                script_include_id=t.script_include_id,
                is_disabled=t.is_disabled,
                execution_status=t.execution_status,
                minute_interval=t.minute_interval,
                last_execution=t.last_execution,
                next_execution=t.next_execution,
                execution_time_ms=t.execution_time_ms,
                error_message=self._sanitize_optional_string(t.error_message),
                last_error=t.last_error,
                retries=t.retries,
            )
            for t in res.tasks
        )

        return SystemEventsResultDTO(
            total_tasks=res.total_tasks,
            returned_tasks=len(sanitized_tasks),
            tasks=sanitized_tasks,
        )
