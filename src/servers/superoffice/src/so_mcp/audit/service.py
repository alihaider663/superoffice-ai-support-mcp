"""Application service for SuperOffice ticket audit trail and change history
with PII sanitization.
"""

import logging

from platform_security.interfaces import OutputSanitizer
from platform_security.sanitization import RecursiveOutputSanitizer
from so_mcp.audit.contracts import (
    TicketActionItemDTO,
    TicketAuditCriteriaDTO,
    TicketAuditTrailDTO,
    TicketFieldChangeDTO,
    TicketLogMilestoneDTO,
)
from so_mcp.audit.repository import TicketAuditRepositoryProtocol

logger = logging.getLogger(__name__)


class TicketAuditService:
    """Service providing ticket audit trail discovery with PII and credential sanitization."""

    def __init__(
        self,
        repository: TicketAuditRepositoryProtocol,
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

    async def get_ticket_audit_trail(
        self,
        criteria: TicketAuditCriteriaDTO,
    ) -> TicketAuditTrailDTO:
        """Fetch chronological audit trail and scrub sensitive PII/secrets."""
        raw_trail = await self._repository.get_ticket_audit_trail(criteria)

        # Sanitize milestones
        sanitized_milestones: list[TicketLogMilestoneDTO] = []
        for m in raw_trail.milestone_logs:
            sanitized_milestones.append(
                TicketLogMilestoneDTO(
                    id=m.id,
                    occurred_at=m.occurred_at,
                    actor=self._sanitize_optional_string(m.actor),
                    event_code=m.event_code,
                    description=self._sanitize_string(m.description),
                )
            )

        # Sanitize actions and nested field changes
        sanitized_actions: list[TicketActionItemDTO] = []
        for a in raw_trail.actions:
            sanitized_changes: list[TicketFieldChangeDTO] = []
            for c in a.changes:
                sanitized_changes.append(
                    TicketFieldChangeDTO(
                        id=c.id,
                        action_id=c.action_id,
                        field_name=c.field_name,
                        display_name=c.display_name,
                        is_extra_field=c.is_extra_field,
                        extra_field_id=c.extra_field_id,
                        change_type_code=c.change_type_code,
                        from_value=self._sanitize_string(c.from_value),
                        to_value=self._sanitize_string(c.to_value),
                    )
                )

            sanitized_actions.append(
                TicketActionItemDTO(
                    action_id=a.action_id,
                    occurred_at=a.occurred_at,
                    actor=self._sanitize_string(a.actor),
                    user_id=a.user_id,
                    customer_id=a.customer_id,
                    action_code=a.action_code,
                    action_name=a.action_name,
                    description=self._sanitize_string(a.description),
                    details=self._sanitize_optional_string(a.details),
                    changes=tuple(sanitized_changes),
                )
            )

        return TicketAuditTrailDTO(
            ticket_id=raw_trail.ticket_id,
            milestone_logs=tuple(sanitized_milestones),
            actions=tuple(sanitized_actions),
            total_milestones=len(sanitized_milestones),
            total_actions=len(sanitized_actions),
            total_changes=sum(len(a.changes) for a in sanitized_actions),
        )
